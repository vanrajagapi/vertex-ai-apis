-- ═══════════════════════════════════════════════════════════════
-- PMJAY Claim Pre-Auth System — Database Schema
-- Migration 008 — Add clinical_relevant flag to package_documents
--
-- Allows admins to mark which field groups should be included
-- in ClinicalRelevanceAgent analysis, instead of hardcoding
-- 'text' and 'ot_notes' in Python code.
-- ═══════════════════════════════════════════════════════════════

-- ───────────────────────────────────────
-- 1. ADD THE COLUMN
-- ───────────────────────────────────────
ALTER TABLE package_documents
ADD COLUMN IF NOT EXISTS clinical_relevant BOOLEAN NOT NULL DEFAULT false;

-- ───────────────────────────────────────
-- 2. BACKFILL: mark existing text/ot_notes groups as clinical_relevant
--    These were previously hardcoded in the ClinicalRelevanceAgent.
-- ───────────────────────────────────────
UPDATE package_documents pd
SET clinical_relevant = true
FROM text_field_groups tfg
WHERE pd.field_group_id = tfg.id
  AND tfg.group_name IN ('text', 'ot_notes');
