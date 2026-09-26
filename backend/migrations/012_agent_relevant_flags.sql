-- ═══════════════════════════════════════════════════════════════
-- PMJAY Claim Pre-Auth System — Database Schema
-- Migration 012 — Add per-agent document relevance flags
--
-- Extends package_documents with boolean flags for each agent:
--   identity_relevant, lab_relevant, image_relevant, radiology_relevant
--
-- These flags allow admins to mark which document groups should be
-- passed to each specific agent, mirroring the existing pattern
-- used by clinical_relevant, billing_relevant, and discharge_relevant.
-- ═══════════════════════════════════════════════════════════════

-- ───────────────────────────────────────
-- 1. ADD identity_relevant TO package_documents
--    Marks which field groups should be analyzed by IdentityValidatorAgent.
-- ───────────────────────────────────────
ALTER TABLE package_documents
ADD COLUMN IF NOT EXISTS identity_relevant BOOLEAN NOT NULL DEFAULT false;

-- ───────────────────────────────────────
-- 2. ADD lab_relevant TO package_documents
--    Marks which field groups should be analyzed by LabAnalyzerAgent.
-- ───────────────────────────────────────
ALTER TABLE package_documents
ADD COLUMN IF NOT EXISTS lab_relevant BOOLEAN NOT NULL DEFAULT false;

-- ───────────────────────────────────────
-- 3. ADD image_relevant TO package_documents
--    Marks which field groups should be analyzed by ImageValidatorAgent.
-- ───────────────────────────────────────
ALTER TABLE package_documents
ADD COLUMN IF NOT EXISTS image_relevant BOOLEAN NOT NULL DEFAULT false;

-- ───────────────────────────────────────
-- 4. ADD radiology_relevant TO package_documents
--    Marks which field groups should be analyzed by RadiologyValidatorAgent.
-- ───────────────────────────────────────
ALTER TABLE package_documents
ADD COLUMN IF NOT EXISTS radiology_relevant BOOLEAN NOT NULL DEFAULT false;

-- ───────────────────────────────────────
-- 5. BACKFILL: mark existing pathology groups as lab_relevant
--    These were previously hardcoded in LabAnalyzerAgent.
-- ───────────────────────────────────────
UPDATE package_documents pd
SET lab_relevant = true
FROM text_field_groups tfg
WHERE pd.field_group_id = tfg.id
  AND tfg.group_name = 'pathology';

-- ───────────────────────────────────────
-- 6. BACKFILL: mark existing others groups as image_relevant
--    These were previously hardcoded in ImageValidatorAgent.
-- ───────────────────────────────────────
UPDATE package_documents pd
SET image_relevant = true
FROM text_field_groups tfg
WHERE pd.field_group_id = tfg.id
  AND tfg.group_name = 'others';

-- ───────────────────────────────────────
-- 7. BACKFILL: mark existing radiology groups as radiology_relevant
--    These were previously hardcoded in RadiologyValidatorAgent.
-- ───────────────────────────────────────
UPDATE package_documents pd
SET radiology_relevant = true
FROM text_field_groups tfg
WHERE pd.field_group_id = tfg.id
  AND tfg.group_name = 'radiology';

-- ───────────────────────────────────────
-- 8. BACKFILL: mark ALL document groups as identity_relevant by default
--    IdentityValidatorAgent previously analyzed ALL documents.
-- ───────────────────────────────────────
UPDATE package_documents
SET identity_relevant = true;
