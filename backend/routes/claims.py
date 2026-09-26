"""
Claims Routes

POST /api/v1/claims/                   — Submit claim documents (saves to DB)
GET  /api/v1/claims/{id}/preflight     — Pre-flight existence check
POST /api/v1/claims/{id}/score         — Run claim engine on saved claim
GET  /api/v1/claims/{id}/report        — Get saved score report
GET  /api/v1/claims/patient/{pid}      — All claims for a patient
"""

import time
import json
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from core.database import get_db
from core.config import settings
from core.ai_clients import get_ai_client
from models.schemas import (
    ClaimSubmitRequest, ClaimScoreReport, PreflightResult, PreflightField,
    PreauthSubmitRequest, PreauthScoreReport,
)

from agents.orchestrator import ClaimOrchestratorAgent

router = APIRouter()


# ─────────────────────────────────────────
# List all claims — searchable (MUST register before /{claim_id} routes)
# ─────────────────────────────────────────

@router.get("/")
async def list_claims(
    search: Optional[str] = Query(None, description="Search by claim_ref, patient name, PMJAY number, or package code"),
    status: Optional[str] = Query(None, description="Filter by claim status (e.g. PENDING, SCORED)"),
    package_code: Optional[str] = Query(None, description="Filter by package code"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Paginated list of all claims with optional search/filter.
    """
    base = """
        SELECT c.id, c.claim_ref, c.status, c.admission_date, c.discharge_date,
               c.created_at,
               pat.name AS patient_name, pat.pmjay_number,
               p.code AS package_code, p.name AS package_name,
               csr.verdict, csr.total_score
        FROM claims c
        JOIN patients pat ON pat.id = c.patient_id
        JOIN packages p ON p.id = c.package_id
        LEFT JOIN claim_score_reports csr ON csr.claim_id = c.id
    """
    conditions = []
    params: dict = {"limit": limit, "offset": offset}

    if search:
        conditions.append(
            "(c.claim_ref ILIKE :q OR pat.name ILIKE :q OR pat.pmjay_number ILIKE :q OR p.code ILIKE :q)"
        )
        params["q"] = f"%{search}%"
    if status:
        conditions.append("c.status = :status")
        params["status"] = status.upper()
    if package_code:
        conditions.append("p.code = :pkg_code")
        params["pkg_code"] = package_code

    if conditions:
        base += " WHERE " + " AND ".join(conditions)

    base += " ORDER BY c.created_at DESC LIMIT :limit OFFSET :offset"

    result = await db.execute(text(base), params)
    rows = [dict(r._mapping) for r in result.fetchall()]

    # Total count
    count_sql = "SELECT COUNT(*) FROM claims c JOIN patients pat ON pat.id = c.patient_id JOIN packages p ON p.id = c.package_id"
    if conditions:
        count_sql += " WHERE " + " AND ".join(conditions)
    count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
    count_result = await db.execute(text(count_sql), count_params)
    total = count_result.scalar()

    return {"total": total, "limit": limit, "offset": offset, "results": rows}


# ─────────────────────────────────────────
# List all preauths — searchable (MUST register before /{claim_id} routes)
# ─────────────────────────────────────────

@router.get("/preauth")
async def list_preauths(
    search: Optional[str] = Query(None, description="Search by preauth_ref, patient name, PMJAY number, or package code"),
    status: Optional[str] = Query(None, description="Filter by preauth status (e.g. PENDING, SCORED)"),
    package_code: Optional[str] = Query(None, description="Filter by package code"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Paginated list of all pre-authorizations with optional search/filter.
    """
    base = """
        SELECT pa.id, pa.preauth_ref, pa.status, pa.admission_date,
               pa.created_at,
               pat.name AS patient_name, pat.pmjay_number,
               p.code AS package_code, p.name AS package_name,
               psr.verdict, psr.total_score
        FROM preauths pa
        JOIN patients pat ON pat.id = pa.patient_id
        JOIN packages p ON p.id = pa.package_id
        LEFT JOIN preauth_score_reports psr ON psr.preauth_id = pa.id
    """
    conditions = []
    params: dict = {"limit": limit, "offset": offset}

    if search:
        conditions.append(
            "(pa.preauth_ref ILIKE :q OR pat.name ILIKE :q OR pat.pmjay_number ILIKE :q OR p.code ILIKE :q)"
        )
        params["q"] = f"%{search}%"
    if status:
        conditions.append("pa.status = :status")
        params["status"] = status.upper()
    if package_code:
        conditions.append("p.code = :pkg_code")
        params["pkg_code"] = package_code

    if conditions:
        base += " WHERE " + " AND ".join(conditions)

    base += " ORDER BY pa.created_at DESC LIMIT :limit OFFSET :offset"

    result = await db.execute(text(base), params)
    rows = [dict(r._mapping) for r in result.fetchall()]

    # Total count
    count_sql = "SELECT COUNT(*) FROM preauths pa JOIN patients pat ON pat.id = pa.patient_id JOIN packages p ON p.id = pa.package_id"
    if conditions:
        count_sql += " WHERE " + " AND ".join(conditions)
    count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
    count_result = await db.execute(text(count_sql), count_params)
    total = count_result.scalar()

    return {"total": total, "limit": limit, "offset": offset, "results": rows}


# ─────────────────────────────────────────
# Patient-scoped lists (static path segments — safe before /{claim_id})
# ─────────────────────────────────────────

@router.get("/patient/{patient_id}")
async def get_patient_claims(patient_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("""
            SELECT c.id, c.claim_ref, c.status, c.admission_date, c.discharge_date,
                   p.code AS package_code, p.name AS package_name,
                   csr.verdict, csr.total_score
            FROM claims c
            JOIN packages p ON p.id = c.package_id
            LEFT JOIN claim_score_reports csr ON csr.claim_id = c.id
            WHERE c.patient_id = :pid
            ORDER BY c.created_at DESC
        """),
        {"pid": patient_id},
    )
    return [dict(r._mapping) for r in result.fetchall()]


@router.get("/patient/{patient_id}/preauths")
async def get_patient_preauths(patient_id: int, db: AsyncSession = Depends(get_db)):
    """
    List all pre-authorizations for a given patient.
    """
    result = await db.execute(
        text("""
            SELECT pa.id, pa.preauth_ref, pa.status, pa.admission_date,
                   p.code AS package_code, p.name AS package_name,
                   psr.verdict, psr.total_score
            FROM preauths pa
            JOIN packages p ON p.id = pa.package_id
            LEFT JOIN preauth_score_reports psr ON psr.preauth_id = pa.id
            WHERE pa.patient_id = :pid
            ORDER BY pa.created_at DESC
        """),
        {"pid": patient_id},
    )
    return [dict(r._mapping) for r in result.fetchall()]


# ─────────────────────────────────────────
# 1. Submit claim documents
# ─────────────────────────────────────────

@router.post("/", status_code=201)
async def submit_claim(
    body: ClaimSubmitRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Step 1: Frontend submits patient_id + package_code + all documents.
    Saves everything to DB. Returns claim_id for next steps.
    """
    # Validate patient
    pat = await db.execute(
        text("SELECT id, name, pmjay_number FROM patients WHERE id = :pid"),
        {"pid": body.patient_id},
    )
    patient = pat.fetchone()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Validate package
    pkg = await db.execute(
        text("SELECT id, code, name FROM packages WHERE code = :code AND is_active = true"),
        {"code": body.package_code},
    )
    package = pkg.fetchone()
    if not package:
        raise HTTPException(status_code=404, detail=f"Package {body.package_code} not found")

    # Generate claim ref
    claim_ref = f"CLM-{time.strftime('%Y')}-{str(uuid.uuid4())[:8].upper()}"

    # Insert claim
    claim_result = await db.execute(
        text("""
            INSERT INTO claims
                (claim_ref, patient_id, package_id, hospital_id, admission_date, discharge_date)
            VALUES
                (:ref, :pid, :pkg_id, :hosp, :admit, :discharge)
            RETURNING id
        """),
        {
            "ref":      claim_ref,
            "pid":      body.patient_id,
            "pkg_id":   package.id,
            "hosp":     body.hospital_id,
            "admit":    body.admission_date,
            "discharge": body.discharge_date,
        },
    )
    claim_id = claim_result.fetchone().id

    # Mapping preauth if present
    if body.preauth_id:
        # Verify preauth exists
        pa_check = await db.execute(
            text("SELECT id FROM preauths WHERE id = :pid"),
            {"pid": body.preauth_id}
        )
        if not pa_check.fetchone():
            raise HTTPException(status_code=404, detail=f"Pre-authorization ID {body.preauth_id} not found")
        
        await db.execute(
            text("INSERT INTO claim_preauth_mappings (claim_id, preauth_id) VALUES (:cid, :pid)"),
            {"cid": claim_id, "pid": body.preauth_id}
        )

    # Insert documents
    for doc in body.documents:
        if doc.data_type_is_string():
            # Single text field
            await db.execute(
                text("""
                    INSERT INTO claim_documents
                        (claim_id, field_key, field_group, text_content)
                    VALUES (:cid, :fkey, :fgrp, :txt)
                """),
                {
                    "cid":  claim_id,
                    "fkey": doc.field_key,
                    "fgrp": doc.field_group,
                    "txt":  doc.text_value,
                },
            )
        else:
            # Array of files — one row per file
            for i, f in enumerate(doc.files):
                await db.execute(
                    text("""
                        INSERT INTO claim_documents
                            (claim_id, field_key, field_group, filename, content_base64, sort_order)
                        VALUES (:cid, :fkey, :fgrp, :fname, :b64, :ord)
                    """),
                    {
                        "cid":   claim_id,
                        "fkey":  doc.field_key,
                        "fgrp":  doc.field_group,
                        "fname": f.filename,
                        "b64":   f.content_base64,
                        "ord":   i,
                    },
                )

    return {
        "claim_id":  claim_id,
        "claim_ref": claim_ref,
        "preauth_id": body.preauth_id,
        "status":    "PENDING",
        "message":   "Claim documents saved. Call /preflight to check, then /score to run engine.",
    }


# ─────────────────────────────────────────
# 2. Pre-flight existence check
# ─────────────────────────────────────────

@router.get("/{claim_id}/preflight", response_model=PreflightResult)
async def preflight_check(claim_id: int, db: AsyncSession = Depends(get_db)):
    """
    Step 2: Cross-check submitted documents against package required fields.
    Must be called before /score.
    Returns ready=True only when all mandatory fields are present and non-empty.
    """
    claim = await _get_claim_or_404(claim_id, db)

    # Required fields from package
    required = await db.execute(
        text("""
            SELECT tf.field_name AS field_key, pd.label, pd.mandatory
            FROM package_documents pd
            JOIN text_fields tf ON tf.id = pd.field_key_id
            WHERE pd.package_id = :pkg_id
            ORDER BY pd.sort_order
        """),
        {"pkg_id": claim["package_id"]},
    )
    required_fields = required.fetchall()

    # Find mapped preauth_id
    pa_mapping_res = await db.execute(
        text("SELECT preauth_id FROM claim_preauth_mappings WHERE claim_id = :cid"),
        {"cid": claim_id}
    )
    pa_row = pa_mapping_res.fetchone()
    pa_id = pa_row.preauth_id if pa_row else None

    # Query submitted fields from claim_documents
    query_sub = """
        SELECT DISTINCT field_key,
               CASE
                 WHEN text_content IS NOT NULL AND text_content != '' THEN true
                 WHEN filename IS NOT NULL THEN true
                 ELSE false
               END as has_content
        FROM claim_documents
        WHERE claim_id = :cid
    """
    params_sub = {"cid": claim_id}
    
    if pa_id:
        query_sub = f"""
            ({query_sub})
            UNION
            (SELECT DISTINCT field_key,
                   CASE
                     WHEN text_content IS NOT NULL AND text_content != '' THEN true
                     WHEN filename IS NOT NULL THEN true
                     ELSE false
                   END as has_content
            FROM preauth_documents
            WHERE preauth_id = :pid)
        """
        params_sub["pid"] = pa_id

    submitted = await db.execute(text(query_sub), params_sub)
    submitted_map = {r.field_key: r.has_content for r in submitted.fetchall()}


    field_results = []
    missing_mandatory = []
    missing_optional = []

    for req in required_fields:
        provided = req.field_key in submitted_map
        has_content = submitted_map.get(req.field_key, False)

        if not provided:
            status = "missing"
        elif not has_content:
            status = "empty"
        else:
            status = "ok"

        field_results.append(PreflightField(
            field_key=req.field_key,
            label=req.label,
            mandatory=req.mandatory,
            provided=provided,
            status=status,
        ))

        if status != "ok":
            if req.mandatory:
                missing_mandatory.append(req.label)
            else:
                missing_optional.append(req.label)

    return PreflightResult(
        ready=len(missing_mandatory) == 0,
        missing_mandatory=missing_mandatory,
        missing_optional=missing_optional,
        fields=field_results,
    )


# ─────────────────────────────────────────
# 3. Run claim engine
# ─────────────────────────────────────────

@router.post("/{claim_id}/score", response_model=ClaimScoreReport)
async def score_claim(claim_id: int, db: AsyncSession = Depends(get_db)):
    """
    Step 3: Run all agents and produce a score report.
    Preflight is run internally first — if mandatory docs missing, returns 422.
    """
    # Internal preflight guard
    preflight = await preflight_check(claim_id, db)
    if not preflight.ready:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Cannot score: mandatory documents missing",
                "missing": preflight.missing_mandatory,
            },
        )

    claim = await _get_claim_or_404(claim_id, db)

    # Check if there is a mapped preauth
    pa_mapping_res = await db.execute(
        text("SELECT preauth_id FROM claim_preauth_mappings WHERE claim_id = :cid"),
        {"cid": claim_id}
    )
    pa_row = pa_mapping_res.fetchone()
    pa_id = pa_row.preauth_id if pa_row else None

    # Load all claim documents
    docs_result = await db.execute(
        text("SELECT * FROM claim_documents WHERE claim_id = :cid ORDER BY field_key, sort_order"),
        {"cid": claim_id},
    )
    claim_documents = [dict(d._mapping) for d in docs_result.fetchall()]

    if pa_id:
        # Load all preauth documents
        pa_docs_result = await db.execute(
            text("SELECT * FROM preauth_documents WHERE preauth_id = :pid ORDER BY field_key, sort_order"),
            {"pid": pa_id},
        )
        preauth_documents = [dict(d._mapping) for d in pa_docs_result.fetchall()]
        # Combine them!
        claim_documents.extend(preauth_documents)

    # Load weights from DB (dynamic per package)
    weights_result = await db.execute(
        text("SELECT agent_name, weight FROM scoring_weights WHERE package_id = :pid"),
        {"pid": claim["package_id"]},
    )
    weights = {r.agent_name: float(r.weight) for r in weights_result.fetchall()}

    claim_context = {
        "claim_id":       claim_id,
        "claim_ref":      claim["claim_ref"],
        "patient_id":     claim["patient_id"],
        "patient_name":   claim["patient_name"],
        "pmjay_number":   claim["pmjay_number"],
        "patient_dob":    str(claim["dob"]),
        "patient_gender": claim["gender"],
        "package_code":   claim["package_code"],
        "package_name":   claim["package_name"],
        "hospital_id":    claim["hospital_id"],
        "admission_date": str(claim["admission_date"]),
        "discharge_date": str(claim["discharge_date"]),
        "documents":      claim_documents,
        "required_fields": [],   # injected below from package_documents
        "agent_prompts":   {},   # injected below from agent_prompts
    }

    # Load required fields from DB → injected into claim_context for PackageComplianceAgent
    req_result = await db.execute(
        text("""
            SELECT tf.field_name AS field_key, pd.label, pd.mandatory
            FROM package_documents pd
            JOIN text_fields tf ON tf.id = pd.field_key_id
            WHERE pd.package_id = :pid
            ORDER BY pd.sort_order
        """),
        {"pid": claim["package_id"]},
    )
    claim_context["required_fields"] = [
        {"field_key": r.field_key, "label": r.label, "mandatory": r.mandatory}
        for r in req_result.fetchall()
    ]

    # Load clinical_relevant groups → drives which doc groups ClinicalRelevanceAgent analyzes
    cr_result = await db.execute(
        text("""
            SELECT DISTINCT tfg.group_name
            FROM package_documents pd
            JOIN text_field_groups tfg ON tfg.id = pd.field_group_id
            WHERE pd.package_id = :pid AND pd.clinical_relevant = true
        """),
        {"pid": claim["package_id"]},
    )
    claim_context["clinical_relevant_groups"] = [r.group_name for r in cr_result.fetchall()]

    # Load billing_relevant groups → drives which doc groups BillingAnalyserAgent analyzes
    br_result = await db.execute(
        text("""
            SELECT DISTINCT tfg.group_name
            FROM package_documents pd
            JOIN text_field_groups tfg ON tfg.id = pd.field_group_id
            WHERE pd.package_id = :pid AND pd.billing_relevant = true
        """),
        {"pid": claim["package_id"]},
    )
    claim_context["billing_relevant_groups"] = [r.group_name for r in br_result.fetchall()]

    # Load package_rate_inr for billing verification
    rate_result = await db.execute(
        text("SELECT package_rate_inr FROM packages WHERE id = :pid"),
        {"pid": claim["package_id"]},
    )
    rate_row = rate_result.fetchone()
    claim_context["package_rate_inr"] = float(rate_row.package_rate_inr) if rate_row and rate_row.package_rate_inr else None

    # Load dynamic agent prompts
    prompts_result = await db.execute(text("SELECT agent_name, system_prompt FROM agent_prompts"))
    claim_context["agent_prompts"] = {r.agent_name: r.system_prompt for r in prompts_result.fetchall()}


    # Load discharge_relevant groups → drives which doc groups DischargeSummaryAnalyserAgent analyzes
    dr_result = await db.execute(
        text("""
            SELECT DISTINCT tfg.group_name
            FROM package_documents pd
            JOIN text_field_groups tfg ON tfg.id = pd.field_group_id
            WHERE pd.package_id = :pid AND pd.discharge_relevant = true
        """),
        {"pid": claim["package_id"]},
    )
    claim_context["discharge_relevant_groups"] = [r.group_name for r in dr_result.fetchall()]

    # Load identity_relevant groups → drives which doc groups IdentityValidatorAgent analyzes
    ir_result = await db.execute(
        text("""
            SELECT DISTINCT tfg.group_name
            FROM package_documents pd
            JOIN text_field_groups tfg ON tfg.id = pd.field_group_id
            WHERE pd.package_id = :pid AND pd.identity_relevant = true
        """),
        {"pid": claim["package_id"]},
    )
    claim_context["identity_relevant_groups"] = [r.group_name for r in ir_result.fetchall()]

    # Load lab_relevant groups → drives which doc groups LabAnalyzerAgent analyzes
    lr_result = await db.execute(
        text("""
            SELECT DISTINCT tfg.group_name
            FROM package_documents pd
            JOIN text_field_groups tfg ON tfg.id = pd.field_group_id
            WHERE pd.package_id = :pid AND pd.lab_relevant = true
        """),
        {"pid": claim["package_id"]},
    )
    claim_context["lab_relevant_groups"] = [r.group_name for r in lr_result.fetchall()]

    # Load image_relevant groups → drives which doc groups ImageValidatorAgent analyzes
    imgr_result = await db.execute(
        text("""
            SELECT DISTINCT tfg.group_name
            FROM package_documents pd
            JOIN text_field_groups tfg ON tfg.id = pd.field_group_id
            WHERE pd.package_id = :pid AND pd.image_relevant = true
        """),
        {"pid": claim["package_id"]},
    )
    claim_context["image_relevant_groups"] = [r.group_name for r in imgr_result.fetchall()]

    # Load radiology_relevant groups → drives which doc groups RadiologyValidatorAgent analyzes
    radr_result = await db.execute(
        text("""
            SELECT DISTINCT tfg.group_name
            FROM package_documents pd
            JOIN text_field_groups tfg ON tfg.id = pd.field_group_id
            WHERE pd.package_id = :pid AND pd.radiology_relevant = true
        """),
        {"pid": claim["package_id"]},
    )
    claim_context["radiology_relevant_groups"] = [r.group_name for r in radr_result.fetchall()]

    # Load icp_relevant groups → drives which doc groups ICPAgent analyzes
    icpr_result = await db.execute(
        text("""
            SELECT DISTINCT tfg.group_name
            FROM package_documents pd
            JOIN text_field_groups tfg ON tfg.id = pd.field_group_id
            WHERE pd.package_id = :pid AND pd.icp_relevant = true
        """),
        {"pid": claim["package_id"]},
    )
    claim_context["icp_relevant_groups"] = [r.group_name for r in icpr_result.fetchall()]


    # Run agents (include_billing=True, include_discharge=True for claims)
    ai_client = get_ai_client(settings.AI_PROVIDER, settings.AI_API_KEY)
    orchestrator = ClaimOrchestratorAgent(
        ai_client=ai_client, 
        weights=weights, 
        include_billing=True, 
        include_discharge=True
    )
    report = await orchestrator.process_claim(claim_context)

    # Persist report
    await db.execute(
        text("""
            INSERT INTO claim_score_reports
                (claim_id, verdict, total_score, hard_block, hard_block_reason,
                 module_scores, all_flags, missing_documents, identity_mismatches,
                 recommendations, processing_time_ms)
            VALUES
                (:cid, :verdict, :score, :hb, :hbr,
                 CAST(:ms AS jsonb), CAST(:flags AS jsonb), CAST(:missing AS jsonb), CAST(:im AS jsonb),
                 CAST(:recs AS jsonb), :ms_time)
            ON CONFLICT (claim_id) DO UPDATE
            SET verdict=:verdict, total_score=:score, hard_block=:hb,
                hard_block_reason=:hbr, module_scores=CAST(:ms AS jsonb),
                all_flags=CAST(:flags AS jsonb), missing_documents=CAST(:missing AS jsonb),
                identity_mismatches=CAST(:im AS jsonb), recommendations=CAST(:recs AS jsonb),
                processing_time_ms=:ms_time, created_at=now()
        """),
        {
            "cid":     claim_id,
            "verdict": report.verdict,
            "score":   report.total_score,
            "hb":      report.hard_block,
            "hbr":     report.hard_block_reason,
            "ms":      json.dumps([m.model_dump() for m in report.module_scores]),
            "flags":   json.dumps([f.model_dump() for f in report.all_flags]),
            "missing": json.dumps(report.missing_documents),
            "im":      json.dumps(report.identity_mismatches),
            "recs":    json.dumps(report.recommendations),
            "ms_time": report.processing_time_ms,
        },
    )

    # Update claim status
    await db.execute(
        text("UPDATE claims SET status='SCORED', updated_at=now() WHERE id=:cid"),
        {"cid": claim_id},
    )

    return report


# ─────────────────────────────────────────
# 4. Get saved report
# ─────────────────────────────────────────

@router.get("/{claim_id}/report", response_model=dict)
async def get_report(claim_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT * FROM claim_score_reports WHERE claim_id = :cid"),
        {"cid": claim_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No report found. Run /score first.")
    return dict(row._mapping)




# ─────────────────────────────────────────
# Internal helper
# ─────────────────────────────────────────

async def _get_claim_or_404(claim_id: int, db: AsyncSession) -> dict:
    result = await db.execute(
        text("""
            SELECT c.id, c.claim_ref, c.patient_id, c.package_id, c.hospital_id,
                   c.admission_date, c.discharge_date, c.status,
                   pat.name AS patient_name, pat.pmjay_number, pat.dob, pat.gender,
                   pkg.code AS package_code, pkg.name AS package_name
            FROM claims c
            JOIN patients pat ON pat.id = c.patient_id
            JOIN packages pkg ON pkg.id = c.package_id
            WHERE c.id = :cid
        """),
        {"cid": claim_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Claim not found")
    return dict(row._mapping)

# ─────────────────────────────────────────
# 6. Extract fields from uploaded PDFs
# ─────────────────────────────────────────

from core.auth import get_current_active_user
import io
import pdfplumber

@router.post("/extract-fields")
async def extract_fields_from_documents(
    package_code: str = Form(...),
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_user)
):
    """
    Accepts a package code and multiple PDF files.
    Extracts text from PDFs, determines required fields for the package DYNAMICALLY
    (regardless of field group name), and uses the AI to extract structured JSON.

    Also cross-references optional lab/radiology documents: if the clinical notes
    (laboratory_findings / radiology_findings) recommend tests that haven't been uploaded,
    they are returned as suggested_missing_docs with MEDIUM severity flags.
    """
    # 1. Validate package
    pkg = await db.execute(
        text("SELECT id, name FROM packages WHERE code = :code AND is_active = true"),
        {"code": package_code}
    )
    package = pkg.fetchone()
    if not package:
        raise HTTPException(status_code=404, detail=f"Package {package_code} not found")

    # 2. Fetch ALL fields for this package with their group info.
    #    We split them into:
    #    - extractable_fields  : fields the user types/fills in (data_type = 'string')
    #    - optional_binary_fields : lab/radiology/image uploads that are optional (data_type = 'array')
    req_result = await db.execute(
        text("""
            SELECT tf.field_name AS field_key, pd.label, pd.mandatory, tfg.group_name, pd.data_type
            FROM package_documents pd
            JOIN text_fields tf ON tf.id = pd.field_key_id
            JOIN text_field_groups tfg ON tfg.id = pd.field_group_id
            WHERE pd.package_id = :pid
            ORDER BY pd.sort_order
        """),
        {"pid": package.id}
    )
    all_fields = req_result.fetchall()

    extractable_fields = [
        {"key": r.field_key, "label": r.label, "mandatory": r.mandatory}
        for r in all_fields if r.data_type == "string"
    ]
    optional_binary_fields = [
        {"key": r.field_key, "label": r.label, "group": r.group_name}
        for r in all_fields
        if r.data_type == "array" and not r.mandatory
    ]

    if not extractable_fields:
        return {"extracted_data": {}, "message": "No text fields are required for this package."}

    # 3. Convert files directly to base64 for direct AI multimodal processing (handles PDF and images natively)
    import base64

    file_base64_list = []
    for f in files:
        await f.seek(0)
        content = await f.read()
        if content:
            b64_str = base64.b64encode(content).decode("utf-8")
            file_base64_list.append(b64_str)

    if not file_base64_list:
        raise HTTPException(status_code=400, detail="No files provided or files are empty.")

    # 4. Build AI prompt
    ai_client = get_ai_client(settings.AI_PROVIDER, settings.AI_API_KEY)

    fields_list_str = "\n".join([
        f"- {f['key']} (Description: {f['label']}, Mandatory: {f['mandatory']})"
        for f in extractable_fields
    ])

    optional_labs_str = ""
    if optional_binary_fields:
        optional_labs_str = (
            "\n\nOPTIONAL LAB/RADIOLOGY DOCUMENTS for this package (not yet uploaded):\n"
            + "\n".join([f"- {f['key']}: {f['label']} [{f['group']}]" for f in optional_binary_fields])
            + "\n\nIMPORTANT: Read the values of 'laboratory_findings' and 'radiology_findings' fields "
            "(if present) from the clinical notes. If they explicitly recommend or mention tests that "
            "match any OPTIONAL LAB/RADIOLOGY DOCUMENTS listed above, include those field_keys in "
            "'suggested_missing_docs'. Only include if genuinely recommended in the text."
        )

    system_prompt = "You are a precise medical document data extraction assistant. Return only valid JSON, no markdown."
    prompt = (
        "Extract the requested fields from the attached medical documents:\n\n"
        f"FIELDS TO EXTRACT:\n{fields_list_str}"
        f"{optional_labs_str}\n\n"
        "Return ONLY a single JSON object with exactly these two top-level keys:\n"
        "  \"extracted_data\": object where keys = field_keys above, values = extracted text (null if not found)\n"
        "  \"suggested_missing_docs\": array of field_keys from optional list that are recommended in the notes ([] if none)\n"
        "Do NOT wrap in markdown. Return raw JSON only."
    )

    try:
        response_text = await ai_client.call(prompt=prompt, images=file_base64_list, system=system_prompt)

        # Clean JSON block if AI wraps it in markdown
        cleaned = response_text.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].split("```")[0].strip()

        parsed = json.loads(cleaned)

        # Handle both nested (new) and flat (legacy) response shapes
        if "extracted_data" in parsed:
            extracted_data = parsed["extracted_data"]
            suggested_missing = parsed.get("suggested_missing_docs", [])
        else:
            extracted_data = parsed
            suggested_missing = []

        # Build human-readable suggested missing doc flags
        optional_map = {f["key"]: f["label"] for f in optional_binary_fields}
        suggested_flags = [
            {
                "field_key": key,
                "label": optional_map.get(key, key),
                "reason": f"Clinical notes recommend '{optional_map.get(key, key)}' but it has not been uploaded.",
                "severity": "MEDIUM"
            }
            for key in suggested_missing
            if key in optional_map  # only return valid package field_keys
        ]

        return {
            "extracted_data": extracted_data,
            "suggested_missing_docs": suggested_flags,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI extraction failed: {str(e)}")


# ═══════════════════════════════════════════════
# PREAUTH ENDPOINTS
# ═══════════════════════════════════════════════

@router.post("/preauth", status_code=201)
async def submit_preauth(
    body: PreauthSubmitRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Submit pre-authorization documents (saves to DB).
    """
    # Validate patient
    pat = await db.execute(
        text("SELECT id, name, pmjay_number FROM patients WHERE id = :pid"),
        {"pid": body.patient_id},
    )
    patient = pat.fetchone()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Validate package
    pkg = await db.execute(
        text("SELECT id, code, name FROM packages WHERE code = :code AND is_active = true"),
        {"code": body.package_code},
    )
    package = pkg.fetchone()
    if not package:
        raise HTTPException(status_code=404, detail=f"Package {body.package_code} not found")

    # Generate preauth ref
    preauth_ref = f"PA-{time.strftime('%Y')}-{str(uuid.uuid4())[:8].upper()}"

    # Insert preauth
    preauth_result = await db.execute(
        text("""
            INSERT INTO preauths
                (preauth_ref, patient_id, package_id, hospital_id, admission_date)
            VALUES
                (:ref, :pid, :pkg_id, :hosp, :admit)
            RETURNING id
        """),
        {
            "ref":      preauth_ref,
            "pid":      body.patient_id,
            "pkg_id":   package.id,
            "hosp":     body.hospital_id,
            "admit":    body.admission_date,
        },
    )
    preauth_id = preauth_result.fetchone().id

    # Insert documents
    for doc in body.documents:
        if doc.data_type_is_string():
            # Single text field
            await db.execute(
                text("""
                    INSERT INTO preauth_documents
                        (preauth_id, field_key, field_group, text_content)
                    VALUES (:pid, :fkey, :fgrp, :txt)
                """),
                {
                    "pid":  preauth_id,
                    "fkey": doc.field_key,
                    "fgrp": doc.field_group,
                    "txt":  doc.text_value,
                },
            )
        else:
            # Array of files — one row per file
            for i, f in enumerate(doc.files):
                await db.execute(
                    text("""
                        INSERT INTO preauth_documents
                            (preauth_id, field_key, field_group, filename, content_base64, sort_order)
                        VALUES (:pid, :fkey, :fgrp, :fname, :b64, :ord)
                    """),
                    {
                        "pid":   preauth_id,
                        "fkey":  doc.field_key,
                        "fgrp":  doc.field_group,
                        "fname": f.filename,
                        "b64":   f.content_base64,
                        "ord":   i,
                    },
                )

    return {
        "preauth_id":  preauth_id,
        "preauth_ref": preauth_ref,
        "status":    "PENDING",
        "message":   "Preauth documents saved. Call /preauth/{id}/preflight to check, then /preauth/{id}/score to run engine.",
    }


@router.get("/preauth/{preauth_id}/preflight", response_model=PreflightResult)
async def preauth_preflight_check(preauth_id: int, db: AsyncSession = Depends(get_db)):
    """
    Pre-flight existence check for Pre-Authorization.
    """
    preauth = await _get_preauth_or_404(preauth_id, db)

    # Required fields from package for PREAUTH stage only
    required = await db.execute(
        text("""
            SELECT tf.field_name AS field_key, pd.label, pd.mandatory
            FROM package_documents pd
            JOIN text_fields tf ON tf.id = pd.field_key_id
            WHERE pd.package_id = :pkg_id AND pd.stage = 'preauth'
            ORDER BY pd.sort_order
        """),
        {"pkg_id": preauth["package_id"]},
    )
    required_fields = required.fetchall()

    # Submitted fields
    submitted = await db.execute(
        text("""
            SELECT DISTINCT field_key,
                   CASE
                     WHEN text_content IS NOT NULL AND text_content != '' THEN true
                     WHEN filename IS NOT NULL THEN true
                     ELSE false
                   END as has_content
            FROM preauth_documents
            WHERE preauth_id = :pid
        """),
        {"pid": preauth_id},
    )
    submitted_map = {r.field_key: r.has_content for r in submitted.fetchall()}

    field_results = []
    missing_mandatory = []
    missing_optional = []

    for req in required_fields:
        provided = req.field_key in submitted_map
        has_content = submitted_map.get(req.field_key, False)

        if not provided:
            status = "missing"
        elif not has_content:
            status = "empty"
        else:
            status = "ok"

        field_results.append(PreflightField(
            field_key=req.field_key,
            label=req.label,
            mandatory=req.mandatory,
            provided=provided,
            status=status,
        ))

        if status != "ok":
            if req.mandatory:
                missing_mandatory.append(req.label)
            else:
                missing_optional.append(req.label)

    return PreflightResult(
        ready=len(missing_mandatory) == 0,
        missing_mandatory=missing_mandatory,
        missing_optional=missing_optional,
        fields=field_results,
    )


@router.post("/preauth/{preauth_id}/score", response_model=PreauthScoreReport)
async def score_preauth(preauth_id: int, db: AsyncSession = Depends(get_db)):
    """
    Score the pre-authorization documents using only the preauth documents and rules.
    """
    # Preflight guard
    preflight = await preauth_preflight_check(preauth_id, db)
    if not preflight.ready:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Cannot score preauth: mandatory preauth documents missing",
                "missing": preflight.missing_mandatory,
            },
        )

    preauth = await _get_preauth_or_404(preauth_id, db)

    # Load preauth documents
    docs_result = await db.execute(
        text("SELECT * FROM preauth_documents WHERE preauth_id = :pid ORDER BY field_key, sort_order"),
        {"pid": preauth_id},
    )
    documents = docs_result.fetchall()

    # Load weights from DB
    weights_result = await db.execute(
        text("SELECT agent_name, weight FROM scoring_weights WHERE package_id = :pid"),
        {"pid": preauth["package_id"]},
    )
    weights = {r.agent_name: float(r.weight) for r in weights_result.fetchall()}

    # Prepare claim_context for ClaimOrchestratorAgent (using preauth details)
    # discharge_date is set to "N/A" for preauth stage
    claim_context = {
        "claim_id":       preauth_id,
        "claim_ref":      preauth["preauth_ref"],
        "patient_id":     preauth["patient_id"],
        "patient_name":   preauth["patient_name"],
        "pmjay_number":   preauth["pmjay_number"],
        "patient_dob":    str(preauth["dob"]),
        "patient_gender": preauth["gender"],
        "package_code":   preauth["package_code"],
        "package_name":   preauth["package_name"],
        "hospital_id":    preauth["hospital_id"],
        "admission_date": str(preauth["admission_date"]),
        "discharge_date": "N/A",
        "documents":      [dict(d._mapping) for d in documents],
        "required_fields": [],
        "agent_prompts":   {},
    }

    # Load required fields for preauth stage
    req_result = await db.execute(
        text("""
            SELECT tf.field_name AS field_key, pd.label, pd.mandatory
            FROM package_documents pd
            JOIN text_fields tf ON tf.id = pd.field_key_id
            WHERE pd.package_id = :pid AND pd.stage = 'preauth'
            ORDER BY pd.sort_order
        """),
        {"pid": preauth["package_id"]},
    )
    claim_context["required_fields"] = [
        {"field_key": r.field_key, "label": r.label, "mandatory": r.mandatory}
        for r in req_result.fetchall()
    ]

    # Load clinical relevance groups (only if marked clinical_relevant AND stage = 'preauth')
    cr_result = await db.execute(
        text("""
            SELECT DISTINCT tfg.group_name
            FROM package_documents pd
            JOIN text_field_groups tfg ON tfg.id = pd.field_group_id
            WHERE pd.package_id = :pid AND pd.clinical_relevant = true AND pd.stage = 'preauth'
        """),
        {"pid": preauth["package_id"]},
    )
    claim_context["clinical_relevant_groups"] = [r.group_name for r in cr_result.fetchall()]

    # Load identity_relevant groups for preauth
    ir_result = await db.execute(
        text("""
            SELECT DISTINCT tfg.group_name
            FROM package_documents pd
            JOIN text_field_groups tfg ON tfg.id = pd.field_group_id
            WHERE pd.package_id = :pid AND pd.identity_relevant = true AND pd.stage = 'preauth'
        """),
        {"pid": preauth["package_id"]},
    )
    claim_context["identity_relevant_groups"] = [r.group_name for r in ir_result.fetchall()]

    # Load lab_relevant groups for preauth
    lr_result = await db.execute(
        text("""
            SELECT DISTINCT tfg.group_name
            FROM package_documents pd
            JOIN text_field_groups tfg ON tfg.id = pd.field_group_id
            WHERE pd.package_id = :pid AND pd.lab_relevant = true AND pd.stage = 'preauth'
        """),
        {"pid": preauth["package_id"]},
    )
    claim_context["lab_relevant_groups"] = [r.group_name for r in lr_result.fetchall()]

    # Load image_relevant groups for preauth
    imgr_result = await db.execute(
        text("""
            SELECT DISTINCT tfg.group_name
            FROM package_documents pd
            JOIN text_field_groups tfg ON tfg.id = pd.field_group_id
            WHERE pd.package_id = :pid AND pd.image_relevant = true AND pd.stage = 'preauth'
        """),
        {"pid": preauth["package_id"]},
    )
    claim_context["image_relevant_groups"] = [r.group_name for r in imgr_result.fetchall()]

    # Load radiology_relevant groups for preauth
    radr_result = await db.execute(
        text("""
            SELECT DISTINCT tfg.group_name
            FROM package_documents pd
            JOIN text_field_groups tfg ON tfg.id = pd.field_group_id
            WHERE pd.package_id = :pid AND pd.radiology_relevant = true AND pd.stage = 'preauth'
        """),
        {"pid": preauth["package_id"]},
    )
    claim_context["radiology_relevant_groups"] = [r.group_name for r in radr_result.fetchall()]

    # Load agent prompts
    prompts_result = await db.execute(text("SELECT agent_name, system_prompt FROM agent_prompts"))
    claim_context["agent_prompts"] = {r.agent_name: r.system_prompt for r in prompts_result.fetchall()}

    # Run agents using our Orchestrator
    ai_client = get_ai_client(settings.AI_PROVIDER, settings.AI_API_KEY)
    orchestrator = ClaimOrchestratorAgent(ai_client=ai_client, weights=weights)
    report = await orchestrator.process_claim(claim_context)

    # Persist report to preauth_score_reports
    await db.execute(
        text("""
            INSERT INTO preauth_score_reports
                (preauth_id, verdict, total_score, hard_block, hard_block_reason,
                 module_scores, all_flags, missing_documents, identity_mismatches,
                 recommendations, processing_time_ms)
            VALUES
                (:pid, :verdict, :score, :hb, :hbr,
                 CAST(:ms AS jsonb), CAST(:flags AS jsonb), CAST(:missing AS jsonb), CAST(:im AS jsonb),
                 CAST(:recs AS jsonb), :ms_time)
            ON CONFLICT (preauth_id) DO UPDATE
            SET verdict=:verdict, total_score=:score, hard_block=:hb,
                hard_block_reason=:hbr, module_scores=CAST(:ms AS jsonb),
                all_flags=CAST(:flags AS jsonb), missing_documents=CAST(:missing AS jsonb),
                identity_mismatches=CAST(:im AS jsonb), recommendations=CAST(:recs AS jsonb),
                processing_time_ms=:ms_time, created_at=now()
        """),
        {
            "pid":     preauth_id,
            "verdict": report.verdict,
            "score":   report.total_score,
            "hb":      report.hard_block,
            "hbr":     report.hard_block_reason,
            "ms":      json.dumps([m.model_dump() for m in report.module_scores]),
            "flags":   json.dumps([f.model_dump() for f in report.all_flags]),
            "missing": json.dumps(report.missing_documents),
            "im":      json.dumps(report.identity_mismatches),
            "recs":    json.dumps(report.recommendations),
            "ms_time": report.processing_time_ms,
        },
    )

    # Update preauth status
    await db.execute(
        text("UPDATE preauths SET status='SCORED', updated_at=now() WHERE id=:pid"),
        {"pid": preauth_id},
    )

    return PreauthScoreReport(
        preauth_id=preauth_id,
        preauth_ref=report.claim_ref,
        package_code=report.package_code,
        package_name=report.package_name,
        verdict=report.verdict,
        total_score=report.total_score,
        hard_block=report.hard_block,
        hard_block_reason=report.hard_block_reason,
        module_scores=report.module_scores,
        all_flags=report.all_flags,
        agent_results=report.agent_results,
        missing_documents=report.missing_documents,
        identity_mismatches=report.identity_mismatches,
        recommendations=report.recommendations,
        processing_time_ms=report.processing_time_ms,
    )


@router.get("/preauth/{preauth_id}/report", response_model=dict)
async def get_preauth_report(preauth_id: int, db: AsyncSession = Depends(get_db)):
    """
    Get saved preauth score report.
    """
    result = await db.execute(
        text("SELECT * FROM preauth_score_reports WHERE preauth_id = :pid"),
        {"pid": preauth_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No report found. Run /preauth/{id}/score first.")
    return dict(row._mapping)


async def _get_preauth_or_404(preauth_id: int, db: AsyncSession) -> dict:
    result = await db.execute(
        text("""
            SELECT c.id, c.preauth_ref, c.patient_id, c.package_id, c.hospital_id,
                   c.admission_date, c.status,
                   pat.name AS patient_name, pat.pmjay_number, pat.dob, pat.gender,
                   pkg.code AS package_code, pkg.name AS package_name
            FROM preauths c
            JOIN patients pat ON pat.id = c.patient_id
            JOIN packages pkg ON pkg.id = c.package_id
            WHERE c.id = :pid
        """),
        {"pid": preauth_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Preauth not found")
    return dict(row._mapping)


