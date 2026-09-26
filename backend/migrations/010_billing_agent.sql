-- ═══════════════════════════════════════════════════════════════
-- PMJAY Claim Pre-Auth System — Database Schema
-- Migration 010 — Billing Analyser Agent support
--
-- 1. Add package_rate_inr to packages table
-- 2. Add billing_relevant boolean to package_documents table
-- 3. Seed default BillingAnalyserAgent weights for all packages
-- ═══════════════════════════════════════════════════════════════

-- ───────────────────────────────────────
-- 1. ADD package_rate_inr TO packages
--    Stores the maximum rate (INR) allowed for each package.
-- ───────────────────────────────────────
ALTER TABLE packages
ADD COLUMN IF NOT EXISTS package_rate_inr NUMERIC(12,2) DEFAULT NULL;

-- ───────────────────────────────────────
-- 2. ADD billing_relevant TO package_documents
--    Marks which field groups should be analyzed by the BillingAnalyserAgent.
-- ───────────────────────────────────────
ALTER TABLE package_documents
ADD COLUMN IF NOT EXISTS billing_relevant BOOLEAN NOT NULL DEFAULT false;

-- ───────────────────────────────────────
-- 3. SEED: DEFAULT SCORING WEIGHTS FOR BillingAnalyserAgent
--    Weight = 0 by default so existing weights are not disrupted.
--    Admin can adjust weights per package once billing agent is active.
-- ───────────────────────────────────────
INSERT INTO scoring_weights (package_id, agent_name, weight, updated_by)
SELECT p.id, 'BillingAnalyserAgent', 0.00, 'system_migration_010'
FROM packages p
ON CONFLICT (package_id, agent_name) DO NOTHING;

-- ───────────────────────────────────────
-- 4. SEED: Agent prompt for BillingAnalyserAgent
-- ───────────────────────────────────────
INSERT INTO agent_prompts (agent_name, system_prompt)
VALUES (
    'BillingAnalyserAgent',
    'You are a PMJAY billing compliance auditor. Analyze the submitted billing documents and verify:
1. Total billed amount does not exceed the package rate (INR).
2. Individual line items are reasonable and consistent with the claimed procedure.
3. No duplicate billing entries.
4. Consumable/implant costs match supporting invoices.
5. No unbundling (splitting a single procedure into multiple billing codes to inflate costs).

Return JSON:
{{
  "billing_score": <0-100>,
  "total_billed_amount": <extracted total amount or null>,
  "package_rate_inr": <package rate limit>,
  "amount_exceeded": <true/false>,
  "excess_amount": <amount over limit or 0>,
  "duplicate_entries": [<list of suspected duplicate items>],
  "suspicious_items": [<list of items with unusual pricing>],
  "flags": ["<issue descriptions>"]
}}'
)
ON CONFLICT (agent_name) DO NOTHING;
