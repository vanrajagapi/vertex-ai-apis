-- ═══════════════════════════════════════════════════════════════
-- PMJAY Claim Pre-Auth System — Database Schema
-- Migration 009 — Preauth flow, stage enum and mappings
-- ═══════════════════════════════════════════════════════════════

-- ───────────────────────────────────────
-- 1. ADD STAGE TO package_documents
-- ───────────────────────────────────────
ALTER TABLE package_documents
ADD COLUMN IF NOT EXISTS stage VARCHAR(20) NOT NULL CHECK (stage IN ('preauth', 'claim')) DEFAULT 'preauth';

-- ───────────────────────────────────────
-- 2. BACKFILL STAGES FOR SEEDED DOCUMENTS
-- ───────────────────────────────────────
-- 'discharge_summary', 'ot_notes', 'surgery_photos', 'others' are claim stage.
-- Everything else remains preauth stage.
UPDATE package_documents pd
SET stage = 'claim'
FROM text_fields tf
WHERE pd.field_key_id = tf.id
  AND tf.field_name IN ('discharge_summary', 'ot_notes', 'surgery_photos', 'others');

-- ───────────────────────────────────────
-- 3. PREAUTHS TABLE
-- ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS preauths (
    id              SERIAL PRIMARY KEY,
    preauth_ref     VARCHAR(50)     NOT NULL UNIQUE,    -- PA-2026-XXXXXX
    patient_id      INT             NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    package_id      INT             NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    hospital_id     VARCHAR(50)     NOT NULL,
    admission_date  DATE            NOT NULL,
    status          VARCHAR(20)     NOT NULL DEFAULT 'PENDING',  -- PENDING | SCORED | APPROVED | REJECTED
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_preauths_patient  ON preauths(patient_id);
CREATE INDEX IF NOT EXISTS idx_preauths_package  ON preauths(package_id);
CREATE INDEX IF NOT EXISTS idx_preauths_ref      ON preauths(preauth_ref);

-- ───────────────────────────────────────
-- 4. PREAUTH DOCUMENTS TABLE
-- ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS preauth_documents (
    id              SERIAL PRIMARY KEY,
    preauth_id      INT             NOT NULL REFERENCES preauths(id) ON DELETE CASCADE,
    field_key       VARCHAR(100)    NOT NULL,
    field_group     VARCHAR(50)     NOT NULL,
    text_content    TEXT,
    filename        VARCHAR(255),
    file_path       VARCHAR(500),
    content_base64  TEXT,
    sort_order      INT             NOT NULL DEFAULT 0,
    uploaded_at     TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_preauth_docs_preauth ON preauth_documents(preauth_id);

-- ───────────────────────────────────────
-- 5. PREAUTH SCORE REPORTS TABLE
-- ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS preauth_score_reports (
    id                  SERIAL PRIMARY KEY,
    preauth_id          INT             NOT NULL REFERENCES preauths(id) ON DELETE CASCADE UNIQUE,
    verdict             VARCHAR(10)     NOT NULL,       -- PASS | REVIEW | FAIL
    total_score         NUMERIC(6,2)    NOT NULL,
    hard_block          BOOLEAN         NOT NULL DEFAULT false,
    hard_block_reason   TEXT,
    module_scores       JSONB           NOT NULL,       -- [{module, weight, raw_score, weighted_score}]
    all_flags           JSONB           NOT NULL,       -- [{field, severity, reason, affected_doc}]
    missing_documents   JSONB           NOT NULL,       -- [string]
    identity_mismatches JSONB           NOT NULL,       -- [string]
    recommendations     JSONB           NOT NULL,       -- [string]
    processing_time_ms  INT,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now()
);

-- ───────────────────────────────────────
-- 6. CLAIM PREAUTH MAPPINGS TABLE
-- ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS claim_preauth_mappings (
    claim_id        INT             NOT NULL REFERENCES claims(id) ON DELETE CASCADE UNIQUE,
    preauth_id      INT             NOT NULL REFERENCES preauths(id) ON DELETE CASCADE,
    PRIMARY KEY (claim_id, preauth_id)
);
