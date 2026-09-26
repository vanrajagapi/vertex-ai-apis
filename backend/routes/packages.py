"""
Package Routes

GET  /api/v1/packages/                          — List all packages
GET  /api/v1/packages/{code}/form-schema        — Dynamic form schema for frontend
                                                   ?patient_id=X required
GET  /api/v1/packages/{code}/weights            — Get current scoring weights
PUT  /api/v1/packages/{code}/weights            — Update scoring weights (dynamic)
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from datetime import datetime
from typing import Optional


from core.database import get_db
from models.schemas import (
    PackageSummary, PackageFormSchema, FieldSchema, FieldGroup,
    WeightsUpdateRequest, WeightsResponse, WeightEntry,
)

router = APIRouter()


# ─────────────────────────────────────────
# List all packages
# ─────────────────────────────────────────
@router.get("", response_model=list[PackageSummary])
@router.get("/", response_model=list[PackageSummary])
async def list_packages(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT id, code, name, specialty, is_active FROM packages ORDER BY code")
    )
    return [
        PackageSummary(id=r.id, code=r.code, name=r.name, specialty=r.specialty, is_active=r.is_active)
        for r in result.fetchall()
    ]


# ─────────────────────────────────────────
# Form schema — the key API for frontend
# ─────────────────────────────────────────

@router.get("/{code}/form-schema", response_model=PackageFormSchema)
async def get_form_schema(
    code: str,
    patient_id: int = Query(..., description="patient_id returned from patient registration"),
    stage: Optional[str] = Query(None, description="Filter fields by stage: 'preauth' or 'claim'"),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the dynamic form schema for a given package + patient.

    Frontend uses this to render the claim form:
    - field_group = text | ot_notes  → render a text area
    - field_group = pathology | radiology | others → render multi-file upload

    data_type tells frontend the expected shape when submitting the claim:
    - string → send as text_value
    - array  → send as files[]
    """
    # Package
    pkg_result = await db.execute(
        text("SELECT id, code, name, specialty FROM packages WHERE code = :code AND is_active = true"),
        {"code": code},
    )
    pkg = pkg_result.fetchone()
    if not pkg:
        raise HTTPException(status_code=404, detail=f"Package {code} not found")

    # Patient
    pat_result = await db.execute(
        text("SELECT id, name, pmjay_number FROM patients WHERE id = :pid"),
        {"pid": patient_id},
    )
    pat = pat_result.fetchone()
    if not pat:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")

    # Fields
    query_str = """
        SELECT tf.field_name AS field_key, pd.label, tfg.group_name AS field_group, pd.data_type, pd.mandatory, pd.sort_order, pd.notes, pd.stage, pd.clinical_relevant
        FROM package_documents pd
        JOIN text_fields tf ON tf.id = pd.field_key_id
        JOIN text_field_groups tfg ON tfg.id = pd.field_group_id
        WHERE pd.package_id = :pkg_id
    """
    params = {"pkg_id": pkg.id}
    if stage:
        query_str += " AND pd.stage = :stage"
        params["stage"] = stage
    query_str += " ORDER BY pd.sort_order"

    fields_result = await db.execute(text(query_str), params)
    fields_grouped = {}
    for r in fields_result.fetchall():
        fg = r.field_group  # plain string from text_field_groups table
        if fg not in fields_grouped:
            fields_grouped[fg] = []
        fields_grouped[fg].append(
            FieldSchema(
                field_key=r.field_key,
                label=r.label,
                field_group=fg,
                data_type=r.data_type,
                mandatory=r.mandatory,
                sort_order=r.sort_order,
                notes=r.notes,
                stage=r.stage,
                clinical_relevant=r.clinical_relevant,
            )
        )

    return PackageFormSchema(
        package_code=pkg.code,
        package_name=pkg.name,
        specialty=pkg.specialty,
        patient_id=pat.id,
        patient_name=pat.name,
        pmjay_number=pat.pmjay_number,
        fields=fields_grouped,
    )



# ─────────────────────────────────────────
# Scoring weights — GET
# ─────────────────────────────────────────

@router.get("/{code}/weights", response_model=WeightsResponse)
async def get_weights(code: str, db: AsyncSession = Depends(get_db)):
    pkg = await _get_package_or_404(code, db)
    result = await db.execute(
        text("""
            SELECT agent_name, weight, updated_at
            FROM scoring_weights WHERE package_id = :pid
            ORDER BY weight DESC
        """),
        {"pid": pkg["id"]},
    )
    rows = result.fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="No weights found for this package")

    return WeightsResponse(
        package_code=code,
        weights=[WeightEntry(agent_name=r.agent_name, weight=float(r.weight)) for r in rows],
        updated_at=rows[0].updated_at.isoformat(),
    )


# ─────────────────────────────────────────
# Scoring weights — UPDATE (dynamic)
# ─────────────────────────────────────────

@router.put("/{code}/weights", response_model=WeightsResponse)
async def update_weights(
    code: str,
    body: WeightsUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Update scoring weights for a package.
    Weights must sum to 1.0.
    Any agent not in the list keeps its existing weight — partial update allowed
    as long as the full set still sums to 1.0.
    """
    pkg = await _get_package_or_404(code, db)

    for entry in body.weights:
        await db.execute(
            text("""
                INSERT INTO scoring_weights (package_id, agent_name, weight, updated_at, updated_by)
                VALUES (:pid, :agent, :weight, now(), :by)
                ON CONFLICT (package_id, agent_name)
                DO UPDATE SET weight = :weight, updated_at = now(), updated_by = :by
            """),
            {
                "pid":    pkg["id"],
                "agent":  entry.agent_name,
                "weight": entry.weight,
                "by":     body.updated_by or "api",
            },
        )

    return await get_weights(code, db)


# ─────────────────────────────────────────
# Internal helper
# ─────────────────────────────────────────

async def _get_package_or_404(code: str, db: AsyncSession) -> dict:
    result = await db.execute(
        text("SELECT id, code, name FROM packages WHERE code = :code"),
        {"code": code},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Package {code} not found")
    return {"id": row.id, "code": row.code, "name": row.name}
