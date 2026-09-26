-- ═══════════════════════════════════════════════════════════════
-- PMJAY Claim Pre-Auth System — Database Schema
-- Migration 001 — Initial
-- ═══════════════════════════════════════════════════════════════

-- ───────────────────────────────────────
-- 1. PATIENTS
-- ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS patients (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255)    NOT NULL,
    dob             DATE            NOT NULL,
    age             INT             NOT NULL,          -- stored for fast display; derived from dob
    gender          VARCHAR(20)     NOT NULL,          -- Male | Female | Other
    pmjay_number    VARCHAR(50)     NOT NULL UNIQUE,   -- PMJAY beneficiary ID
    phone           VARCHAR(20),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_patients_pmjay ON patients(pmjay_number);


-- ───────────────────────────────────────
-- 2. PMJAY PACKAGES
-- ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS packages (
    id              SERIAL PRIMARY KEY,
    code            VARCHAR(20)     NOT NULL UNIQUE,   -- e.g. P08012
    name            VARCHAR(255)    NOT NULL,
    specialty       VARCHAR(100)    NOT NULL,
    checklist_notes TEXT,
    is_active       BOOLEAN         NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now()
);


-- ───────────────────────────────────────
-- 3. PACKAGE REQUIRED DOCUMENTS
--    Each row = one document slot required by a package.
--    field_group drives the data-type schema returned to frontend.
-- ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS package_documents (
    id              SERIAL PRIMARY KEY,
    package_id      INT             NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    field_key       VARCHAR(100)    NOT NULL,   -- machine key:  clinical_notes, ot_notes, pathology, radiology, others
    label           VARCHAR(255)    NOT NULL,   -- human label:  "Surgery Notes", "OT Notes"
    field_group     VARCHAR(50)     NOT NULL,   -- groups: text | ot_notes | pathology | radiology | others
    data_type       VARCHAR(30)     NOT NULL,   -- string | array
    mandatory       BOOLEAN         NOT NULL DEFAULT true,
    sort_order      INT             NOT NULL DEFAULT 0,
    notes           TEXT,

    UNIQUE(package_id, field_key)
);

-- field_group values:
--   text       → single string field  (clinical_notes, discharge_summary, consent, etc.)
--   ot_notes   → OT / surgery notes string
--   pathology  → array of pathology reports
--   radiology  → array of radiology reports
--   others     → array of miscellaneous supporting docs


-- ───────────────────────────────────────
-- 4. SCORING WEIGHTS  (dynamic, per package)
-- ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS scoring_weights (
    id              SERIAL PRIMARY KEY,
    package_id      INT             NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    agent_name      VARCHAR(100)    NOT NULL,
    weight          NUMERIC(5,4)    NOT NULL,           -- e.g. 0.2500
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_by      VARCHAR(100),

    UNIQUE(package_id, agent_name),
    CONSTRAINT weights_positive CHECK (weight >= 0),
    CONSTRAINT weights_max CHECK (weight <= 1)
);


-- ───────────────────────────────────────
-- 5. CLAIMS
-- ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS claims (
    id              SERIAL PRIMARY KEY,
    claim_ref       VARCHAR(50)     NOT NULL UNIQUE,    -- CLM-2026-XXXXXX
    patient_id      INT             NOT NULL REFERENCES patients(id),
    package_id      INT             NOT NULL REFERENCES packages(id),
    hospital_id     VARCHAR(50)     NOT NULL,
    admission_date  DATE            NOT NULL,
    discharge_date  DATE            NOT NULL,
    status          VARCHAR(20)     NOT NULL DEFAULT 'PENDING',  -- PENDING | SCORED | SUBMITTED
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_claims_patient  ON claims(patient_id);
CREATE INDEX IF NOT EXISTS idx_claims_package  ON claims(package_id);
CREATE INDEX IF NOT EXISTS idx_claims_ref      ON claims(claim_ref);


-- ───────────────────────────────────────
-- 6. CLAIM DOCUMENTS  (submitted by frontend)
-- ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS claim_documents (
    id              SERIAL PRIMARY KEY,
    claim_id        INT             NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    field_key       VARCHAR(100)    NOT NULL,    -- matches package_documents.field_key
    field_group     VARCHAR(50)     NOT NULL,    -- text | ot_notes | pathology | radiology | others
    -- For text fields: content stored directly
    text_content    TEXT,
    -- For array fields: each file is a separate row
    filename        VARCHAR(255),
    file_path       VARCHAR(500),               -- server storage path
    content_base64  TEXT,                       -- or base64 for PoC
    sort_order      INT             NOT NULL DEFAULT 0,
    uploaded_at     TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_claim_docs_claim ON claim_documents(claim_id);


-- ───────────────────────────────────────
-- 7. CLAIM SCORE REPORTS
-- ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS claim_score_reports (
    id                  SERIAL PRIMARY KEY,
    claim_id            INT             NOT NULL REFERENCES claims(id) ON DELETE CASCADE UNIQUE,
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
-- 8. SEED: PACKAGES
-- ───────────────────────────────────────
INSERT INTO packages (code, name, specialty, checklist_notes) VALUES
('P19001', 'Cataract Surgery',            'Ophthalmology',            'Post-op photo must clearly show operated eye. Pre-op VA required.'),
('P08012', 'Knee Replacement (TKR)',       'Orthopaedics',             'Implant invoice must include brand, lot number, and cost.'),
('P16003', 'Coronary Angioplasty (PTCA)', 'Cardiology',               'Stent details (brand, size) must appear in cath lab notes.'),
('P07002', 'Appendectomy',                'General Surgery',           NULL),
('P03001', 'Normal Delivery / C-Section', 'Obstetrics & Gynaecology', NULL),
('P14001', 'Dialysis (per session)',       'Nephrology',               'Both creatinine and urea values must be present with date.'),
('P13002', 'Chemotherapy Cycle',          'Oncology',                 NULL),
('P08007', 'Hip Fracture Fixation',       'Orthopaedics',             NULL)
ON CONFLICT (code) DO NOTHING;


-- ───────────────────────────────────────
-- 9. SEED: PACKAGE DOCUMENTS
--    field_group / data_type drives what frontend must send
-- ───────────────────────────────────────

-- P19001 Cataract Surgery
WITH pkg AS (SELECT id FROM packages WHERE code='P19001')
INSERT INTO package_documents (package_id, field_key, label, field_group, data_type, mandatory, sort_order) VALUES
((SELECT id FROM pkg), 'clinical_notes',    'Clinical Notes',     'text',      'string', true,  1),
((SELECT id FROM pkg), 'consent_form',      'Consent Form',       'text',      'string', true,  2),
((SELECT id FROM pkg), 'discharge_summary', 'Discharge Summary',  'text',      'string', true,  3),
((SELECT id FROM pkg), 'pathology',         'Pathology Reports',  'pathology', 'array',  false, 4),
((SELECT id FROM pkg), 'radiology',         'Radiology Reports',  'radiology', 'array',  false, 5),
((SELECT id FROM pkg), 'surgery_photos',    'Surgery Photos',     'others',    'array',  true,  6)
ON CONFLICT (package_id, field_key) DO NOTHING;

-- P08012 Knee Replacement (TKR)
WITH pkg AS (SELECT id FROM packages WHERE code='P08012')
INSERT INTO package_documents (package_id, field_key, label, field_group, data_type, mandatory, sort_order) VALUES
((SELECT id FROM pkg), 'clinical_notes',    'Clinical Notes',     'text',      'string', true,  1),
((SELECT id FROM pkg), 'ot_notes',          'OT Notes',           'ot_notes',  'string', true,  2),
((SELECT id FROM pkg), 'discharge_summary', 'Discharge Summary',  'text',      'string', true,  3),
((SELECT id FROM pkg), 'pathology',         'Pathology Reports',  'pathology', 'array',  false, 4),
((SELECT id FROM pkg), 'radiology',         'Radiology Reports',  'radiology', 'array',  true,  5),
((SELECT id FROM pkg), 'others',            'Other Documents',    'others',    'array',  true,  6)
ON CONFLICT (package_id, field_key) DO NOTHING;

-- P16003 Coronary Angioplasty (PTCA)
WITH pkg AS (SELECT id FROM packages WHERE code='P16003')
INSERT INTO package_documents (package_id, field_key, label, field_group, data_type, mandatory, sort_order) VALUES
((SELECT id FROM pkg), 'clinical_notes',    'Clinical Notes',     'text',      'string', true,  1),
((SELECT id FROM pkg), 'ot_notes',          'Cath Lab Notes',     'ot_notes',  'string', true,  2),
((SELECT id FROM pkg), 'discharge_summary', 'Discharge Summary',  'text',      'string', true,  3),
((SELECT id FROM pkg), 'radiology',         'Radiology Reports',  'radiology', 'array',  true,  4),
((SELECT id FROM pkg), 'pathology',         'Pathology Reports',  'pathology', 'array',  false, 5),
((SELECT id FROM pkg), 'others',            'Other Documents',    'others',    'array',  true,  6)
ON CONFLICT (package_id, field_key) DO NOTHING;

-- P07002 Appendectomy
WITH pkg AS (SELECT id FROM packages WHERE code='P07002')
INSERT INTO package_documents (package_id, field_key, label, field_group, data_type, mandatory, sort_order) VALUES
((SELECT id FROM pkg), 'clinical_notes',    'Clinical Notes',     'text',      'string', true,  1),
((SELECT id FROM pkg), 'ot_notes',          'OT Notes',           'ot_notes',  'string', true,  2),
((SELECT id FROM pkg), 'discharge_summary', 'Discharge Summary',  'text',      'string', true,  3),
((SELECT id FROM pkg), 'pathology',         'Pathology Reports',  'pathology', 'array',  true,  4),
((SELECT id FROM pkg), 'radiology',         'Radiology Reports',  'radiology', 'array',  true,  5),
((SELECT id FROM pkg), 'others',            'Other Documents',    'others',    'array',  false, 6)
ON CONFLICT (package_id, field_key) DO NOTHING;

-- P03001 Normal Delivery / C-Section
WITH pkg AS (SELECT id FROM packages WHERE code='P03001')
INSERT INTO package_documents (package_id, field_key, label, field_group, data_type, mandatory, sort_order) VALUES
((SELECT id FROM pkg), 'clinical_notes',    'Clinical Notes',     'text',      'string', true,  1),
((SELECT id FROM pkg), 'discharge_summary', 'Discharge Summary',  'text',      'string', true,  2),
((SELECT id FROM pkg), 'pathology',         'Pathology Reports',  'pathology', 'array',  false, 3),
((SELECT id FROM pkg), 'radiology',         'Radiology Reports',  'radiology', 'array',  false, 4),
((SELECT id FROM pkg), 'others',            'Other Documents',    'others',    'array',  true,  5)
ON CONFLICT (package_id, field_key) DO NOTHING;

-- P14001 Dialysis (per session)
WITH pkg AS (SELECT id FROM packages WHERE code='P14001')
INSERT INTO package_documents (package_id, field_key, label, field_group, data_type, mandatory, sort_order) VALUES
((SELECT id FROM pkg), 'clinical_notes',    'Nephrologist Notes', 'text',      'string', true,  1),
((SELECT id FROM pkg), 'discharge_summary', 'Discharge Summary',  'text',      'string', false, 2),
((SELECT id FROM pkg), 'pathology',         'Lab Reports',        'pathology', 'array',  true,  3),
((SELECT id FROM pkg), 'others',            'Other Documents',    'others',    'array',  false, 4)
ON CONFLICT (package_id, field_key) DO NOTHING;

-- P13002 Chemotherapy Cycle
WITH pkg AS (SELECT id FROM packages WHERE code='P13002')
INSERT INTO package_documents (package_id, field_key, label, field_group, data_type, mandatory, sort_order) VALUES
((SELECT id FROM pkg), 'clinical_notes',    'Oncology Notes',     'text',      'string', true,  1),
((SELECT id FROM pkg), 'discharge_summary', 'Discharge Summary',  'text',      'string', false, 2),
((SELECT id FROM pkg), 'pathology',         'Pathology Reports',  'pathology', 'array',  true,  3),
((SELECT id FROM pkg), 'radiology',         'Radiology Reports',  'radiology', 'array',  false, 4),
((SELECT id FROM pkg), 'others',            'Other Documents',    'others',    'array',  true,  5)
ON CONFLICT (package_id, field_key) DO NOTHING;

-- P08007 Hip Fracture Fixation
WITH pkg AS (SELECT id FROM packages WHERE code='P08007')
INSERT INTO package_documents (package_id, field_key, label, field_group, data_type, mandatory, sort_order) VALUES
((SELECT id FROM pkg), 'clinical_notes',    'Clinical Notes',     'text',      'string', true,  1),
((SELECT id FROM pkg), 'ot_notes',          'OT Notes',           'ot_notes',  'string', true,  2),
((SELECT id FROM pkg), 'discharge_summary', 'Discharge Summary',  'text',      'string', true,  3),
((SELECT id FROM pkg), 'pathology',         'Pathology Reports',  'pathology', 'array',  false, 4),
((SELECT id FROM pkg), 'radiology',         'Radiology Reports',  'radiology', 'array',  true,  5),
((SELECT id FROM pkg), 'others',            'Other Documents',    'others',    'array',  true,  6)
ON CONFLICT (package_id, field_key) DO NOTHING;


-- ───────────────────────────────────────
-- 10. SEED: DEFAULT SCORING WEIGHTS (per package)
-- ───────────────────────────────────────
INSERT INTO scoring_weights (package_id, agent_name, weight, updated_by)
SELECT p.id, w.agent_name, w.weight, 'system_seed'
FROM packages p
CROSS JOIN (VALUES
    ('IdentityValidatorAgent',    0.2500),
    ('PackageComplianceAgent',    0.3000),
    ('DocumentExtractorAgent',    0.2000),
    ('ClinicalRelevanceAgent',    0.1500),
    ('LabAnalyzerAgent',          0.0500),
    ('ImageValidatorAgent',       0.0250),
    ('RadiologyValidatorAgent',   0.0250)
) AS w(agent_name, weight)
ON CONFLICT (package_id, agent_name) DO NOTHING;
