-- ═══════════════════════════════════════════════════════════════
-- PMJAY Claim Pre-Auth System — Database Schema
-- Migration 011 — Discharge Summary Analyser Agent support
--
-- 1. Add discharge_relevant boolean to package_documents table
-- 2. Seed default DischargeSummaryAnalyserAgent weights for all packages
-- 3. Seed Agent prompt
-- ═══════════════════════════════════════════════════════════════

-- ───────────────────────────────────────
-- 1. ADD discharge_relevant TO package_documents
--    Marks which field groups should be analyzed by the DischargeSummaryAnalyserAgent.
-- ───────────────────────────────────────
ALTER TABLE package_documents
ADD COLUMN IF NOT EXISTS discharge_relevant BOOLEAN NOT NULL DEFAULT false;

-- ───────────────────────────────────────
-- 2. SEED: DEFAULT SCORING WEIGHTS FOR DischargeSummaryAnalyserAgent
--    Weight = 0 by default so existing weights are not disrupted.
-- ───────────────────────────────────────
INSERT INTO scoring_weights (package_id, agent_name, weight, updated_by)
SELECT p.id, 'DischargeSummaryAnalyserAgent', 0.00, 'system_migration_011'
FROM packages p
ON CONFLICT (package_id, agent_name) DO NOTHING;

-- ───────────────────────────────────────
-- 3. SEED: Agent prompt for DischargeSummaryAnalyserAgent
-- ───────────────────────────────────────
INSERT INTO agent_prompts (agent_name, system_prompt)
VALUES (
    'DischargeSummaryAnalyserAgent',
    'You are a PMJAY medical auditor reviewing discharge summaries. Analyze the submitted discharge documents and verify:
1. The discharge summary clearly mentions the correct patient, admission, and discharge dates.
2. The primary diagnosis and performed procedures align with the claimed package.
3. The patient condition at discharge is stated (e.g., stable, referred, LAMA, death).
4. Discharge medications and follow-up advice are appropriately documented.
5. Identify any discrepancies between the package criteria and the documented course in the hospital.

Return JSON:
{{
  "discharge_score": <0-100>,
  "diagnosis_match": <true/false>,
  "procedure_match": <true/false>,
  "condition_at_discharge": "<extracted condition>",
  "discrepancies": ["<list of issues or mismatches>"],
  "flags": ["<issue descriptions>"]
}}'
)
ON CONFLICT (agent_name) DO NOTHING;
