"""
PMJAY Agent Pipeline — v2 (patched)
All agents receive a plain dict (claim_context) instead of a Pydantic model.
Package data comes from the DB (already in context). No core.package_db import.

claim_context keys:
    claim_id, claim_ref, patient_id, patient_name, pmjay_number,
    patient_dob, patient_gender, package_code, package_name,
    hospital_id, admission_date, discharge_date,
    documents: list of dicts with keys:
        field_key, field_group, text_content, filename, content_base64

PATCH NOTES (v2.1):
    FIX-1: DocumentExtractor — PDF text extracted in-place on original doc dict (not copy)
    FIX-2: IdentityValidator — identity_map uses {doc, value} dicts instead of tuples
    FIX-3: ClinicalRelevance — template format includes package_code + icd10_codes
    FIX-4: LabAnalyzer — prompt explicitly instructs AI to analyze provided images
    FIX-5: BillingAnalyser — rate_display variable replaces f-string JSON injection
    FIX-6: ICPAgent + Discharge + Radiology — _normalize_flags handles dict/str flag types
    FIX-7: PackageCompliance — empty required_fields DB misconfiguration detected + flagged
    FIX-8: All agents — fallback score log messages match actual fallback values used
"""

import json
import time
import asyncio
import logging
from models.schemas import AgentResult, Flag, FlagSeverity
from .base_agent import BaseAgent
from langchain_core.prompts import PromptTemplate
from .prompts import (
    DOCUMENT_EXTRACTOR_PROMPT,
    IDENTITY_VALIDATOR_PROMPT,
    CLINICAL_RELEVANCE_PROMPT,
    LAB_ANALYZER_PROMPT,
    IMAGE_VALIDATOR_PROMPT,
    RADIOLOGY_VALIDATOR_PROMPT,
    BILLING_ANALYSER_PROMPT,
    DISCHARGE_SUMMARY_PROMPT,
    ICP_PROMPT
)

logger = logging.getLogger("uvicorn")


import re
from langchain_core.prompts import PromptTemplate

# ─────────────────────────────────────────
# Shared Utilities
# ─────────────────────────────────────────
def _is_probably_text_pdf(b64: str) -> bool:
    """PDF magic bytes check — same heuristic as existing FIX-1 logic."""
    return bool(b64) and b64.startswith("JVBERi")


def _build_field_list_str(fields: list[dict]) -> str:
    """
    fields: [{"field_name": "cluster_number", "label": "Cluster Number", "group": "History"}, ...]
    Falls back to a minimal generic set if the DB has no clinical_form_fields configured yet,
    so the agent still does something useful before an admin sets this up.
    """
    if not fields:
        fields = [
            {"field_name": "patient_name", "label": "Patient Name", "group": "Identity"},
            {"field_name": "cluster_number", "label": "Cluster Number", "group": "Diagnosis"},
            {"field_name": "diagnosis", "label": "Diagnosis", "group": "Diagnosis"},
            {"field_name": "care_plan", "label": "Care Plan", "group": "Treatment"},
        ]
    return "\n".join(
        f'- "{f["field_name"]}": {f["label"]} (group: {f.get("group", "general")})'
        for f in fields
    )
def _prepare_langchain_template(template_str: str) -> str:
    """
    Safely converts a raw prompt containing both {variables} and JSON {blocks}
    into a valid LangChain template by escaping the JSON braces.
    """
    if not template_str:
        return template_str
        
    # 1. Find all standard {variable_names} (letters, numbers, underscores)
    variables = set(re.findall(r'\{([a-zA-Z_][a-zA-Z0-9_]*)\}', template_str))
    
    # 2. Escape ALL { and } in the entire string to protect JSON blocks
    escaped_str = template_str.replace("{", "{{").replace("}", "}}")
    
    # 3. Un-escape ONLY the valid variables so LangChain can format them
    for var in variables:
        escaped_str = escaped_str.replace(f"{{{{{var}}}}}", f"{{{var}}}")
        
    return escaped_str


def _parse_ai_json(raw: str) -> tuple[dict, str | None]:
    """
    Parse model output into a dict. Repairs common Gemini mistakes:
    copied placeholders (<0-100>, <true/false>), trailing commas, Python booleans.
    Returns (object, error). error is None on success.
    """
    if raw is None or not str(raw).strip():
        return {}, "empty AI response"

    text = str(raw).strip().lstrip("\ufeff")
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]

    def _repair(s: str) -> str:
        s = (
            s.replace("\u201c", '"')
            .replace("\u201d", '"')
            .replace("\u2018", "'")
            .replace("\u2019", "'")
        )
        s = re.sub(r"\bTrue\b", "true", s)
        s = re.sub(r"\bFalse\b", "false", s)
        s = re.sub(r"\bNone\b", "null", s)
        s = re.sub(r"<0-100>", "70", s)
        s = re.sub(r"<true/false>", "false", s)
        s = re.sub(r"<issue description>", "unspecified issue", s)
        s = re.sub(r",\s*}", "}", s)
        s = re.sub(r",\s*]", "]", s)
        return s

    last_err = None
    for candidate in (text, _repair(text)):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj, None
            last_err = f"JSON root was {type(obj).__name__}, expected object"
        except json.JSONDecodeError as e:
            last_err = str(e)
    return {}, last_err or "unparseable JSON"


def _format_prompt_template(tmpl: PromptTemplate, format_kwargs: dict) -> str:
    """Format using only the template's declared variables. Missing keys → error."""
    values = {v: format_kwargs[v] for v in tmpl.input_variables}
    return tmpl.format(**values)


def _render_agent_prompt(
    agent_name: str,
    claim: dict,
    default_prompt: PromptTemplate,
    format_kwargs: dict,
    flags: list | None = None,
    affected_doc: str | None = None,
) -> str:
    """
    Prefer the prompt saved in agent_prompts (DB).
    If it is missing or fails for any reason, use the hardcoded default.
    """
    template_str = (claim.get("agent_prompts") or {}).get(agent_name)
    last_error = None

    if template_str and str(template_str).strip():
        candidates = []
        if "{{" in template_str:
            candidates.extend([template_str, _prepare_langchain_template(template_str)])
        else:
            candidates.extend([_prepare_langchain_template(template_str), template_str])

        seen: set[str] = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            try:
                tmpl = PromptTemplate.from_template(candidate)
                return _format_prompt_template(tmpl, format_kwargs)
            except Exception as e:
                last_error = e
                continue

        logger.warning(
            "[%s] DB prompt failed (%s: %s); using hardcoded default",
            agent_name,
            type(last_error).__name__ if last_error else "Error",
            last_error,
        )
        if flags is not None:
            flags.append(Flag(
                field="agent_prompt_template",
                severity=FlagSeverity.MEDIUM,
                reason=(
                    f"DB prompt for {agent_name} failed "
                    f"({type(last_error).__name__ if last_error else 'Error'}: {last_error}); "
                    f"used hardcoded default prompt."
                ),
                affected_doc=affected_doc,
            ))

    try:
        return _format_prompt_template(default_prompt, format_kwargs)
    except Exception as e:
        logger.error("[%s] hardcoded default prompt failed: %s", agent_name, e)
        raise

def _docs_by_group(documents: list[dict], *groups: str) -> list[dict]:
    return [d for d in documents if d.get("field_group") in groups]

def _docs_by_relevant_groups(documents: list[dict], relevant_groups: list[str]) -> list[dict]:
    """Filter documents whose field_group is in the given relevant groups list (from DB)."""
    return [d for d in documents if d.get("field_group") in relevant_groups]

def _clinical_docs(documents: list[dict], clinical_groups: list[str]) -> list[dict]:
    """Filter documents whose field_group is marked clinical_relevant in the DB."""
    return [d for d in documents if d.get("field_group") in clinical_groups]

def _text_docs(documents: list[dict]) -> list[dict]:
    return _docs_by_group(documents, "text", "ot_notes")

def _pathology_docs(documents: list[dict]) -> list[dict]:
    return _docs_by_group(documents, "pathology")

def _radiology_docs(documents: list[dict]) -> list[dict]:
    return _docs_by_group(documents, "radiology")

def _others_docs(documents: list[dict]) -> list[dict]:
    return _docs_by_group(documents, "others")


def _normalize_flags(raw_flags: list, field: str) -> list:
    """
    FIX-6: Accepts a list of str OR dict flags from AI responses and returns
    a typed Flag list. Prevents stringified-dict reasons when prompts return
    structured {issue, severity, error_code} objects.
    """
    result = []
    for f in raw_flags:
        if isinstance(f, dict):
            raw_sev = f.get("severity", "MEDIUM").upper()
            try:
                sev = FlagSeverity[raw_sev]
            except KeyError:
                sev = FlagSeverity.MEDIUM
            result.append(Flag(
                field=field,
                severity=sev,
                reason=f.get("issue") or f.get("reason") or str(f),
            ))
        elif isinstance(f, str) and f.strip():
            result.append(Flag(field=field, severity=FlagSeverity.MEDIUM, reason=f))
    return result

# ─────────────────────────────────────────────────────────────
# 1. DocumentExtractorAgent — REPLACEMENT
# ─────────────────────────────────────────────────────────────

class DocumentExtractorAgent(BaseAgent):
    """
    Extracts structured, per-field-confidence-scored data from ONE document at a time.
    Falls back to vision (sends the raw image/PDF bytes to the AI) whenever there is
    no usable embedded text layer — this is the fix for scanned/handwritten forms such
    as pre-auth clinical notes that previously extracted to near-nothing.
    """
    name = "DocumentExtractorAgent"

    async def run(self, claim: dict, context: dict) -> AgentResult:
        flags = []
        extracted_docs = {}
        documents = claim.get("documents", [])
        field_list_str = _build_field_list_str(claim.get("clinical_form_fields", []))

        async def process_doc(doc):
            field_key   = doc.get("field_key", "unknown")
            field_group = doc.get("field_group", "")
            filename    = doc.get("filename") or field_key
            content     = doc.get("text_content") or ""
            b64         = doc.get("content_base64")

            # Try embedded PDF text extraction first (unchanged from FIX-1)
            if not content and b64 and _is_probably_text_pdf(b64):
                try:
                    import fitz
                    pdf_bytes = base64.b64decode(b64)
                    pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                    extracted_text = [page.get_text() for page in pdf_doc]
                    content = "\n".join(extracted_text).strip()
                    doc["text_content"] = content  # propagate to original list item
                except Exception as e:
                    logger.warning(f"Failed to extract text from PDF {filename}: {e}")

            # NEW: vision fallback — if there is STILL no usable text (scanned/handwritten
            # PDF, or a plain image), send the image bytes directly to the AI instead of
            # silently extracting nothing.
            images_b64 = []
            use_vision = False
            if (not content or len(content.strip()) < 20) and b64:
                images_b64 = [b64]
                use_vision = True
                image_instruction = (
                    f"IMPORTANT: This document ({filename}) has no reliable extracted text. "
                    f"An image of the document is attached. Read it directly, including any "
                    f"handwritten fields, tables, and checkboxes. Expand common clinical "
                    f"abbreviations but preserve the original text in the 'raw' field."
                )
            else:
                image_instruction = ""

            format_kwargs = dict(
                field_key=field_key,
                field_group=field_group,
                filename=filename,
                content=content[:3000] if content else "(no usable text layer — see attached image)",
                field_list=field_list_str,
                image_instruction=image_instruction,
            )
            ai_prompt = _render_agent_prompt(
                self.name, claim, DOCUMENT_EXTRACTOR_PROMPT, format_kwargs,
                flags=flags, affected_doc=field_key,
            )

            raw = await self._call_ai(ai_prompt, images=images_b64)

            logger.info(f"[{self.name}] Model response for {filename} ({field_key}) "
                        f"[vision={use_vision}]: {raw}")

            local_flags = []
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {"fields": {}, "investigations_mentioned": [], "status": "parse_error"}
                local_flags.append(Flag(
                    field=field_key,
                    severity=FlagSeverity.MEDIUM,
                    reason=f"AI extraction returned unparseable response for {filename}",
                    affected_doc=field_key,
                ))

            # Surface low-confidence / not_found fields as visible flags rather than
            # silently returning them in a blob — this is what feeds the frontend
            # "needs review" indicator per field.
            for fname, fdata in (parsed.get("fields") or {}).items():
                if not isinstance(fdata, dict):
                    continue
                conf = fdata.get("confidence")
                if conf == "low":
                    local_flags.append(Flag(
                        field=fname,
                        severity=FlagSeverity.LOW,
                        reason=f"Low-confidence extraction for '{fname}' in {filename} "
                               f"(handwriting/legibility) — recommend human verification.",
                        affected_doc=field_key,
                    ))

            return field_key, {
                "field_group":              field_group,
                "filename":                 filename,
                "used_vision":              use_vision,
                "fields":                   parsed.get("fields", {}),
                "investigations_mentioned": parsed.get("investigations_mentioned", []),
            }, local_flags

        results = await asyncio.gather(*(process_doc(d) for d in documents))

        for f_key, data, f_flags in results:
            extracted_docs[f_key] = data
            flags.extend(f_flags)

        return AgentResult(
            agent_name=self.name,
            score=100.0,
            passed=True,
            flags=flags,
            details={"extracted_documents": extracted_docs},
        )


# ─────────────────────────────────────────────────────────────
# 2. ClaimSynthesisAgent — NEW
# ─────────────────────────────────────────────────────────────

class ClaimSynthesisAgent(BaseAgent):
    """
    Runs ONCE per claim, after DocumentExtractorAgent. Consolidates all
    per-document extractions into a single authoritative claim record and
    performs cross-document checks (date logic, missing procedure codes,
    documents present/missing, conflicting facts) that no single per-document
    call can see. Infrastructure agent — excluded from weighted scoring,
    same as DocumentExtractorAgent (weight defaults to 0.0).
    """
    name = "ClaimSynthesisAgent"

    async def run(self, claim: dict, context: dict) -> AgentResult:
        flags = []
        extracted_documents = context.get("DocumentExtractorAgent", {}).get("extracted_documents", {})
        required_fields = claim.get("required_fields", [])
        documents = claim.get("documents", [])

        submitted_field_keys = sorted({
            d["field_key"] for d in documents
            if d.get("text_content") or d.get("filename") or d.get("content_base64")
        })

        if not extracted_documents:
            return AgentResult(
                agent_name=self.name,
                score=100.0,
                passed=True,
                flags=[Flag(
                    field="claim_synthesis",
                    severity=FlagSeverity.MEDIUM,
                    reason="No per-document extraction data available — synthesis skipped.",
                )],
                details={"note": "DocumentExtractorAgent produced no extracted documents."},
            )

        format_kwargs = dict(
            extracted_documents_json=json.dumps(extracted_documents, indent=2)[:12000],
            required_fields_json=json.dumps(required_fields, indent=2),
            submitted_field_keys=json.dumps(submitted_field_keys),
        )
        ai_prompt = _render_agent_prompt(
            self.name, claim, CLAIM_SYNTHESIS_PROMPT, format_kwargs, flags=flags,
        )

        raw = await self._call_ai(ai_prompt)

        logger.info(f"[{self.name}] Model response: {raw}")

        try:
            result = json.loads(raw)
            has_decode_error = False
        except json.JSONDecodeError:
            # Conservative fallback: DO NOT assume clean — surface a flag that forces
            # human review rather than silently proceeding with an empty record.
            result = {
                "critical_flags": [{
                    "flag": "SYNTHESIS_PARSE_ERROR",
                    "detail": "AI claim synthesis returned unparseable JSON; claim-level "
                              "consolidation (documents_present/missing, date logic, "
                              "procedure code check) could not be verified — manual review required.",
                }],
                "documents_present": [],
                "documents_missing_mandatory": [],
                "documents_missing_optional": [],
            }
            has_decode_error = True

        # Convert critical_flags (structured {flag, detail}) into typed Flag objects.
        # Severity: date/amount/procedure/PMJAY-ID issues are HIGH (they are the same
        # class of issue that would cause a real TPA rejection); DATA_CONFLICT is MEDIUM
        # since it needs human judgment rather than being an outright blocker.
        HIGH_SEVERITY_CODES = {
            "PMJAY_ID_INVALID", "DATE_LOGIC_ERROR",
            "AMOUNT_MISSING", "PROCEDURE_CODE_ABSENT", "SYNTHESIS_PARSE_ERROR",
        }
        for cf in result.get("critical_flags", []):
            code = cf.get("flag", "UNKNOWN_FLAG")
            severity = FlagSeverity.HIGH if code in HIGH_SEVERITY_CODES else FlagSeverity.MEDIUM
            flags.append(Flag(
                field="claim_synthesis",
                severity=severity,
                reason=f"[{code}] {cf.get('detail', 'No detail provided.')}",
            ))

        missing_mandatory = result.get("documents_missing_mandatory", [])
        for label in missing_mandatory:
            flags.append(Flag(
                field="documents_missing_mandatory",
                severity=FlagSeverity.HIGH,
                reason=f"Mandatory document missing (confirmed at claim-synthesis level): {label}",
            ))

        # Hard-block-eligible conditions surfaced explicitly so the orchestrator can
        # read them the same structured way it reads Identity/Compliance/Billing —
        # NOT via substring matching on flag text (fixes the radiology-style fragility
        # noted in the architecture review).
        hard_block_codes = {"DATE_LOGIC_ERROR", "PROCEDURE_CODE_ABSENT"}
        hard_block = any(cf.get("flag") in hard_block_codes for cf in result.get("critical_flags", []))

        score = 50.0 if has_decode_error else 100.0  # synthesis has no "quality score" of its
        # own by design — it's a consolidation/fact-check step, not a validator being scored.
        # 100 on success just means "synthesis ran"; hard_block/flags carry the actual signal.
        # This agent's weight should be 0.0 in scoring_weights (infrastructure agent).

        return AgentResult(
            agent_name=self.name,
            score=score,
            passed=not hard_block,
            flags=flags,
            details={
                **result,
                "hard_block": hard_block,
            },
        )
# ─────────────────────────────────────────
# 2. Identity Validator Agent
# ─────────────────────────────────────────

class IdentityValidatorAgent(BaseAgent):
    """
    Cross-matches patient name, age, date, hospital across ALL documents.
    Any mismatch → HIGH severity flag + hard identity failure.
    """
    name = "IdentityValidatorAgent"

    async def run(self, claim: dict, context: dict) -> AgentResult:
        flags = []
        extracted = context.get("DocumentExtractorAgent", {}).get("extracted_documents", {})

        identity_groups = claim.get("identity_relevant_groups", [])

        # FIX-2: Use {doc, value} dicts instead of tuples.
        # Tuples serialise as JSON arrays ([field_key, name]) which is ambiguous to the AI.
        # Dicts are self-documenting: {"doc": "discharge_summary", "value": "Mr Patel"}.
        identity_map = {"names": [], "ages": [], "hospitals": [], "pmjay_ids": []}

        for field_key, doc_data in extracted.items():
            if identity_groups:
                doc_group = doc_data.get("field_group", "")
                if doc_group not in identity_groups:
                    continue

            e = doc_data.get("extracted", {})
            if not isinstance(e, dict):
                continue

            name = e.get("patient_name") or e.get("name")
            if name:
                identity_map["names"].append({"doc": field_key, "value": name})

            age = e.get("patient_age") or e.get("dob") or e.get("patient_dob") or e.get("age")
            if age:
                identity_map["ages"].append({"doc": field_key, "value": age})

            hospital = e.get("hospital_name") or e.get("hospital")
            if hospital:
                identity_map["hospitals"].append({"doc": field_key, "value": hospital})

            pmjay = e.get("pmjay_id") or e.get("pmjay_number") or e.get("beneficiary_id")
            if pmjay:
                identity_map["pmjay_ids"].append({"doc": field_key, "value": pmjay})

        has_identity_data = any(len(lst) > 0 for lst in identity_map.values())
        if not has_identity_data:
            return AgentResult(
                agent_name=self.name,
                score=100,
                passed=True,
                flags=[],
                details={
                    "identity_map": identity_map,
                    "hard_block": False,
                    "mismatches": [],
                    "note": "No identity fields extracted from submitted documents."
                },
            )

        format_kwargs = dict(
            patient_name=claim["patient_name"],
            patient_dob=claim.get("patient_dob", "N/A"),
            patient_gender=claim["patient_gender"],
            pmjay_number=claim.get("pmjay_number", "N/A"),
            hospital_id=claim["hospital_id"],
            admission_date=claim["admission_date"],
            discharge_date=claim.get("discharge_date", "N/A"),
            identity_map=json.dumps(identity_map, indent=2),
        )
        ai_prompt = _render_agent_prompt(
            self.name, claim, IDENTITY_VALIDATOR_PROMPT, format_kwargs, flags=flags,
        )

        raw = await self._call_ai(ai_prompt)
        decode_error_msg = ""
        raw_preview = ""
        try:
            result = json.loads(raw)
            has_decode_error = False
        except json.JSONDecodeError as e:
            result = {"identity_score": 50, "mismatches": [], "hard_block": False}
            has_decode_error = True
            decode_error_msg = str(e)
            raw_preview = repr(raw)[:200]

        mismatches = result.get("mismatches", [])
        for m in mismatches:
            flags.append(Flag(
                field="patient_identity",
                severity=FlagSeverity.HIGH,
                reason=m,
            ))

        score = result.get("identity_score")
        if score is None:
            # FIX-8: fallback value 100 — message says 100
            score = 100
            flags.append(Flag(
                field="system_fallback",
                severity=FlagSeverity.MEDIUM,
                reason="System fallback score of 100 was used because AI identity validation returned a null/empty score."
            ))
        elif has_decode_error:
            # FIX-8: fallback value 50 (already set above) — message says 50
            flags.append(Flag(
                field="system_fallback",
                severity=FlagSeverity.MEDIUM,
                reason=f"System fallback score of 50 was used because AI identity validation returned unparseable JSON. "
                       f"Error: {decode_error_msg}. Raw: {raw_preview}"
            ))

        passed = not result.get("hard_block", False) and len(mismatches) == 0

        return AgentResult(
            agent_name=self.name,
            score=score,
            passed=passed,
            flags=flags,
            details={
                "identity_map": identity_map,
                "hard_block":   result.get("hard_block", False),
                "mismatches":   mismatches,
            },
        )


# ─────────────────────────────────────────
# 3. Package Compliance Agent
# ─────────────────────────────────────────

class PackageComplianceAgent(BaseAgent):
    """
    Verifies that all required field_keys for the package were submitted.
    Required field list comes from claim_context (already fetched from DB).
    Pure rule-based — no AI needed.
    """
    name = "PackageComplianceAgent"

    async def run(self, claim: dict, context: dict) -> AgentResult:
        flags = []
        documents       = claim.get("documents", [])
        required_fields = claim.get("required_fields", [])

        # FIX-7: Detect DB misconfiguration — empty required_fields is a config problem,
        # not a pass. Emit a MEDIUM flag so reviewers know the check was skipped.
        if not required_fields:
            flags.append(Flag(
                field="package_config",
                severity=FlagSeverity.MEDIUM,
                reason="No required fields configured for this package in the database. "
                       "Package compliance check was skipped — verify package setup in admin.",
            ))
            return AgentResult(
                agent_name=self.name,
                score=100.0,
                passed=True,
                flags=flags,
                details={
                    "package_name":      claim["package_name"],
                    "missing_mandatory": [],
                    "missing_optional":  [],
                    "hard_block":        False,
                    "note":              "required_fields empty — DB config issue",
                },
            )

        submitted_keys = {d["field_key"] for d in documents if
                          d.get("text_content") or d.get("filename")}

        clinical_groups = set(claim.get("clinical_relevant_groups", []))
        clinical_text = ""
        for d in documents:
            if d.get("field_group") in clinical_groups:
                clinical_text += f"\n{d.get('text_content') or ''}"
        clinical_text_lower = clinical_text.lower()

        keyword_mappings = {
            "pathology_abg": ["abg", "arterial blood gas", "acidosis"],
            "pathology_upcr": ["upcr", "urine protein", "creatinine ratio", "proteinuria"],
            "pathology_calcium_phos": ["calcium", "phosphorus", "phos", "ca2+", "po4-"],
            "radiology_renal_doppler": ["renal doppler", "color doppler", "renal artery doppler"],
            "pathology_lactate": ["lactate", "lactic acid"],
            "pathology_crp_pct": ["crp", "c-reactive protein", "procalcitonin", "pct"],
            "radiology_usg_abdomen": ["usg abdomen", "ultrasound abdomen", "usg abd"],
            "pathology_fbs_hba1c": ["hba1c", "fbs", "fasting blood sugar", "sugar level", "diabetes"],
            "pathology_cpk_mb": ["cpk", "cpk-mb", "creatine kinase"],
            "radiology_tmt_stress_echo": ["tmt", "treadmill test", "stress echo"],
            "radiology_ffr": ["ffr", "fractional flow reserve"],
            "radiology_post_ptca_ecg": ["post-ptca ecg", "post op ecg"],
            "pathology_sodium_osmolality": ["sodium", "na+", "osmolality"],
            "pathology_csf_analysis": ["csf", "cerebrospinal fluid", "xanthochromia"],
            "radiology_tcd": ["tcd", "transcranial doppler", "vasospasm"],
            "pathology_pth": ["pth", "parathyroid", "parathormone"],
            "pathology_iron_profile": ["iron profile", "ferritin", "tibc", "transferrin"],
            "radiology_av_fistula_doppler": ["av fistula", "fistula doppler", "shunt doppler"],
            "pathology_d_dimer": ["d-dimer", "ddimer"],
            "pathology_sputum_culture": ["sputum culture", "sputum c/s"],
            "radiology_ugi_endoscopy": ["ugi endoscopy", "upper gi endoscopy", "varices", "endoscopy report"],
        }

        missing_mandatory = []
        missing_optional  = []

        for req in required_fields:
            key       = req["field_key"]
            label     = req["label"]
            mandatory = req["mandatory"]

            if key not in submitted_keys:
                if mandatory:
                    missing_mandatory.append(label)
                    flags.append(Flag(
                        field=key,
                        severity=FlagSeverity.HIGH,
                        reason=f"Mandatory document missing: {label}",
                    ))
                else:
                    missing_optional.append(label)
                    kws = keyword_mappings.get(key, [])
                    mentioned = any(kw in clinical_text_lower for kw in kws)

                    if mentioned:
                        flags.append(Flag(
                            field=key,
                            severity=FlagSeverity.MEDIUM,
                            reason=f"Optional document '{label}' is missing but was mentioned/recommended in the clinical findings.",
                        ))
                    else:
                        flags.append(Flag(
                            field=key,
                            severity=FlagSeverity.LOW,
                            reason=f"Optional document not submitted: {label}",
                        ))

        total_required = sum(1 for r in required_fields if r["mandatory"])
        present        = total_required - len(missing_mandatory)
        score          = (present / total_required * 100) if total_required else 100.0
        hard_block     = len(missing_mandatory) > 2

        return AgentResult(
            agent_name=self.name,
            score=round(score, 2),
            passed=len(missing_mandatory) == 0,
            flags=flags,
            details={
                "package_name":      claim["package_name"],
                "missing_mandatory": missing_mandatory,
                "missing_optional":  missing_optional,
                "hard_block":        hard_block,
            },
        )


# ─────────────────────────────────────────
# 4. Clinical Relevance Agent
# ─────────────────────────────────────────
import datetime

def _compute_patient_age(claim: dict) -> str:
    """
    Returns patient age as a string for prompt injection.
    Uses claim['patient_age'] directly if present; otherwise computes
    from patient_dob relative to admission_date (falls back to today
    if admission_date is missing/unparseable).
    """
    age = claim.get("patient_age")
    if age not in (None, "", "N/A"):
        return str(age)

    dob_raw = claim.get("patient_dob")
    if not dob_raw or dob_raw == "N/A":
        return "N/A"

    try:
        dob = datetime.date.fromisoformat(str(dob_raw)[:10])
    except (ValueError, TypeError):
        return "N/A"

    ref_raw = claim.get("admission_date")
    try:
        ref_date = datetime.date.fromisoformat(str(ref_raw)[:10]) if ref_raw and ref_raw != "N/A" else datetime.date.today()
    except (ValueError, TypeError):
        ref_date = datetime.date.today()

    years = ref_date.year - dob.year - ((ref_date.month, ref_date.day) < (dob.month, dob.day))
    return str(years)


class ClinicalRelevanceAgent(BaseAgent):
    """
    Scores whether the pre-auth clinical note is internally consistent
    with the claimed patient identity and PM-JAY cluster, and evaluates
    documentation quality. Also extracts doctor-recommended lab/radiology
    tests (informational only — does not affect score).

    VISION FIX: handwritten/scanned clinical notes (text_content empty,
    content_base64 present) are now read via image, matching the pattern
    used by LabAnalyzerAgent / RadiologyValidatorAgent / DischargeSummaryAnalyserAgent.
    """
    name = "ClinicalRelevanceAgent"

    async def run(self, claim: dict, context: dict) -> AgentResult:
        flags    = []
        documents = claim.get("documents", [])
        clinical_groups = claim.get("clinical_relevant_groups", [])
        text_docs = _clinical_docs(documents, clinical_groups) if clinical_groups else _text_docs(documents)

        if not text_docs:
            return AgentResult(
                agent_name=self.name,
                score=0,
                passed=False,
                flags=[Flag(
                    field="clinical_text",
                    severity=FlagSeverity.HIGH,
                    reason="No clinical text documents submitted (no field groups marked as clinical_relevant)",
                )],
            )

        valid_text_docs = [
            d for d in text_docs
            if (d.get("text_content") and d["text_content"].strip())
               or d.get("content_base64")
               or d.get("filename")
        ]

        if not valid_text_docs:
            return AgentResult(
                agent_name=self.name,
                score=70,
                passed=True,
                flags=[Flag(
                    field="clinical_text",
                    severity=FlagSeverity.MEDIUM,
                    reason="Clinical documents were submitted but all have empty/null content",
                )],
                details={"note": "All clinical document entries are empty"},
            )

        flag_field = valid_text_docs[0]["field_key"]

        notes_summary = "\n".join(
            f"[{d['field_key']}]: {(d.get('text_content') or '(binary file)')[:400]}"
            for d in valid_text_docs
        )

        images_b64 = [d["content_base64"] for d in valid_text_docs if d.get("content_base64")]

        image_instruction = ""
        if images_b64:
            image_instruction = f"""
IMPORTANT: {len(images_b64)} clinical document image(s) are attached to this prompt.
Each image corresponds to a document listed above showing "(binary file)" in the
content section. Read the handwritten/scanned content directly from the attached
image(s) — including patient details, diagnosis, and care plan — instead of
relying on the placeholder text.
"""

        format_kwargs = dict(
            patient_name=claim.get("patient_name", "N/A"),
            patient_age=_compute_patient_age(claim),
            patient_gender=claim.get("patient_gender", "N/A"),
            package_code=claim.get("package_code", "N/A"),
            package_name=claim.get("package_name", "N/A"),
            admission_date=claim.get("admission_date", "N/A"),
            discharge_date=claim.get("discharge_date", "N/A"),
            notes_summary=notes_summary,
            image_instruction=image_instruction,
        )
        ai_prompt = _render_agent_prompt(
            self.name, claim, CLINICAL_RELEVANCE_PROMPT, format_kwargs, flags=flags,
        )

        raw = await self._call_ai(ai_prompt, images=images_b64)

        try:
            result = json.loads(raw)
            has_decode_error = False
        except json.JSONDecodeError:
            result = {
                "overall_score": 70,
                "flags": [],
                "identity_match": True,
                "cluster_match": True,
                "recommended_lab_tests": [],
                "recommended_radiology_tests": [],
            }
            has_decode_error = True

        flags.extend(_normalize_flags(result.get("flags", []), flag_field))

        score = result.get("overall_score")
        if score is None:
            score = 70
            flags.append(Flag(
                field="system_fallback",
                severity=FlagSeverity.MEDIUM,
                reason="System fallback score of 70 was used because AI clinical relevance judgment returned a null/empty score."
            ))
        elif has_decode_error:
            flags.append(Flag(
                field="system_fallback",
                severity=FlagSeverity.MEDIUM,
                reason="System fallback score of 70 was used because AI clinical relevance judgment returned unparseable JSON."
            ))

        return AgentResult(
            agent_name=self.name,
            score=score,
            passed=score >= 60,
            flags=flags,
            details=result,
        )
# ─────────────────────────────────────────
# 5. Lab Analyzer Agent
# ─────────────────────────────────────────

class LabAnalyzerAgent(BaseAgent):
    """
    Analyzes pathology/lab reports.
    Checks H/L flags, required tests, date range, patient name match.
    """
    name = "LabAnalyzerAgent"

    async def run(self, claim: dict, context: dict) -> AgentResult:
        flags    = []
        documents = claim.get("documents", [])

        lab_groups = claim.get("lab_relevant_groups", [])
        lab_docs = _docs_by_relevant_groups(documents, lab_groups) if lab_groups else _pathology_docs(documents)

        if not lab_docs:
            return AgentResult(
                agent_name=self.name,
                score=80,
                passed=True,
                flags=[],
                details={"note": "No pathology/lab reports submitted"},
            )

        valid_lab_docs = [
            d for d in lab_docs
            if (d.get("text_content") and d["text_content"].strip())
               or d.get("content_base64")
               or d.get("filename")
        ]

        if not valid_lab_docs:
            return AgentResult(
                agent_name=self.name,
                score=80,
                passed=True,
                flags=[Flag(
                    field="lab_report",
                    severity=FlagSeverity.MEDIUM,
                    reason="Lab documents were submitted but all have empty/null content",
                )],
                details={"note": "All lab document entries are empty"},
            )

        filenames = [d.get("filename", d["field_key"]) for d in valid_lab_docs]

        lab_summary = "\n".join(
            f"[{d.get('filename', d['field_key'])}]: {(d.get('text_content') or '(binary file)')[:400]}"
            for d in valid_lab_docs
        )

        images_b64 = [d["content_base64"] for d in valid_lab_docs if d.get("content_base64")]

        image_instruction = ""
        if images_b64:
            image_instruction = f"""
IMPORTANT: {len(images_b64)} lab report image(s) are attached to this prompt.
Each image corresponds to the filename(s) listed above in the same order.
For any entry showing "(binary file)" in the content section, extract all lab
values, dates, and patient details directly from the attached image instead.
"""

        format_kwargs = dict(
            package_name=claim["package_name"],
            patient_name=claim["patient_name"],
            admission_date=claim["admission_date"],
            discharge_date=claim["discharge_date"],
            filenames=filenames,
            image_instruction=image_instruction,
            lab_summary=lab_summary,
        )
        ai_prompt = _render_agent_prompt(
            self.name, claim, LAB_ANALYZER_PROMPT, format_kwargs, flags=flags,
        )

        raw = await self._call_ai(ai_prompt, images=images_b64)

        try:
            result = json.loads(raw)
            has_decode_error = False
        except json.JSONDecodeError:
            result = {"lab_score": 70, "flags": [], "extracted_values": []}
            has_decode_error = True

        # FIX-6: normalize flags
        flags.extend(_normalize_flags(result.get("flags", []), "lab_report"))

        score = result.get("lab_score")
        if score is None:
            # FIX-8: fallback 80 — message says 80
            score = 80
            flags.append(Flag(
                field="system_fallback",
                severity=FlagSeverity.MEDIUM,
                reason="System fallback score of 80 was used because AI lab reports analysis returned a null/empty score."
            ))
        elif has_decode_error:
            # FIX-8: fallback 70 (set above in except block) — message says 70
            flags.append(Flag(
                field="system_fallback",
                severity=FlagSeverity.MEDIUM,
                reason="System fallback score of 70 was used because AI lab reports analysis returned unparseable JSON."
            ))

        return AgentResult(
            agent_name=self.name,
            score=score,
            passed=score >= 60,
            flags=flags,
            details=result,
        )


# ─────────────────────────────────────────
# 6. Image Validator Agent
# ─────────────────────────────────────────

class ImageValidatorAgent(BaseAgent):
    """
    Checks surgery/procedure photos (from 'others' group) for relevance.
    Uses AI vision when base64 content is available.
    """
    name = "ImageValidatorAgent"

    async def run(self, claim: dict, context: dict) -> AgentResult:
        flags      = []
        documents  = claim.get("documents", [])

        image_groups = claim.get("image_relevant_groups", [])
        image_docs = _docs_by_relevant_groups(documents, image_groups) if image_groups else _others_docs(documents)

        if not image_docs:
            return AgentResult(
                agent_name=self.name,
                score=100,
                passed=True,
                flags=[],
                details={"note": "No image/other documents submitted"},
            )

        images_b64 = [d["content_base64"] for d in image_docs if d.get("content_base64")]

        format_kwargs = dict(
            package_name=claim["package_name"],
            filenames=[d.get("filename", d["field_key"]) for d in image_docs],
        )
        ai_prompt = _render_agent_prompt(
            self.name, claim, IMAGE_VALIDATOR_PROMPT, format_kwargs, flags=flags,
        )

        raw = await self._call_ai(ai_prompt, images=images_b64)
        try:
            result = json.loads(raw)
            has_decode_error = False
        except json.JSONDecodeError:
            result = {"image_score": 75, "relevant": True, "flags": []}
            has_decode_error = True

        # FIX-6: normalize flags
        flags.extend(_normalize_flags(result.get("flags", []), "other_documents"))

        score = result.get("image_score")
        if score is None:
            # FIX-8: fallback 75 — message says 75
            score = 75
            flags.append(Flag(
                field="system_fallback",
                severity=FlagSeverity.MEDIUM,
                reason="System fallback score of 75 was used because AI image validation returned a null/empty score."
            ))
        elif has_decode_error:
            # FIX-8: fallback 75 (set above) — message says 75
            flags.append(Flag(
                field="system_fallback",
                severity=FlagSeverity.MEDIUM,
                reason="System fallback score of 75 was used because AI image validation returned unparseable JSON."
            ))

        return AgentResult(
            agent_name=self.name,
            score=score,
            passed=result.get("relevant", True),
            flags=flags,
            details=result,
        )


# ─────────────────────────────────────────
# 7. Radiology Validator Agent
# ─────────────────────────────────────────

class RadiologyValidatorAgent(BaseAgent):
    """
    Validates written radiology ANALYSIS only (never scan images):
    - Date within admission-discharge range (hard block if not)
    - Patient name match
    - Finding consistent with claimed procedure, judged as PA view
    """
    name = "RadiologyValidatorAgent"

    async def run(self, claim: dict, context: dict) -> AgentResult:
        flags         = []
        documents     = claim.get("documents", [])

        rad_groups = claim.get("radiology_relevant_groups", [])
        radiology_docs = _docs_by_relevant_groups(documents, rad_groups) if rad_groups else _radiology_docs(documents)

        if not radiology_docs:
            return AgentResult(
                agent_name=self.name,
                score=100,
                passed=True,
                flags=[],
                details={"note": "No radiology documents submitted"},
            )

        valid_radiology_docs = [
            d for d in radiology_docs
            if (d.get("text_content") and d["text_content"].strip())
               or d.get("content_base64")
               or d.get("filename")
        ]

        if not valid_radiology_docs:
            return AgentResult(
                agent_name=self.name,
                score=80,
                passed=True,
                flags=[Flag(
                    field="radiology_report",
                    severity=FlagSeverity.MEDIUM,
                    reason="Radiology documents were submitted but all have empty/null content",
                )],
                details={"note": "All radiology document entries are empty"},
            )

        filenames = ", ".join(
            str(d.get("filename") or d.get("field_key") or "unknown")
            for d in valid_radiology_docs
        )

        def _rad_text_preview(d: dict) -> str:
            text = (d.get("text_content") or "").strip()
            if text:
                return text[:400]
            if d.get("content_base64"):
                return "(scan/image only — IGNORE the image; no written ANALYSIS)"
            return "(no written ANALYSIS)"

        radiology_summary = "\n".join(
            f"[{d.get('filename', d['field_key'])}]: {_rad_text_preview(d)}"
            for d in valid_radiology_docs
        )

        format_kwargs = dict(
            package_name=claim["package_name"],
            package_code=claim["package_code"],
            patient_name=claim["patient_name"],
            admission_date=claim["admission_date"],
            discharge_date=claim.get("discharge_date") or "",
            filenames=filenames,
            radiology_summary=radiology_summary,
        )
        ai_prompt = _render_agent_prompt(
            self.name, claim, RADIOLOGY_VALIDATOR_PROMPT, format_kwargs, flags=flags,
        )

        # Never send scan images — decisions must come from written ANALYSIS only.
        raw = await self._call_ai(ai_prompt)
        result, parse_err = _parse_ai_json(raw)
        has_decode_error = parse_err is not None
        if has_decode_error:
            logger.warning(
                "[%s] unparseable JSON (%s). Raw preview: %s",
                self.name,
                parse_err,
                repr(raw)[:500],
            )
            result = {
                "radiology_score": 70,
                "hard_block": False,
                "flags": [],
                "parse_error": parse_err,
            }

        if not result.get("date_valid", True):
            flags.append(Flag(
                field="radiology_date",
                severity=FlagSeverity.HIGH,
                reason="Radiology report date is outside admission-discharge range - HARD BLOCK",
            ))

        # FIX-6: normalize flags (radiology refined prompt returns dict flags)
        flags.extend(_normalize_flags(result.get("flags", []), "radiology_report"))

        score = result.get("radiology_score")
        if score is None:
            # FIX-8: fallback 70 — message says 70
            score = 70
            flags.append(Flag(
                field="system_fallback",
                severity=FlagSeverity.MEDIUM,
                reason="System fallback score of 70 was used because AI radiology validation returned a null/empty score."
            ))
        elif has_decode_error:
            # FIX-8: fallback 70 (set above) — message says 70
            flags.append(Flag(
                field="system_fallback",
                severity=FlagSeverity.MEDIUM,
                reason=(
                    "System fallback score of 70 was used because AI radiology validation "
                    f"returned unparseable JSON ({parse_err}). Raw: {repr(raw)[:180]}"
                )
            ))

        return AgentResult(
            agent_name=self.name,
            score=score,
            passed=not result.get("hard_block", False),
            flags=flags,
            details=result,
        )


# ─────────────────────────────────────────
# 8. Billing Analyser Agent  (CLAIM-ONLY)
# ─────────────────────────────────────────

def _billing_docs(documents: list[dict], billing_groups: list[str]) -> list[dict]:
    """Filter documents whose field_group is marked billing_relevant in the DB."""
    return [d for d in documents if d.get("field_group") in billing_groups]


class BillingAnalyserAgent(BaseAgent):
    """
    Cross-verifies submitted bills against the package rate.
    Runs ONLY on claims (not preauth).
    """
    name = "BillingAnalyserAgent"

    async def run(self, claim: dict, context: dict) -> AgentResult:
        flags = []
        documents        = claim.get("documents", [])
        billing_groups   = claim.get("billing_relevant_groups", [])
        package_rate_inr = claim.get("package_rate_inr")

        billing_docs = _billing_docs(documents, billing_groups) if billing_groups else []

        if not billing_docs:
            return AgentResult(
                agent_name=self.name,
                score=100,
                passed=True,
                flags=[Flag(
                    field="billing",
                    severity=FlagSeverity.LOW,
                    reason="No billing-relevant document groups configured or submitted for this package.",
                )],
                details={"note": "No billing-relevant documents found"},
            )

        valid_billing_docs = [
            d for d in billing_docs
            if (d.get("text_content") and d["text_content"].strip())
               or d.get("content_base64")
               or d.get("filename")
        ]

        if not valid_billing_docs:
            return AgentResult(
                agent_name=self.name,
                score=80,
                passed=True,
                flags=[Flag(
                    field="billing",
                    severity=FlagSeverity.MEDIUM,
                    reason="Billing documents were submitted but all have empty/null content",
                )],
                details={"note": "All billing document entries are empty"},
            )

        filenames = [d.get("filename", d["field_key"]) for d in valid_billing_docs]

        billing_summary = "\n".join(
            f"[{d.get('filename', d['field_key'])}] (group: {d.get('field_group', 'unknown')}): "
            f"{(d.get('text_content') or '(binary file)')[:500]}"
            for d in valid_billing_docs
        )

        images_b64 = [d["content_base64"] for d in valid_billing_docs if d.get("content_base64")]

        # FIX-5: Use a plain variable for the rate display value instead of
        # inlining a Python expression directly into a JSON-like f-string template.
        # This prevents None → 'null' string confusion and is easier to read.
        rate_display = f"₹{package_rate_inr:,.2f}" if package_rate_inr is not None else "Not configured"
        rate_context = (
            f"\nPACKAGE RATE LIMIT: ₹{package_rate_inr:,.2f} (INR)"
            if package_rate_inr is not None
            else "\nPACKAGE RATE LIMIT: Not set (no cap configured)"
        )
        rate_for_json = package_rate_inr if package_rate_inr is not None else "null"

        format_kwargs = dict(
            package_name=claim["package_name"],
            package_code=claim["package_code"],
            patient_name=claim["patient_name"],
            admission_date=claim["admission_date"],
            discharge_date=claim["discharge_date"],
            package_rate_inr=package_rate_inr or "N/A",
            rate_context=rate_context,
            rate_display=rate_display,
            rate_for_json=rate_for_json,
            filenames=filenames,
            billing_summary=billing_summary,
        )
        ai_prompt = _render_agent_prompt(
            self.name, claim, BILLING_ANALYSER_PROMPT, format_kwargs, flags=flags,
        )

        raw = await self._call_ai(ai_prompt, images=images_b64)

        logger.info(f"[{self.name}] Model response: {raw}")
        print(f"\n--- [{self.name}] Model response ---")
        print(raw)
        print("--------------------------------------------------\n")

        try:
            result = json.loads(raw)
            has_decode_error = False
        except json.JSONDecodeError:
            result = {"billing_score": 70, "flags": [], "amount_exceeded": False}
            has_decode_error = True

        amount_exceeded = result.get("amount_exceeded", False)
        total_billed    = result.get("total_billed_amount")
        excess_amount   = result.get("excess_amount", 0)

        if amount_exceeded and package_rate_inr is not None:
            flags.append(Flag(
                field="billing_amount",
                severity=FlagSeverity.HIGH,
                reason=(
                    f"BILLING EXCEEDED: Total billed amount (₹{total_billed:,.2f}) "
                    f"exceeds the package rate limit (₹{package_rate_inr:,.2f}) "
                    f"by ₹{excess_amount:,.2f}."
                ) if isinstance(total_billed, (int, float)) else (
                    f"BILLING EXCEEDED: Total billed amount exceeds the package rate limit (₹{package_rate_inr:,.2f})."
                ),
            ))
        elif package_rate_inr is None and total_billed is not None:
            flags.append(Flag(
                field="billing_amount",
                severity=FlagSeverity.MEDIUM,
                reason=f"Package rate (INR) is not configured. Cannot verify if billed amount "
                       f"(₹{total_billed}) is within limits.",
            ))

        for dup in result.get("duplicate_entries", []):
            flags.append(Flag(
                field="billing_duplicates",
                severity=FlagSeverity.HIGH,
                reason=f"Suspected duplicate billing entry: {dup}",
            ))

        for item in result.get("suspicious_items", []):
            flags.append(Flag(
                field="billing_suspicious",
                severity=FlagSeverity.MEDIUM,
                reason=f"Suspicious billing item: {item}",
            ))

        if result.get("unbundling_detected", False):
            flags.append(Flag(
                field="billing_unbundling",
                severity=FlagSeverity.HIGH,
                reason="Possible unbundling detected: procedure may have been split into "
                       "multiple billing codes to inflate costs.",
            ))

        # FIX-6: normalize general AI flags
        flags.extend(_normalize_flags(result.get("flags", []), "billing"))

        score = result.get("billing_score")
        if score is None:
            # FIX-8: fallback 70 — message says 70
            score = 70
            flags.append(Flag(
                field="system_fallback",
                severity=FlagSeverity.MEDIUM,
                reason="System fallback score of 70 was used because AI billing analysis returned a null/empty score."
            ))
        elif has_decode_error:
            # FIX-8: fallback 70 (set above) — message says 70
            flags.append(Flag(
                field="system_fallback",
                severity=FlagSeverity.MEDIUM,
                reason="System fallback score of 70 was used because AI billing analysis returned unparseable JSON."
            ))

        hard_block = amount_exceeded and package_rate_inr is not None
        passed     = not hard_block and len(result.get("duplicate_entries", [])) == 0

        return AgentResult(
            agent_name=self.name,
            score=score,
            passed=passed,
            flags=flags,
            details={**result, "hard_block": hard_block},
        )


# ─────────────────────────────────────────
# 9. Discharge Summary Analyser Agent  (CLAIM-ONLY)
# ─────────────────────────────────────────

def _discharge_docs(documents: list[dict], discharge_groups: list[str]) -> list[dict]:
    """Filter documents whose field_group is marked discharge_relevant in the DB."""
    return [d for d in documents if d.get("field_group") in discharge_groups]


class DischargeSummaryAnalyserAgent(BaseAgent):
    """
    Analyzes the discharge summary for a claim.
    Runs ONLY on claims (not preauth).
    """
    name = "DischargeSummaryAnalyserAgent"

    async def run(self, claim: dict, context: dict) -> AgentResult:
        flags = []
        documents        = claim.get("documents", [])
        discharge_groups = claim.get("discharge_relevant_groups", [])

        discharge_docs = _discharge_docs(documents, discharge_groups) if discharge_groups else []

        if not discharge_docs:
            return AgentResult(
                agent_name=self.name,
                score=100,
                passed=True,
                flags=[Flag(
                    field="discharge",
                    severity=FlagSeverity.LOW,
                    reason="No discharge-relevant document groups configured or submitted for this package.",
                )],
                details={"note": "No discharge-relevant documents found"},
            )

        valid_discharge_docs = [
            d for d in discharge_docs
            if (d.get("text_content") and d["text_content"].strip())
               or d.get("content_base64")
               or d.get("filename")
        ]

        if not valid_discharge_docs:
            return AgentResult(
                agent_name=self.name,
                score=80,
                passed=True,
                flags=[Flag(
                    field="discharge",
                    severity=FlagSeverity.MEDIUM,
                    reason="Discharge documents were submitted but all have empty/null content",
                )],
                details={"note": "All discharge document entries are empty"},
            )

        filenames = [d.get("filename", d["field_key"]) for d in valid_discharge_docs]

        # Cap total summary to avoid hitting context window limits
        MAX_SUMMARY_CHARS = 8000
        discharge_summary = "\n".join(
            f"[{d.get('filename', d['field_key'])}] (group: {d.get('field_group', 'unknown')}): "
            f"{(d.get('text_content') or '(binary file)')[:1500]}"
            for d in valid_discharge_docs
        )[:MAX_SUMMARY_CHARS]

        images_b64 = [d["content_base64"] for d in valid_discharge_docs if d.get("content_base64")]

        format_kwargs = dict(
            package_name=claim["package_name"],
            package_code=claim["package_code"],
            patient_name=claim["patient_name"],
            admission_date=claim["admission_date"],
            discharge_date=claim["discharge_date"],
            filenames=filenames,
            discharge_summary=discharge_summary,
        )
        ai_prompt = _render_agent_prompt(
            self.name, claim, DISCHARGE_SUMMARY_PROMPT, format_kwargs, flags=flags,
        )

        raw = await self._call_ai(ai_prompt, images=images_b64)

        logger.info(f"[{self.name}] Model response: {raw}")
        print(f"\n--- [{self.name}] Model response ---")
        print(raw)
        print("--------------------------------------------------\n")

        try:
            result = json.loads(raw)
            has_decode_error = False
        except json.JSONDecodeError:
            result = {
                "discharge_score": 70,
                "flags": [],
                "diagnosis_match": False,
                "procedure_match": False,
            }
            has_decode_error = True

        if not result.get("diagnosis_match", True):
            flags.append(Flag(
                field="discharge_diagnosis",
                severity=FlagSeverity.HIGH,
                reason="Primary diagnosis in discharge summary does not align with claimed package.",
            ))

        if not result.get("procedure_match", True):
            flags.append(Flag(
                field="discharge_procedure",
                severity=FlagSeverity.HIGH,
                reason="Performed procedure in discharge summary does not align with claimed package.",
            ))

        for disc in result.get("discrepancies", []):
            flags.append(Flag(
                field="discharge_discrepancy",
                severity=FlagSeverity.MEDIUM,
                reason=f"Discrepancy found: {disc}",
            ))

        # FIX-6: normalize flags (discharge refined prompt returns dict flags)
        flags.extend(_normalize_flags(result.get("flags", []), "discharge"))

        score = result.get("discharge_score")
        if score is None:
            # FIX-8: fallback 70 — message says 70
            score = 70
            flags.append(Flag(
                field="system_fallback",
                severity=FlagSeverity.MEDIUM,
                reason="System fallback score of 70 was used because AI discharge analysis returned a null/empty score."
            ))
        elif has_decode_error:
            # FIX-8: fallback 70 (set above) — message says 70
            flags.append(Flag(
                field="system_fallback",
                severity=FlagSeverity.MEDIUM,
                reason="System fallback score of 70 was used because AI discharge analysis returned unparseable JSON."
            ))

        return AgentResult(
            agent_name=self.name,
            score=score,
            passed=score >= 60,
            flags=flags,
            details=result,
        )


# ─────────────────────────────────────────
# 10. ICP Agent (Indoor Case Papers)  (CLAIM-ONLY)
# ─────────────────────────────────────────

class ICPAgent(BaseAgent):
    """
    Analyzes Indoor Case Papers (ICPs): continuation sheets, day care plans, nursing charts.
    Runs only during claim stage.
    """
    name = "ICPAgent"

    async def run(self, claim: dict, context: dict) -> AgentResult:
        flags = []
        documents  = claim.get("documents", [])

        icp_groups = claim.get("icp_relevant_groups", [])
        icp_docs   = _docs_by_relevant_groups(documents, icp_groups) if icp_groups else []

        if not icp_docs:
            return AgentResult(
                agent_name=self.name,
                score=100,
                passed=True,
                flags=[],
                details={"note": "No ICP documents marked for this package."},
            )

        extracted = context.get("DocumentExtractorAgent", {}).get("extracted_documents", {})

        icp_summary = []
        for d in icp_docs:
            fk = d.get("field_key")
            e  = extracted.get(fk, {}).get("extracted", {})
            if isinstance(e, dict):
                icp_summary.append(f"--- Document: {fk} ---\n{json.dumps(e, indent=2)}")

        if not icp_summary:
            return AgentResult(
                agent_name=self.name,
                score=100,
                passed=True,
                flags=[],
                details={"note": "ICP documents found but no text extracted."},
            )

        format_kwargs = dict(
            package_name=claim.get("package_name"),
            admission_date=claim.get("admission_date"),
            discharge_date=claim.get("discharge_date"),
            icp_summary=chr(10).join(icp_summary),
        )
        ai_prompt = _render_agent_prompt(
            self.name, claim, ICP_PROMPT, format_kwargs, flags=flags,
        )

        raw = await self._call_ai(ai_prompt)
        decode_error_msg = ""
        raw_preview = ""
        try:
            result = json.loads(raw)
            has_decode_error = False
        except json.JSONDecodeError as e:
            result = {"icp_score": 50, "care_consistent": False, "flags": ["AI parsing failed"]}
            has_decode_error = True
            decode_error_msg = str(e)
            raw_preview = repr(raw)[:200]

        # FIX-6: normalize flags — ICP refined prompt returns dict flags with
        # {issue, severity, error_code}. Without normalization these were being
        # stringified as dict reprs in the reason field.
        flags.extend(_normalize_flags(result.get("flags", []), "icp_check"))

        score = result.get("icp_score")
        if score is None:
            # FIX-8: fallback 100 — message says 100
            score = 100
            flags.append(Flag(
                field="system_fallback",
                severity=FlagSeverity.MEDIUM,
                reason=(
                    f"System fallback score of 100 was used because AI ICP validation returned "
                    f"unparseable JSON. Error: {decode_error_msg}. Raw: {raw_preview}"
                ) if has_decode_error else (
                    "System fallback score of 100 was used because AI returned invalid structure without score field."
                )
            ))
        elif not isinstance(score, (int, float)):
            # FIX-8: fallback 50 — message says 50
            score = 50
            flags.append(Flag(
                field="system_fallback",
                severity=FlagSeverity.MEDIUM,
                reason="System fallback score of 50 was used because AI returned non-numeric score for ICP."
            ))

        return AgentResult(
            agent_name=self.name,
            score=max(0, min(100, score)),
            passed=True,
            flags=flags,
            details={
                "care_consistent": result.get("care_consistent", True),
                "hard_block":      result.get("hard_block", False),
                "ai_issues":       result.get("flags", []),
            },
        )