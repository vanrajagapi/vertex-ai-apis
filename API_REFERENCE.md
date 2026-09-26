# PMJAY API — Integration Reference

Base URL: http://localhost:8000
All endpoints return JSON. All dates: ISO 8601 (YYYY-MM-DD).

---

## POST /api/v1/claims/score

Submit a claim for pre-authorization scoring.

### Request body

```json
{
  "claim_id": "CLM-2026-004821",
  "package_code": "P08012",
  "hospital_id": "HOSP-GJ-0042",
  "beneficiary_id": "BEN-GJ-884712",
  "patient_name": "Ramesh Patel",
  "patient_dob": "1958-03-15",
  "patient_gender": "Male",
  "admission_date": "2026-04-10",
  "discharge_date": "2026-04-15",
  "documents": [
    {
      "doc_id": "DOC-001",
      "doc_type": "clinical_notes",
      "filename": "surgery_notes.pdf",
      "content_base64": "<base64 string of PDF>"
    },
    {
      "doc_id": "DOC-002",
      "doc_type": "radiology_report",
      "filename": "preop_xray.pdf",
      "content_base64": "<base64 string>"
    },
    {
      "doc_id": "DOC-003",
      "doc_type": "surgery_photo",
      "filename": "postop_photo.jpg",
      "content_base64": "<base64 string of image>"
    }
  ]
}
```

**doc_type values:**
`clinical_notes` · `lab_report` · `radiology_report` · `surgery_photo` · `consent_form` · `discharge_summary` · `prescription` · `other`

---

### Response body

```json
{
  "claim_id": "CLM-2026-004821",
  "package_code": "P08012",
  "package_name": "Knee Replacement (TKR)",
  "verdict": "REVIEW",
  "total_score": 71.5,
  "hard_block": false,
  "hard_block_reason": null,
  "processing_time_ms": 1840,

  "module_scores": [
    { "module": "IdentityValidatorAgent",  "weight": 0.25, "raw_score": 88.0,  "weighted_score": 22.0 },
    { "module": "PackageComplianceAgent",  "weight": 0.30, "raw_score": 66.7,  "weighted_score": 20.0 },
    { "module": "DocumentExtractorAgent",  "weight": 0.20, "raw_score": 85.0,  "weighted_score": 17.0 },
    { "module": "ClinicalRelevanceAgent",  "weight": 0.15, "raw_score": 78.0,  "weighted_score": 11.7 },
    { "module": "LabAnalyzerAgent",        "weight": 0.05, "raw_score": 90.0,  "weighted_score": 4.5  },
    { "module": "ImageValidatorAgent",     "weight": 0.025,"raw_score": 100.0, "weighted_score": 2.5  },
    { "module": "RadiologyValidatorAgent", "weight": 0.025,"raw_score": 75.0,  "weighted_score": 1.9  }
  ],

  "all_flags": [
    {
      "field": "Implant Invoice",
      "severity": "HIGH",
      "reason": "Mandatory document missing: Implant Invoice",
      "affected_doc": null
    },
    {
      "field": "radiology_date",
      "severity": "HIGH",
      "reason": "Post-Op X-Ray date does not match discharge date range",
      "affected_doc": "DOC-002"
    },
    {
      "field": "clinical_notes",
      "severity": "MEDIUM",
      "reason": "Surgery notes do not mention implant brand/lot number",
      "affected_doc": "DOC-001"
    }
  ],

  "missing_documents": ["Implant Invoice"],
  "identity_mismatches": [],
  "recommendations": [
    "Upload missing documents: Implant Invoice",
    "Resolve: Post-Op X-Ray date does not match discharge date range",
    "Send to TPA with attached flag report for manual review."
  ],

  "agent_results": [
    {
      "agent_name": "PackageComplianceAgent",
      "score": 66.7,
      "passed": false,
      "flags": [...],
      "details": {
        "package_name": "Knee Replacement (TKR)",
        "missing_mandatory": ["Implant Invoice"],
        "missing_optional": [],
        "hard_block": false
      },
      "raw_output": null
    }
  ]
}
```

**Verdict values:** `PASS` (score ≥85) · `REVIEW` (60–84) · `FAIL` (<60 or hard block)
**Flag severity values:** `HIGH` · `MEDIUM` · `LOW`

---

## GET /api/v1/packages/

Returns all 8 PMJAY packages with required documents.

### Response

```json
[
  {
    "code": "P08012",
    "name": "Knee Replacement (TKR)",
    "specialty": "Orthopaedics",
    "checklist_notes": "Implant invoice must include brand, lot number, and cost.",
    "required_documents": [
      { "doc_type": "radiology_report", "label": "Pre-Op X-Ray",    "mandatory": true,  "notes": null },
      { "doc_type": "radiology_report", "label": "Post-Op X-Ray",   "mandatory": true,  "notes": null },
      { "doc_type": "clinical_notes",   "label": "Surgery Notes",   "mandatory": true,  "notes": null },
      { "doc_type": "other",            "label": "Implant Invoice",  "mandatory": true,  "notes": null },
      { "doc_type": "lab_report",       "label": "Pre-Op Labs",     "mandatory": true,  "notes": null },
      { "doc_type": "discharge_summary","label": "Discharge Summary","mandatory": true,  "notes": null }
    ]
  }
]
```

---

## GET /api/v1/packages/{code}

Single package. Returns 404 if code not found.

```
GET /api/v1/packages/P19001
```

---

## GET /api/v1/health

```json
{ "status": "ok", "service": "PMJAY Claim Pre-Auth API", "version": "1.0.0" }
```

---

## Error responses

```json
{ "detail": "Unknown package code: P99999" }   // 404
{ "detail": "<error message>" }                 // 500
```

---

## Package codes

| Code    | Name                        |
|---------|-----------------------------|
| P19001  | Cataract Surgery            |
| P08012  | Knee Replacement (TKR)      |
| P16003  | Coronary Angioplasty (PTCA) |
| P07002  | Appendectomy                |
| P03001  | Normal Delivery / C-Section |
| P14001  | Dialysis (per session)      |
| P13002  | Chemotherapy Cycle          |
| P08007  | Hip Fracture Fixation       |
