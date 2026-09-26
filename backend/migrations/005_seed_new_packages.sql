-- ═══════════════════════════════════════════════════════════════
-- PMJAY Claim Pre-Auth System — Database Schema
-- Migration 005 — Seed New HBP Packages, Documents, Weights, and Text Field Masters
-- ═══════════════════════════════════════════════════════════════

-- ───────────────────────────────────────
-- 1. SEED: NEW HBP PACKAGES
-- ───────────────────────────────────────
INSERT INTO packages (code, name, specialty, checklist_notes) VALUES
('MG045A', 'AKI / Renal Failure (Medical Management)', 'Nephrology', 'USG KUB to rule out CKD. Trend serial creatinine.'),
('MG038A', 'Congestive Heart Failure (CHF)', 'Cardiology', '2D-Echo must state LVEF%. ECG and Chest X-ray required.'),
('MG081B', 'CAD (Coronary Artery Disease) - Medical Mgmt', 'Cardiology', 'Troponin quantitative and lipid profile required.'),
('MC011A', 'PTCA (Stenting), inclusive of angiogram', 'Cardiology', 'Angio/PTCA CD/DICOM and Pre/Post CAG report required.'),
('SN023A', 'Aneurysm Clipping including DSA or CTA', 'Neurosurgery', 'CT Brain pre/post and CTA/DSA morphology required.'),
('MG072D', 'Chronic Haemodialysis', 'Nephrology', 'USG KUB must show contracted kidneys/loss of CMD.'),
('MG040C', 'Respiratory Failure (Due to any cause)', 'Pulmonology', 'ABG (PaO2/PaCO2) and Chest X-ray/HRCT required.'),
('MG078D', 'Alcoholic Liver Disease', 'Gastroenterology', 'LFT (AST:ALT > 2), PT/INR, CBC, and USG Abdomen required.')
ON CONFLICT (code) DO UPDATE SET 
    name = EXCLUDED.name, 
    specialty = EXCLUDED.specialty, 
    checklist_notes = EXCLUDED.checklist_notes;


-- ───────────────────────────────────────
-- 2. SEED: PACKAGE DOCUMENTS
-- ───────────────────────────────────────

-- MG045A: AKI / Renal Failure (Medical Management)
WITH pkg AS (SELECT id FROM packages WHERE code='MG045A')
INSERT INTO package_documents (package_id, field_key, label, field_group, data_type, mandatory, sort_order) VALUES
((SELECT id FROM pkg), 'clinical_notes', 'Clinical Notes', 'text', 'string', true, 1),
((SELECT id FROM pkg), 'discharge_summary', 'Discharge Summary', 'text', 'string', true, 2),
((SELECT id FROM pkg), 'pathology_creatinine_bun', 'Serum Creatinine & BUN (serial/trend)', 'pathology', 'array', true, 3),
((SELECT id FROM pkg), 'pathology_electrolytes', 'Serum Electrolytes (Potassium)', 'pathology', 'array', true, 4),
((SELECT id FROM pkg), 'pathology_urine_routine', 'Urine Routine & Microscopic', 'pathology', 'array', true, 5),
((SELECT id FROM pkg), 'radiology_usg_kub', 'USG KUB (to rule out obstruction/CKD)', 'radiology', 'array', true, 6),
((SELECT id FROM pkg), 'pathology_abg', 'ABG (Metabolic Acidosis) [Advanced]', 'pathology', 'array', false, 7),
((SELECT id FROM pkg), 'pathology_upcr', 'Urine Protein/Creatinine Ratio (UPCR) [Advanced]', 'pathology', 'array', false, 8),
((SELECT id FROM pkg), 'pathology_calcium_phos', 'Serum Calcium & Phosphorus [Advanced]', 'pathology', 'array', false, 9),
((SELECT id FROM pkg), 'radiology_renal_doppler', 'Renal Color Doppler [Advanced]', 'radiology', 'array', false, 10)
ON CONFLICT (package_id, field_key) DO NOTHING;

-- MG038A: Congestive Heart Failure (CHF)
WITH pkg AS (SELECT id FROM packages WHERE code='MG038A')
INSERT INTO package_documents (package_id, field_key, label, field_group, data_type, mandatory, sort_order) VALUES
((SELECT id FROM pkg), 'clinical_notes', 'Clinical Notes', 'text', 'string', true, 1),
((SELECT id FROM pkg), 'discharge_summary', 'Discharge Summary', 'text', 'string', true, 2),
((SELECT id FROM pkg), 'pathology_bnp', 'NT-proBNP or BNP', 'pathology', 'array', true, 3),
((SELECT id FROM pkg), 'pathology_troponin', 'Cardiac Biomarkers (Trop-I/T)', 'pathology', 'array', true, 4),
((SELECT id FROM pkg), 'pathology_kft', 'Renal Function Test (KFT)', 'pathology', 'array', true, 5),
((SELECT id FROM pkg), 'radiology_echo', '2D-Echocardiography (Must state LVEF%)', 'radiology', 'array', true, 6),
((SELECT id FROM pkg), 'radiology_cxr', 'Chest X-Ray (PA View)', 'radiology', 'array', true, 7),
((SELECT id FROM pkg), 'radiology_ecg', '12-Lead ECG', 'radiology', 'array', true, 8),
((SELECT id FROM pkg), 'pathology_lactate', 'Serum Lactate [Advanced]', 'pathology', 'array', false, 9),
((SELECT id FROM pkg), 'pathology_crp_pct', 'Procalcitonin or CRP [Advanced]', 'pathology', 'array', false, 10),
((SELECT id FROM pkg), 'radiology_usg_abdomen', 'USG Abdomen Whole [Advanced]', 'radiology', 'array', false, 11)
ON CONFLICT (package_id, field_key) DO NOTHING;

-- MG081B: CAD (Coronary Artery Disease) - Medical Mgmt
WITH pkg AS (SELECT id FROM packages WHERE code='MG081B')
INSERT INTO package_documents (package_id, field_key, label, field_group, data_type, mandatory, sort_order) VALUES
((SELECT id FROM pkg), 'clinical_notes', 'Clinical Notes', 'text', 'string', true, 1),
((SELECT id FROM pkg), 'discharge_summary', 'Discharge Summary', 'text', 'string', true, 2),
((SELECT id FROM pkg), 'pathology_troponin', 'Quantitative Troponin-I/T', 'pathology', 'array', true, 3),
((SELECT id FROM pkg), 'pathology_lipid_profile', 'Lipid Profile', 'pathology', 'array', true, 4),
((SELECT id FROM pkg), 'radiology_ecg', '12-Lead ECG', 'radiology', 'array', true, 5),
((SELECT id FROM pkg), 'radiology_echo', '2D-Echocardiography (for RWMA)', 'radiology', 'array', true, 6),
((SELECT id FROM pkg), 'pathology_fbs_hba1c', 'HbA1c & Fasting Blood Sugar (FBS) [Advanced]', 'pathology', 'array', false, 7),
((SELECT id FROM pkg), 'pathology_cpk_mb', 'CPK-MB [Advanced]', 'pathology', 'array', false, 8),
((SELECT id FROM pkg), 'radiology_tmt_stress_echo', 'TMT or Stress Echo [Advanced]', 'radiology', 'array', false, 9)
ON CONFLICT (package_id, field_key) DO NOTHING;

-- MC011A: PTCA (Stenting), inclusive of angiogram
WITH pkg AS (SELECT id FROM packages WHERE code='MC011A')
INSERT INTO package_documents (package_id, field_key, label, field_group, data_type, mandatory, sort_order) VALUES
((SELECT id FROM pkg), 'clinical_notes', 'Cath Lab Notes', 'text', 'string', true, 1),
((SELECT id FROM pkg), 'discharge_summary', 'Discharge Summary', 'text', 'string', true, 2),
((SELECT id FROM pkg), 'pathology_troponin', 'Trop-I/Trop-T', 'pathology', 'array', true, 3),
((SELECT id FROM pkg), 'pathology_kft', 'KFT (Creatinine)', 'pathology', 'array', true, 4),
((SELECT id FROM pkg), 'pathology_viral_markers', 'Viral Markers (HIV, HBsAg, HCV)', 'pathology', 'array', true, 5),
((SELECT id FROM pkg), 'radiology_preop_ecg_echo', 'Pre-Op ECG & 2D-Echo', 'radiology', 'array', true, 6),
((SELECT id FROM pkg), 'radiology_cag_report', 'Coronary Angiography (CAG) Report', 'radiology', 'array', true, 7),
((SELECT id FROM pkg), 'radiology_dicom_images', 'Angio/PTCA CD/DICOM Images (Pre/Post)', 'radiology', 'array', true, 8),
((SELECT id FROM pkg), 'radiology_ffr', 'FFR (Fractional Flow Reserve < 0.80) [Advanced]', 'radiology', 'array', false, 9),
((SELECT id FROM pkg), 'radiology_post_ptca_ecg', 'Post-PTCA ECG (24 hrs later) [Advanced]', 'radiology', 'array', false, 10)
ON CONFLICT (package_id, field_key) DO NOTHING;

-- SN023A: Aneurysm Clipping including DSA or CTA
WITH pkg AS (SELECT id FROM packages WHERE code='SN023A')
INSERT INTO package_documents (package_id, field_key, label, field_group, data_type, mandatory, sort_order) VALUES
((SELECT id FROM pkg), 'clinical_notes', 'OT Notes / Clinical Notes', 'text', 'string', true, 1),
((SELECT id FROM pkg), 'discharge_summary', 'Discharge Summary', 'text', 'string', true, 2),
((SELECT id FROM pkg), 'pathology_pac_profile', 'PAC Profile (CBC, LFT, KFT, PT/INR, APTT, Blood Grouping)', 'pathology', 'array', true, 3),
((SELECT id FROM pkg), 'radiology_plain_ct_brain', 'Plain CT Brain (for SAH)', 'radiology', 'array', true, 4),
((SELECT id FROM pkg), 'radiology_cta_dsa', 'CTA or DSA (aneurysm morphology)', 'radiology', 'array', true, 5),
((SELECT id FROM pkg), 'radiology_postop_ct_brain', 'Post-Op CT Brain', 'radiology', 'array', true, 6),
((SELECT id FROM pkg), 'pathology_sodium_osmolality', 'Serum Sodium & Osmolality trends [Advanced]', 'pathology', 'array', false, 7),
((SELECT id FROM pkg), 'pathology_csf_analysis', 'CSF Analysis (Xanthochromia) [Advanced]', 'pathology', 'array', false, 8),
((SELECT id FROM pkg), 'radiology_tcd', 'Transcranial Doppler (TCD) for Vasospasm [Advanced]', 'radiology', 'array', false, 9)
ON CONFLICT (package_id, field_key) DO NOTHING;

-- MG072D: Chronic Haemodialysis
WITH pkg AS (SELECT id FROM packages WHERE code='MG072D')
INSERT INTO package_documents (package_id, field_key, label, field_group, data_type, mandatory, sort_order) VALUES
((SELECT id FROM pkg), 'clinical_notes', 'Nephrologist Notes', 'text', 'string', true, 1),
((SELECT id FROM pkg), 'discharge_summary', 'Discharge Summary', 'text', 'string', true, 2),
((SELECT id FROM pkg), 'pathology_kft_potassium', 'Serum Creatinine, Blood Urea, Potassium', 'pathology', 'array', true, 3),
((SELECT id FROM pkg), 'pathology_viral_markers', 'Viral Markers (HBsAg, Anti-HCV, HIV)', 'pathology', 'array', true, 4),
((SELECT id FROM pkg), 'pathology_cbc', 'CBC', 'pathology', 'array', true, 5),
((SELECT id FROM pkg), 'radiology_usg_kub', 'USG KUB (must show contracted kidneys/loss of CMD)', 'radiology', 'array', true, 6),
((SELECT id FROM pkg), 'pathology_pth', 'Intact PTH [Advanced]', 'pathology', 'array', false, 7),
((SELECT id FROM pkg), 'pathology_iron_profile', 'Serum Ferritin/Iron Profile [Advanced]', 'pathology', 'array', false, 8),
((SELECT id FROM pkg), 'radiology_av_fistula_doppler', 'AV Fistula Color Doppler [Advanced]', 'radiology', 'array', false, 9)
ON CONFLICT (package_id, field_key) DO NOTHING;

-- MG040C: Respiratory Failure (Due to any cause)
WITH pkg AS (SELECT id FROM packages WHERE code='MG040C')
INSERT INTO package_documents (package_id, field_key, label, field_group, data_type, mandatory, sort_order) VALUES
((SELECT id FROM pkg), 'clinical_notes', 'Clinical Notes', 'text', 'string', true, 1),
((SELECT id FROM pkg), 'discharge_summary', 'Discharge Summary', 'text', 'string', true, 2),
((SELECT id FROM pkg), 'pathology_abg', 'Arterial Blood Gas (ABG - PaO2/PaCO2)', 'pathology', 'array', true, 3),
((SELECT id FROM pkg), 'pathology_cbc', 'CBC', 'pathology', 'array', true, 4),
((SELECT id FROM pkg), 'pathology_crp_pct', 'CRP/Procalcitonin', 'pathology', 'array', true, 5),
((SELECT id FROM pkg), 'radiology_cxr_hrct', 'Chest X-Ray (PA View) or HRCT Thorax', 'radiology', 'array', true, 6),
((SELECT id FROM pkg), 'pathology_d_dimer', 'D-Dimer [Advanced]', 'pathology', 'array', false, 7),
((SELECT id FROM pkg), 'pathology_sputum_culture', 'Sputum Culture & Sensitivity [Advanced]', 'pathology', 'array', false, 8),
((SELECT id FROM pkg), 'pathology_lactate', 'Serum Lactate [Advanced]', 'pathology', 'array', false, 9),
((SELECT id FROM pkg), 'radiology_echo', '2D-Echocardiography (rule out PE/Cor Pulmonale) [Advanced]', 'radiology', 'array', false, 10)
ON CONFLICT (package_id, field_key) DO NOTHING;

-- MG078D: Alcoholic Liver Disease
WITH pkg AS (SELECT id FROM packages WHERE code='MG078D')
INSERT INTO package_documents (package_id, field_key, label, field_group, data_type, mandatory, sort_order) VALUES
((SELECT id FROM pkg), 'clinical_notes', 'Clinical Notes', 'text', 'string', true, 1),
((SELECT id FROM pkg), 'discharge_summary', 'Discharge Summary', 'text', 'string', true, 2),
((SELECT id FROM pkg), 'pathology_lft', 'LFT (AST:ALT > 2, Bilirubin, Albumin)', 'pathology', 'array', true, 3),
((SELECT id FROM pkg), 'pathology_coagulation_profile', 'Coagulation Profile (PT/INR)', 'pathology', 'array', true, 4),
((SELECT id FROM pkg), 'pathology_cbc', 'CBC', 'pathology', 'array', true, 5),
((SELECT id FROM pkg), 'radiology_usg_abdomen', 'USG Abdomen (Whole)', 'radiology', 'array', true, 6),
((SELECT id FROM pkg), 'pathology_ammonia', 'Serum Ammonia [Advanced]', 'pathology', 'array', false, 7),
((SELECT id FROM pkg), 'pathology_ascitic_fluid', 'Ascitic Fluid Analysis (SAAG > 1.1) [Advanced]', 'pathology', 'array', false, 8),
((SELECT id FROM pkg), 'radiology_ugi_endoscopy', 'UGI Endoscopy Report (for Varices) [Advanced]', 'radiology', 'array', false, 9)
ON CONFLICT (package_id, field_key) DO NOTHING;


-- ───────────────────────────────────────
-- 3. SEED: DEFAULT SCORING WEIGHTS FOR NEW PACKAGES
-- ───────────────────────────────────────
INSERT INTO scoring_weights (package_id, agent_name, weight, updated_by)
SELECT p.id, w.agent_name, w.weight, 'system_seed_new_pkg'
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
WHERE p.code IN ('MG045A', 'MG038A', 'MG081B', 'MC011A', 'SN023A', 'MG072D', 'MG040C', 'MG078D')
ON CONFLICT (package_id, agent_name) DO NOTHING;


-- ───────────────────────────────────────
-- 4. SEED: TEXT FIELD GROUPS & TEXT FIELDS MASTERS
--    This populates the newly created text field masters tables.
-- ───────────────────────────────────────

-- Create Text Field Groups
INSERT INTO text_field_groups (group_name, description) VALUES
('AKI / Renal Failure Group', 'Clinical features and vital extraction fields for AKI/Renal Failure Management'),
('Congestive Heart Failure Group', 'Critical markers and diagnostic findings for CHF Management'),
('CAD Medical Management Group', 'Laboratory results and ECG metrics for CAD Management'),
('PTCA Stenting Group', 'Operative parameters, stent details, and CAG reporting metrics'),
('Aneurysm Clipping Group', 'Surgical, radiological, and CSF trend markers for clipping procedures'),
('Chronic Haemodialysis Group', 'Renal metrics and dialysis efficacy monitoring parameters'),
('Respiratory Failure Group', 'ABG gas parameters, oxygenation, and pulmonary findings'),
('Alcoholic Liver Disease Group', 'Liver enzymes, coagulation status, and endoscopic findings')
ON CONFLICT (group_name) DO NOTHING;

-- Create Text Fields
INSERT INTO text_fields (field_name, description) VALUES
('Serum Creatinine Trend', 'Tracking of creatinine levels over days'),
('Urine Output (ml/day)', 'Daily urine volume record'),
('Potassium level (mEq/L)', 'Serum potassium laboratory value'),
('Metabolic Acidosis Status', 'Presence and severity of metabolic acidosis'),
('LVEF % (Ejection Fraction)', 'Left Ventricular Ejection Fraction percentage'),
('NT-proBNP value (pg/mL)', 'Heart failure biomarker value'),
('Troponin Level', 'Cardiac troponin level (T or I)'),
('Chest X-Ray Findings', 'Pulmonary congestion or pleural effusion details'),
('ECG Findings', 'ST-T changes, bundle branch blocks, or arrhythmias'),
('Lipid Profile', 'LDL, HDL, Total Cholesterol, and Triglycerides'),
('Stent Details (Brand, Size)', 'Stent specifications used in PTCA'),
('Coronary Angiography Findings', 'Vessel blockages and flow grading'),
('FFR Value', 'Fractional Flow Reserve measurement'),
('Plain CT Brain Findings', 'Subarachnoid hemorrhage (SAH) grade/location'),
('Aneurysm Morphology', 'Shape, size, and neck characteristics of aneurysm'),
('Post-Op CT Findings', 'Surgical cavity and post-clipping brain status'),
('Pre-dialysis KFT', 'Creatinine and BUN before dialysis session'),
('Viral Serology Status', 'HIV, HBsAg, and HCV test results'),
('USG KUB Kidney Size', 'Kidney dimensions showing contraction or CMD loss'),
('PaO2 / PaCO2 Values (ABG)', 'Oxygen and carbon dioxide partial pressures'),
('FiO2 / Oxygen Flow Rate', 'Fraction of inspired oxygen or external oxygen flow'),
('AST:ALT Ratio', 'Ratio of liver enzymes (AST vs ALT)'),
('Bilirubin & Albumin Levels', 'Liver function markers'),
('PT/INR Value', 'Coagulation profile status'),
('Ascitic Fluid Analysis (SAAG)', 'Serum-ascites albumin gradient value')
ON CONFLICT (field_name) DO NOTHING;

-- Map Text Fields to Groups
-- AKI / Renal Failure Group
WITH grp AS (SELECT id FROM text_field_groups WHERE group_name='AKI / Renal Failure Group')
INSERT INTO text_field_group_mappings (group_id, field_id, sort_order, is_mandatory) VALUES
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='Serum Creatinine Trend'), 1, true),
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='Urine Output (ml/day)'), 2, true),
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='Potassium level (mEq/L)'), 3, true),
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='Metabolic Acidosis Status'), 4, false)
ON CONFLICT (group_id, field_id) DO NOTHING;

-- Congestive Heart Failure Group
WITH grp AS (SELECT id FROM text_field_groups WHERE group_name='Congestive Heart Failure Group')
INSERT INTO text_field_group_mappings (group_id, field_id, sort_order, is_mandatory) VALUES
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='LVEF % (Ejection Fraction)'), 1, true),
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='NT-proBNP value (pg/mL)'), 2, true),
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='Troponin Level'), 3, true),
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='Chest X-Ray Findings'), 4, true)
ON CONFLICT (group_id, field_id) DO NOTHING;

-- CAD Medical Management Group
WITH grp AS (SELECT id FROM text_field_groups WHERE group_name='CAD Medical Management Group')
INSERT INTO text_field_group_mappings (group_id, field_id, sort_order, is_mandatory) VALUES
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='Troponin Level'), 1, true),
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='Lipid Profile'), 2, true),
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='ECG Findings'), 3, true)
ON CONFLICT (group_id, field_id) DO NOTHING;

-- PTCA Stenting Group
WITH grp AS (SELECT id FROM text_field_groups WHERE group_name='PTCA Stenting Group')
INSERT INTO text_field_group_mappings (group_id, field_id, sort_order, is_mandatory) VALUES
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='Stent Details (Brand, Size)'), 1, true),
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='Coronary Angiography Findings'), 2, true),
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='FFR Value'), 3, false)
ON CONFLICT (group_id, field_id) DO NOTHING;

-- Aneurysm Clipping Group
WITH grp AS (SELECT id FROM text_field_groups WHERE group_name='Aneurysm Clipping Group')
INSERT INTO text_field_group_mappings (group_id, field_id, sort_order, is_mandatory) VALUES
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='Plain CT Brain Findings'), 1, true),
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='Aneurysm Morphology'), 2, true),
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='Post-Op CT Findings'), 3, true)
ON CONFLICT (group_id, field_id) DO NOTHING;

-- Chronic Haemodialysis Group
WITH grp AS (SELECT id FROM text_field_groups WHERE group_name='Chronic Haemodialysis Group')
INSERT INTO text_field_group_mappings (group_id, field_id, sort_order, is_mandatory) VALUES
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='Pre-dialysis KFT'), 1, true),
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='Viral Serology Status'), 2, true),
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='USG KUB Kidney Size'), 3, true)
ON CONFLICT (group_id, field_id) DO NOTHING;

-- Respiratory Failure Group
WITH grp AS (SELECT id FROM text_field_groups WHERE group_name='Respiratory Failure Group')
INSERT INTO text_field_group_mappings (group_id, field_id, sort_order, is_mandatory) VALUES
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='PaO2 / PaCO2 Values (ABG)'), 1, true),
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='FiO2 / Oxygen Flow Rate'), 2, true),
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='Chest X-Ray Findings'), 3, true)
ON CONFLICT (group_id, field_id) DO NOTHING;

-- Alcoholic Liver Disease Group
WITH grp AS (SELECT id FROM text_field_groups WHERE group_name='Alcoholic Liver Disease Group')
INSERT INTO text_field_group_mappings (group_id, field_id, sort_order, is_mandatory) VALUES
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='AST:ALT Ratio'), 1, true),
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='Bilirubin & Albumin Levels'), 2, true),
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='PT/INR Value'), 3, true),
((SELECT id FROM grp), (SELECT id FROM text_fields WHERE field_name='Ascitic Fluid Analysis (SAAG)'), 4, false)
ON CONFLICT (group_id, field_id) DO NOTHING;
