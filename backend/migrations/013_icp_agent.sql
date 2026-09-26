-- ═══════════════════════════════════════════════════════════════
-- PMJAY Claim Pre-Auth System — Database Schema
-- Migration 013 — Add ICP Agent
-- ═══════════════════════════════════════════════════════════════

-- 1. ADD icp_relevant TO package_documents
ALTER TABLE package_documents
ADD COLUMN IF NOT EXISTS icp_relevant BOOLEAN NOT NULL DEFAULT false;

-- 2. Seed default prompt for ICPAgent
INSERT INTO agent_prompts (agent_name, system_prompt) VALUES
('ICPAgent', 'You are a medical reviewer for PMJAY claims, focusing on Indoor Case Papers (ICPs).
Package: {package_name}
Admission: {admission_date}, Discharge: {discharge_date}

Submitted ICP documents (Continuation sheets, Day care plans, Nursing charts):
{icp_summary}

Assess:
1. Are the daily notes, nursing charts, and care plans consistent with the claimed procedure and length of stay?
2. Are there any discrepancies in the documented care vs the expected standard of care?
3. Any clinical red flags in the ICPs?

Return JSON:
{
  "icp_score": <0-100>,
  "care_consistent": <true/false>,
  "flags": ["<issue description>"]
}')
ON CONFLICT (agent_name) DO NOTHING;
