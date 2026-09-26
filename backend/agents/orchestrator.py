"""
ClaimOrchestratorAgent — v2
- Accepts claim_context dict (not a Pydantic model)
- Weights are injected from DB (dynamic per package)
- No import of ClaimSubmission or core.package_db
"""

import time
import asyncio
from models.schemas import (
    AgentResult, ClaimScoreReport, ModuleScore, Flag, FlagSeverity, Verdict,
)
try:
    # pyrefly: ignore [missing-import]
    from langsmith import traceable
except ImportError:
    def traceable(**kwargs):
        def decorator(func):
            return func
        return decorator

# pyrefly: ignore [missing-import]
from .agents import (
    DocumentExtractorAgent,
    IdentityValidatorAgent,
    PackageComplianceAgent,
    ClinicalRelevanceAgent,
    LabAnalyzerAgent,
    ImageValidatorAgent,
    RadiologyValidatorAgent,
    BillingAnalyserAgent,
    DischargeSummaryAnalyserAgent,
    ICPAgent,
)
from core.ai_clients import AIClient, StubClient
from core.config import settings


class ClaimOrchestratorAgent:
    """
    Runs all agents in order, combines weighted scores, returns ClaimScoreReport.

    weights: dict[agent_name, float] — loaded from scoring_weights table (dynamic).
             Falls back to hard-coded defaults if DB has no weights yet.

    ai_client: any AIClient (Claude, GPT-4o, Gemini, Stub).

    include_billing: set to True for claims (not preauth) to include the
                     BillingAnalyserAgent in the pipeline.
    """

    DEFAULT_WEIGHTS = {
        "IdentityValidatorAgent":    0.35,
        "PackageComplianceAgent":    0.30,
        "ClinicalRelevanceAgent":    0.25,
        "LabAnalyzerAgent":          0.05,
        "ImageValidatorAgent":       0.025,
        "RadiologyValidatorAgent":   0.025,
        "BillingAnalyserAgent":      0.00,
        "DischargeSummaryAnalyserAgent": 0.00,
    }

    def __init__(self, ai_client: AIClient = None, weights: dict[str, float] = None, include_billing: bool = False, include_discharge: bool = False):
        client = ai_client or StubClient()
        # Merge provided weights with defaults (DB weights take priority)
        self.weights = {**self.DEFAULT_WEIGHTS, **(weights or {})}

        self.agents = [
            DocumentExtractorAgent(ai_client=client),
            IdentityValidatorAgent(ai_client=client),
            PackageComplianceAgent(ai_client=client),
            ClinicalRelevanceAgent(ai_client=client),
            LabAnalyzerAgent(ai_client=client),
            ImageValidatorAgent(ai_client=client),
            RadiologyValidatorAgent(ai_client=client),
        ]

        # CLAIM stage specific agents
        if include_billing:
            self.agents.append(BillingAnalyserAgent(ai_client=client))
        if include_discharge:
            self.agents.append(DischargeSummaryAnalyserAgent(ai_client=client))
            self.agents.append(ICPAgent(ai_client=client))

    @traceable(run_type="chain", name="orchestrate_claim")
    async def process_claim(self, claim_context: dict) -> ClaimScoreReport:
        """
        claim_context must contain:
            claim_id, claim_ref, patient_name, pmjay_number, patient_dob,
            patient_gender, package_code, package_name, hospital_id,
            admission_date, discharge_date,
            documents: list[dict],
            required_fields: list[dict]   ← from package_documents table
        """
        start_ms      = int(time.time() * 1000)
        context       = {}
        agent_results: list[AgentResult] = []
        all_flags:     list[Flag]        = []

        # 1. Run DocumentExtractorAgent first as other agents depend on its output
        extractor_agent = next(a for a in self.agents if a.name == "DocumentExtractorAgent")
        extractor_result = await extractor_agent.run(claim_context, context)
        context[extractor_agent.name] = extractor_result.details
        agent_results.append(extractor_result)
        all_flags.extend(extractor_result.flags)

        # 2. Run the rest of the agents concurrently
        concurrent_agents = [a for a in self.agents if a.name != "DocumentExtractorAgent"]
        
        async def run_agent(agent):
            return agent.name, await agent.run(claim_context, context)

        results = await asyncio.gather(*(run_agent(a) for a in concurrent_agents))

        for agent_name, result in results:
            context[agent_name] = result.details
            agent_results.append(result)
            all_flags.extend(result.flags)

        # ── Weighted scoring ──
        module_scores: list[ModuleScore] = []
        total_weighted = 0.0

        for result in agent_results:
            # DocumentExtractorAgent is a parser/helper, not a scoring validator
            if result.agent_name == "DocumentExtractorAgent":
                continue

            weight   = self.weights.get(result.agent_name, 0.0)
            weighted = result.score * weight
            total_weighted += weighted
            module_scores.append(ModuleScore(
                module=result.agent_name,
                weight=weight,
                raw_score=result.score,
                weighted_score=round(weighted, 2),
            ))

        total_score = round(total_weighted, 2)

        # ── Hard block checks ──
        hard_block        = False
        hard_block_reason = None

        identity_result = _find(agent_results, "IdentityValidatorAgent")
        if identity_result and identity_result.details.get("hard_block"):
            hard_block        = True
            hard_block_reason = "Patient identity mismatch across documents"

        compliance_result = _find(agent_results, "PackageComplianceAgent")
        if compliance_result and compliance_result.details.get("hard_block"):
            hard_block        = True
            hard_block_reason = hard_block_reason or "More than 2 mandatory documents missing"

        radiology_result = _find(agent_results, "RadiologyValidatorAgent")
        if radiology_result and not radiology_result.passed and any(
            "HARD BLOCK" in f.reason for f in radiology_result.flags
        ):
            hard_block        = True
            hard_block_reason = hard_block_reason or "Radiology date outside admission–discharge range"

        billing_result = _find(agent_results, "BillingAnalyserAgent")
        if billing_result and billing_result.details.get("hard_block"):
            hard_block        = True
            hard_block_reason = hard_block_reason or "Billed amount exceeds the package rate limit"

        # ── Verdict ──
        if hard_block:
            verdict = Verdict.FAIL
        elif total_score >= settings.PASS_THRESHOLD:
            verdict = Verdict.PASS
        elif total_score >= settings.REVIEW_THRESHOLD:
            verdict = Verdict.REVIEW
        else:
            verdict = Verdict.FAIL

        # ── Metadata ──
        missing_docs        = compliance_result.details.get("missing_mandatory", []) if compliance_result else []
        identity_mismatches = identity_result.details.get("mismatches", []) if identity_result else []
        recommendations     = _build_recommendations(verdict, all_flags, missing_docs)

        elapsed = int(time.time() * 1000) - start_ms

        return ClaimScoreReport(
            claim_id=claim_context["claim_id"],
            claim_ref=claim_context["claim_ref"],
            package_code=claim_context["package_code"],
            package_name=claim_context["package_name"],
            verdict=verdict,
            total_score=total_score,
            hard_block=hard_block,
            hard_block_reason=hard_block_reason,
            module_scores=module_scores,
            all_flags=all_flags,
            agent_results=agent_results,
            missing_documents=missing_docs,
            identity_mismatches=identity_mismatches,
            recommendations=recommendations,
            processing_time_ms=elapsed,
        )


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────

def _find(results: list[AgentResult], name: str) -> AgentResult | None:
    return next((r for r in results if r.agent_name == name), None)


def _build_recommendations(
    verdict: Verdict, flags: list[Flag], missing_docs: list[str]
) -> list[str]:
    recs = []
    if missing_docs:
        recs.append(f"Upload missing documents: {', '.join(missing_docs)}")
    for f in [x for x in flags if x.severity == FlagSeverity.HIGH][:3]:
        recs.append(f"Resolve: {f.reason}")
    if verdict == Verdict.PASS:
        recs.append("Claim is ready for TPA submission.")
    elif verdict == Verdict.REVIEW:
        recs.append("Send to TPA with attached flag report for manual review.")
    else:
        recs.append("Return to hospital with full flag report before resubmission.")
    return recs
