"""
Pydantic schemas — request/response models for all APIs
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any, Literal
from enum import Enum
from datetime import date


# ─────────────────────────────────────────
# Enums
# ─────────────────────────────────────────

class Verdict(str, Enum):
    PASS    = "PASS"
    REVIEW  = "REVIEW"
    FAIL    = "FAIL"

class FlagSeverity(str, Enum):
    HIGH    = "HIGH"
    MEDIUM  = "MEDIUM"
    LOW     = "LOW"

class FieldGroup(str, Enum):
    TEXT      = "text"        # single string  (clinical_notes, discharge_summary, consent)
    OT_NOTES  = "ot_notes"   # single string  (OT / surgery notes)
    PATHOLOGY = "pathology"   # array of files
    RADIOLOGY = "radiology"   # array of files
    OTHERS    = "others"      # array of files

class ClaimStage(str, Enum):
    PREAUTH = "preauth"
    CLAIM   = "claim"



# ═══════════════════════════════════════════════
# PATIENT
# ═══════════════════════════════════════════════

class PatientCreate(BaseModel):
    name:         str  = Field(..., min_length=2)
    dob:          date
    age:          int  = Field(..., ge=0, le=130)
    gender:       Literal["Male", "Female", "Other"]
    pmjay_number: str  = Field(..., min_length=5, description="PMJAY Beneficiary ID")
    phone:        Optional[str] = None

class PatientResponse(BaseModel):
    patient_id:   int
    name:         str
    dob:          date
    age:          int
    gender:       str
    pmjay_number: str
    phone:        Optional[str]
    created_at:   str

    class Config:
        from_attributes = True


# ═══════════════════════════════════════════════
# PACKAGE FORM SCHEMA  (returned to frontend)
# What fields to render + their data type
# ═══════════════════════════════════════════════

class FieldSchema(BaseModel):
    field_key:   str
    label:       str
    field_group: str            # group name from text_field_groups table (e.g. "text", "pathology", or custom names)
    data_type:   Literal["string", "array"]   # string → text input, array → multi-file upload
    mandatory:   bool
    sort_order:  int
    notes:       Optional[str] = None
    stage:       Optional[ClaimStage] = None
    clinical_relevant: bool = False



class PackageFormSchema(BaseModel):
    """
    Returned by GET /packages/{code}/form-schema?patient_id=X
    Frontend uses this to render the dynamic claim form.
    """
    package_code: str
    package_name: str
    specialty:    str
    patient_id:   int
    patient_name: str
    pmjay_number: str
    fields:       Dict[str, List[FieldSchema]]  # Grouped by field_group name


# ═══════════════════════════════════════════════
# CLAIM SUBMISSION
# Frontend sends exactly what the form schema asked for
# ═══════════════════════════════════════════════

class FileItem(BaseModel):
    filename:       str
    content_base64: Optional[str] = None
    file_path:      Optional[str] = None

class ClaimDocumentInput(BaseModel):
    """
    One field from the package form schema.
    - If data_type == string  → text_value is set, files is empty
    - If data_type == array   → files is set, text_value is None
    """
    field_key:   str
    field_group: str             # group name from text_field_groups table
    text_value:  Optional[str]       = None   # for string fields
    files:       List[FileItem]      = []     # for array fields

    def data_type_is_string(self) -> bool:
        if self.files and len(self.files) > 0:
            return False
        if self.text_value is not None:
            return True
        group_lower = self.field_group.lower()
        if group_lower in ("pathology", "radiology", "others"):
            return False
        return True

class ClaimSubmitRequest(BaseModel):
    patient_id:     int
    package_code:   str
    hospital_id:    str
    admission_date: date
    discharge_date: date
    documents:      List[ClaimDocumentInput]
    preauth_id:     Optional[int] = None


    @field_validator("discharge_date")
    @classmethod
    def discharge_after_admission(cls, v, info):
        if "admission_date" in info.data and v < info.data["admission_date"]:
            raise ValueError("discharge_date must be after admission_date")
        return v


# ═══════════════════════════════════════════════
# PRE-FLIGHT CHECK
# ═══════════════════════════════════════════════

class PreflightField(BaseModel):
    field_key:  str
    label:      str
    mandatory:  bool
    provided:   bool
    status:     Literal["ok", "missing", "empty"]

class PreflightResult(BaseModel):
    ready:            bool                  # True = all mandatory fields present
    missing_mandatory: List[str]            # field labels of missing mandatory fields
    missing_optional:  List[str]
    fields:           List[PreflightField]


# ═══════════════════════════════════════════════
# SCORING
# ═══════════════════════════════════════════════

class Flag(BaseModel):
    field:        str
    severity:     FlagSeverity
    reason:       str
    affected_doc: Optional[str] = None

class AgentResult(BaseModel):
    agent_name:  str
    score:       float = Field(..., ge=0, le=100)
    passed:      bool
    flags:       List[Flag]         = []
    details:     Dict[str, Any]     = {}
    raw_output:  Optional[str]      = None

class ModuleScore(BaseModel):
    module:          str
    weight:          float
    raw_score:       float
    weighted_score:  float

class ClaimScoreReport(BaseModel):
    claim_id:           int
    claim_ref:          str
    package_code:       str
    package_name:       str
    verdict:            Verdict
    total_score:        float
    hard_block:         bool
    hard_block_reason:  Optional[str]       = None
    module_scores:      List[ModuleScore]
    all_flags:          List[Flag]
    agent_results:      List[AgentResult]
    missing_documents:  List[str]           = []
    identity_mismatches: List[str]          = []
    recommendations:    List[str]           = []
    processing_time_ms: Optional[int]       = None




# ═══════════════════════════════════════════════
# PACKAGE ADMIN
# ═══════════════════════════════════════════════

class PackageSummary(BaseModel):
    id:         int
    code:       str
    name:       str
    specialty:  str
    is_active:  bool

class PackageDocumentCreate(BaseModel):
    field_key_id: int
    label: str
    field_group_id: int
    data_type: Literal["string", "array"]
    mandatory: bool = True
    sort_order: int = 0
    notes: Optional[str] = None
    stage: ClaimStage = ClaimStage.PREAUTH
    clinical_relevant: bool = False
    billing_relevant: bool = False
    discharge_relevant: bool = False
    identity_relevant: bool = False
    lab_relevant: bool = False
    image_relevant: bool = False
    radiology_relevant: bool = False
    icp_relevant: bool = False

class PackageDocumentUpdate(BaseModel):
    field_key_id: Optional[int] = None
    label: Optional[str] = None
    field_group_id: Optional[int] = None
    data_type: Optional[Literal["string", "array"]] = None
    mandatory: Optional[bool] = None
    sort_order: Optional[int] = None
    notes: Optional[str] = None
    stage: Optional[ClaimStage] = None
    clinical_relevant: Optional[bool] = None
    billing_relevant: Optional[bool] = None
    discharge_relevant: Optional[bool] = None
    identity_relevant: Optional[bool] = None
    lab_relevant: Optional[bool] = None
    image_relevant: Optional[bool] = None
    radiology_relevant: Optional[bool] = None
    icp_relevant: Optional[bool] = None

class PackageDocumentResponse(BaseModel):
    id: int
    package_id: int
    field_key_id: int
    field_key: str
    label: str
    field_group_id: int
    field_group: str
    data_type: str
    mandatory: bool
    sort_order: int
    notes: Optional[str] = None
    stage: ClaimStage
    clinical_relevant: bool
    billing_relevant: bool
    discharge_relevant: bool
    identity_relevant: bool
    lab_relevant: bool
    image_relevant: bool
    radiology_relevant: bool
    icp_relevant: bool



class WeightEntry(BaseModel):
    agent_name: str
    weight:     float = Field(..., ge=0, le=1)

class WeightsUpdateRequest(BaseModel):
    """
    PUT /packages/{code}/weights
    Weights must sum to 1.0
    """
    weights:    List[WeightEntry]
    updated_by: Optional[str] = None

    @field_validator("weights")
    @classmethod
    def must_sum_to_one(cls, v):
        total = round(sum(w.weight for w in v), 4)
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Weights must sum to 1.0, got {total}")
        return v

class WeightsResponse(BaseModel):
    package_code: str
    weights:      List[WeightEntry]
    updated_at:   str

# ═══════════════════════════════════════════════
# AGENT PROMPTS
# ═══════════════════════════════════════════════

class AgentPromptResponse(BaseModel):
    agent_name: str
    system_prompt: str
    updated_at: str

class AgentPromptUpdate(BaseModel):
    system_prompt: str

# ═══════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════

class Token(BaseModel):
    access_token: str
    token_type: str
    role: str

class TokenData(BaseModel):
    username: Optional[str] = None

class User(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str = "reviewer"
    disabled: Optional[bool] = None

class UserInDB(User):
    hashed_password: str


# ═══════════════════════════════════════════════
# TEXT FIELD GROUPS  (Master)
# ═══════════════════════════════════════════════

class TextFieldGroupCreate(BaseModel):
    group_name:  str  = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    is_active:   bool = True

class TextFieldGroupUpdate(BaseModel):
    group_name:  Optional[str]  = None
    description: Optional[str]  = None
    is_active:   Optional[bool] = None

class TextFieldGroupResponse(BaseModel):
    id:          int
    group_name:  str
    description: Optional[str] = None
    is_active:   bool
    created_at:  str
    updated_at:  str


# ═══════════════════════════════════════════════
# TEXT FIELDS  (Master)
# ═══════════════════════════════════════════════

class TextFieldCreate(BaseModel):
    field_name:  str  = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    is_active:   bool = True

class TextFieldUpdate(BaseModel):
    field_name:  Optional[str]  = None
    description: Optional[str]  = None
    is_active:   Optional[bool] = None

class TextFieldResponse(BaseModel):
    id:          int
    field_name:  str
    description: Optional[str] = None
    is_active:   bool
    created_at:  str
    updated_at:  str


# ═══════════════════════════════════════════════
# TEXT FIELD GROUP ↔ TEXT FIELD MAPPING
# ═══════════════════════════════════════════════

class TextFieldGroupMappingCreate(BaseModel):
    field_ids:    List[int]

class TextFieldGroupMappingResponse(BaseModel):
    id:           int
    group_id:     int
    field_id:     int
    field_name:   str            # joined from text_fields
    created_at:   str

class TextFieldGroupDetailResponse(BaseModel):
    """Full group detail with all mapped fields."""
    id:          int
    group_name:  str
    description: Optional[str] = None
    is_active:   bool
    created_at:  str
    updated_at:  str
    fields:      List[TextFieldGroupMappingResponse] = []


# ═══════════════════════════════════════════════
# PRE-AUTHORIZATION (PREAUTH) SUBMISSION & SCORING
# ═══════════════════════════════════════════════

class PreauthDocumentInput(BaseModel):
    field_key:   str
    field_group: str
    text_value:  Optional[str]       = None
    files:       List[FileItem]      = []

    def data_type_is_string(self) -> bool:
        if self.files and len(self.files) > 0:
            return False
        if self.text_value is not None:
            return True
        group_lower = self.field_group.lower()
        if group_lower in ("pathology", "radiology", "others"):
            return False
        return True

class PreauthSubmitRequest(BaseModel):
    patient_id:     int
    package_code:   str
    hospital_id:    str
    admission_date: date
    documents:      List[PreauthDocumentInput]

class PreauthScoreReport(BaseModel):
    preauth_id:         int
    preauth_ref:        str
    package_code:       str
    package_name:       str
    verdict:            Verdict
    total_score:        float
    hard_block:         bool
    hard_block_reason:  Optional[str]       = None
    module_scores:      List[ModuleScore]
    all_flags:          List[Flag]
    agent_results:      List[AgentResult]
    missing_documents:  List[str]           = []
    identity_mismatches: List[str]          = []
    recommendations:    List[str]           = []
    processing_time_ms: Optional[int]       = None

