"""
PMJAY Package Database
Static definitions for PoC — move to PostgreSQL in Phase 2
"""

from models.schemas import PMJAYPackage, RequiredDocument, DocumentType

PMJAY_PACKAGES: dict[str, PMJAYPackage] = {
    "P19001": PMJAYPackage(
        code="P19001",
        name="Cataract Surgery",
        specialty="Ophthalmology",
        required_documents=[
            RequiredDocument(doc_type=DocumentType.CONSENT_FORM,     label="Consent Form",          mandatory=True),
            RequiredDocument(doc_type=DocumentType.CLINICAL_NOTES,   label="Surgery Notes",         mandatory=True),
            RequiredDocument(doc_type=DocumentType.LAB_REPORT,       label="Pre-Op Labs",           mandatory=True),
            RequiredDocument(doc_type=DocumentType.SURGERY_PHOTO,    label="Post-Op Photo",         mandatory=True),
            RequiredDocument(doc_type=DocumentType.DISCHARGE_SUMMARY,label="Discharge Summary",     mandatory=True),
        ],
        checklist_notes="Post-op photo must clearly show operated eye. Pre-op VA required."
    ),

    "P08012": PMJAYPackage(
        code="P08012",
        name="Knee Replacement (TKR)",
        specialty="Orthopaedics",
        required_documents=[
            RequiredDocument(doc_type=DocumentType.RADIOLOGY_REPORT, label="Pre-Op X-Ray",          mandatory=True),
            RequiredDocument(doc_type=DocumentType.RADIOLOGY_REPORT, label="Post-Op X-Ray",         mandatory=True),
            RequiredDocument(doc_type=DocumentType.CLINICAL_NOTES,   label="Surgery Notes",         mandatory=True),
            RequiredDocument(doc_type=DocumentType.OTHER,            label="Implant Invoice",       mandatory=True),
            RequiredDocument(doc_type=DocumentType.LAB_REPORT,       label="Pre-Op Labs",           mandatory=True),
            RequiredDocument(doc_type=DocumentType.DISCHARGE_SUMMARY,label="Discharge Summary",     mandatory=True),
        ],
        checklist_notes="Implant invoice must include brand, lot number, and cost."
    ),

    "P16003": PMJAYPackage(
        code="P16003",
        name="Coronary Angioplasty (PTCA)",
        specialty="Cardiology",
        required_documents=[
            RequiredDocument(doc_type=DocumentType.OTHER,            label="ECG Report",            mandatory=True),
            RequiredDocument(doc_type=DocumentType.OTHER,            label="Angiography Report",    mandatory=True),
            RequiredDocument(doc_type=DocumentType.OTHER,            label="Echocardiography",      mandatory=True),
            RequiredDocument(doc_type=DocumentType.CLINICAL_NOTES,   label="Cath Lab Notes",        mandatory=True),
            RequiredDocument(doc_type=DocumentType.DISCHARGE_SUMMARY,label="Discharge Summary",     mandatory=True),
            RequiredDocument(doc_type=DocumentType.LAB_REPORT,       label="Cardiac Enzymes",       mandatory=False),
        ],
        checklist_notes="Stent details (brand, size) must appear in cath lab notes."
    ),

    "P07002": PMJAYPackage(
        code="P07002",
        name="Appendectomy",
        specialty="General Surgery",
        required_documents=[
            RequiredDocument(doc_type=DocumentType.RADIOLOGY_REPORT, label="USG Abdomen",           mandatory=True),
            RequiredDocument(doc_type=DocumentType.CLINICAL_NOTES,   label="Surgery Notes",         mandatory=True),
            RequiredDocument(doc_type=DocumentType.OTHER,            label="Histopathology Report", mandatory=True),
            RequiredDocument(doc_type=DocumentType.LAB_REPORT,       label="Pre-Op Labs",           mandatory=True),
            RequiredDocument(doc_type=DocumentType.DISCHARGE_SUMMARY,label="Discharge Summary",     mandatory=True),
        ],
    ),

    "P03001": PMJAYPackage(
        code="P03001",
        name="Normal Delivery / C-Section",
        specialty="Obstetrics & Gynaecology",
        required_documents=[
            RequiredDocument(doc_type=DocumentType.OTHER,            label="ANC Records",           mandatory=True),
            RequiredDocument(doc_type=DocumentType.CLINICAL_NOTES,   label="Delivery Notes",        mandatory=True),
            RequiredDocument(doc_type=DocumentType.OTHER,            label="Newborn Record",        mandatory=True),
            RequiredDocument(doc_type=DocumentType.LAB_REPORT,       label="Blood Group Report",    mandatory=True),
            RequiredDocument(doc_type=DocumentType.DISCHARGE_SUMMARY,label="Discharge Summary",     mandatory=True),
        ],
    ),

    "P14001": PMJAYPackage(
        code="P14001",
        name="Dialysis (per session)",
        specialty="Nephrology",
        required_documents=[
            RequiredDocument(doc_type=DocumentType.CLINICAL_NOTES,   label="Nephrologist Notes",    mandatory=True),
            RequiredDocument(doc_type=DocumentType.LAB_REPORT,       label="Creatinine Report",     mandatory=True),
            RequiredDocument(doc_type=DocumentType.LAB_REPORT,       label="Urea Report",           mandatory=True),
        ],
        checklist_notes="Both creatinine and urea values must be present with date."
    ),

    "P13002": PMJAYPackage(
        code="P13002",
        name="Chemotherapy Cycle",
        specialty="Oncology",
        required_documents=[
            RequiredDocument(doc_type=DocumentType.CLINICAL_NOTES,   label="Oncology Notes",        mandatory=True),
            RequiredDocument(doc_type=DocumentType.OTHER,            label="Biopsy / HPE Report",   mandatory=True),
            RequiredDocument(doc_type=DocumentType.LAB_REPORT,       label="CBC Report",            mandatory=True),
            RequiredDocument(doc_type=DocumentType.OTHER,            label="Chemotherapy Protocol", mandatory=True),
            RequiredDocument(doc_type=DocumentType.DISCHARGE_SUMMARY,label="Discharge Summary",     mandatory=False),
        ],
    ),

    "P08007": PMJAYPackage(
        code="P08007",
        name="Hip Fracture Fixation",
        specialty="Orthopaedics",
        required_documents=[
            RequiredDocument(doc_type=DocumentType.RADIOLOGY_REPORT, label="Pre-Op X-Ray",          mandatory=True),
            RequiredDocument(doc_type=DocumentType.RADIOLOGY_REPORT, label="Post-Op X-Ray",         mandatory=True),
            RequiredDocument(doc_type=DocumentType.CLINICAL_NOTES,   label="Surgery Notes",         mandatory=True),
            RequiredDocument(doc_type=DocumentType.OTHER,            label="Implant Details",       mandatory=True),
            RequiredDocument(doc_type=DocumentType.LAB_REPORT,       label="Pre-Op Labs",           mandatory=True),
            RequiredDocument(doc_type=DocumentType.DISCHARGE_SUMMARY,label="Discharge Summary",     mandatory=True),
        ],
    ),
}


def get_package(code: str) -> PMJAYPackage | None:
    return PMJAY_PACKAGES.get(code)

def list_packages() -> list[PMJAYPackage]:
    return list(PMJAY_PACKAGES.values())
