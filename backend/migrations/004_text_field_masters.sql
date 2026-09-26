-- ═══════════════════════════════════════════════════════════════
-- PMJAY Claim Pre-Auth System — Database Schema
-- Migration 004 — Text Field Groups & Text Fields Masters
-- ═══════════════════════════════════════════════════════════════

-- ───────────────────────────────────────
-- 1. MASTER: TEXT FIELD GROUPS
--    Defines named groups that can contain multiple text fields.
-- ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS text_field_groups (
    id              SERIAL PRIMARY KEY,
    group_name      VARCHAR(255)    NOT NULL UNIQUE,
    description     TEXT,
    is_active       BOOLEAN         NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_text_field_groups_name ON text_field_groups(group_name);


-- ───────────────────────────────────────
-- 2. MASTER: TEXT FIELDS
--    Individual text fields that can be assigned to groups.
-- ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS text_fields (
    id              SERIAL PRIMARY KEY,
    field_name      VARCHAR(255)    NOT NULL UNIQUE,
    description     TEXT,
    is_active       BOOLEAN         NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_text_fields_name ON text_fields(field_name);


-- ───────────────────────────────────────
-- 3. MAPPING: TEXT FIELD GROUP → TEXT FIELDS  (one-to-many)
--    One group can have many text fields.
--    A text field can belong to multiple groups if needed.
-- ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS text_field_group_mappings (
    id              SERIAL PRIMARY KEY,
    group_id        INT             NOT NULL REFERENCES text_field_groups(id) ON DELETE CASCADE,
    field_id        INT             NOT NULL REFERENCES text_fields(id) ON DELETE CASCADE,
    sort_order      INT             NOT NULL DEFAULT 0,
    is_mandatory    BOOLEAN         NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    UNIQUE(group_id, field_id)
);

CREATE INDEX IF NOT EXISTS idx_tfgm_group ON text_field_group_mappings(group_id);
CREATE INDEX IF NOT EXISTS idx_tfgm_field ON text_field_group_mappings(field_id);
