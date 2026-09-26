-- ═══════════════════════════════════════════════════════════════
-- PMJAY Claim Pre-Auth System — Database Schema
-- Migration 006 — Normalize package_documents to use Text Field Masters
-- ═══════════════════════════════════════════════════════════════

-- ───────────────────────────────────────
-- 1. POPULATE MASTER TABLES FROM EXISTING VALUES
-- ───────────────────────────────────────

-- Insert any missing groups into text_field_groups
INSERT INTO text_field_groups (group_name, description)
SELECT DISTINCT field_group, 'Auto-migrated group from package_documents'
FROM package_documents
ON CONFLICT (group_name) DO NOTHING;

-- Insert any missing fields into text_fields
INSERT INTO text_fields (field_name, description)
SELECT DISTINCT field_key, 'Auto-migrated field key from package_documents'
FROM package_documents
ON CONFLICT (field_name) DO NOTHING;


-- ───────────────────────────────────────
-- 2. ALTER TABLE package_documents
-- ───────────────────────────────────────

-- Add the foreign key columns as nullable first
ALTER TABLE package_documents
ADD COLUMN IF NOT EXISTS field_group_id INT REFERENCES text_field_groups(id) ON DELETE RESTRICT,
ADD COLUMN IF NOT EXISTS field_key_id INT REFERENCES text_fields(id) ON DELETE RESTRICT;

-- Populate the foreign key values
UPDATE package_documents pd
SET 
    field_group_id = tfg.id,
    field_key_id = tf.id
FROM text_field_groups tfg, text_fields tf
WHERE pd.field_group = tfg.group_name AND pd.field_key = tf.field_name;

-- Make columns NOT NULL and drop the old string columns
ALTER TABLE package_documents
ALTER COLUMN field_group_id SET NOT NULL,
ALTER COLUMN field_key_id SET NOT NULL;

-- Remove old unique constraint and string columns
ALTER TABLE package_documents DROP CONSTRAINT IF EXISTS package_documents_package_id_field_key_key;
ALTER TABLE package_documents DROP COLUMN IF EXISTS field_group;
ALTER TABLE package_documents DROP COLUMN IF EXISTS field_key;

-- Add new unique constraint
ALTER TABLE package_documents ADD CONSTRAINT package_documents_package_id_field_key_id_key UNIQUE(package_id, field_key_id);
