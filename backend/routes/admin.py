from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import List, Optional
from pydantic import BaseModel

from core.database import get_db
from core.auth import get_current_admin_user
from core.security import get_password_hash
from models.schemas import (
    User, WeightsUpdateRequest, PackageSummary,
    PackageDocumentCreate, PackageDocumentUpdate, PackageDocumentResponse,
    WeightsResponse, AgentPromptResponse, AgentPromptUpdate,
    TextFieldGroupCreate, TextFieldGroupUpdate, TextFieldGroupResponse, TextFieldGroupDetailResponse,
    TextFieldCreate, TextFieldUpdate, TextFieldResponse,
    TextFieldGroupMappingCreate, TextFieldGroupMappingResponse,
)

router = APIRouter()

class UserCreate(BaseModel):
    username: str
    email: str
    full_name: str
    password: str
    role: str = "reviewer"

class PackageCreate(BaseModel):
    code: str
    name: str
    specialty: str
    is_active: bool = True

class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    disabled: Optional[bool] = None

class PackageUpdate(BaseModel):
    name: Optional[str] = None
    specialty: Optional[str] = None
    is_active: Optional[bool] = None

@router.post("/users", response_model=User)
async def create_user(user: UserCreate, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    hashed_pw = get_password_hash(user.password)
    try:
        await db.execute(
            text("""
                INSERT INTO users (username, email, full_name, hashed_password, role)
                VALUES (:u, :e, :f, :h, :r)
            """),
            {"u": user.username, "e": user.email, "f": user.full_name, "h": hashed_pw, "r": user.role}
        )
        return User(username=user.username, email=user.email, full_name=user.full_name)
    except Exception as e:
        raise HTTPException(status_code=400, detail="Username or email already exists")

@router.post("/packages")
async def create_package(pkg: PackageCreate, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    try:
        await db.execute(
            text("""
                INSERT INTO packages (code, name, specialty, is_active)
                VALUES (:c, :n, :s, :a)
            """),
            {"c": pkg.code, "n": pkg.name, "s": pkg.specialty, "a": pkg.is_active}
        )
        return {"message": "Package created successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail="Package code already exists")

@router.put("/packages/{code}/weights")
async def update_package_weights(code: str, payload: WeightsUpdateRequest, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    pkg_result = await db.execute(text("SELECT id FROM packages WHERE code = :c"), {"c": code})
    pkg_row = pkg_result.fetchone()
    if not pkg_row:
        raise HTTPException(status_code=404, detail="Package not found")
    package_id = pkg_row.id

    # Simple clear and re-insert approach
    await db.execute(text("DELETE FROM scoring_weights WHERE package_id = :pid"), {"pid": package_id})
    for w in payload.weights:
        await db.execute(
            text("""
                INSERT INTO scoring_weights (package_id, agent_name, weight, updated_by)
                VALUES (:pid, :a, :w, :ub)
            """),
            {"pid": package_id, "a": w.agent_name, "w": w.weight, "ub": payload.updated_by or admin.username}
        )
    return {"message": "Weights updated successfully"}

@router.get("/packages/{code}/weights", response_model=WeightsResponse)
async def get_package_weights(code: str, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    pkg_result = await db.execute(text("SELECT id FROM packages WHERE code = :c"), {"c": code})
    pkg_row = pkg_result.fetchone()
    if not pkg_row:
        raise HTTPException(status_code=404, detail="Package not found")
    package_id = pkg_row.id

    result = await db.execute(
        text("SELECT agent_name, weight, updated_at FROM scoring_weights WHERE package_id = :pid"),
        {"pid": package_id}
    )
    rows = result.fetchall()
    weights = [{"agent_name": row.agent_name, "weight": float(row.weight)} for row in rows]
    updated_at = str(rows[0].updated_at) if rows else None
    
    return WeightsResponse(package_code=code, weights=weights, updated_at=updated_at or "")

@router.get("/packages/{code}/documents", response_model=List[PackageDocumentResponse])
async def get_package_documents(code: str, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    pkg_result = await db.execute(text("SELECT id FROM packages WHERE code = :c"), {"c": code})
    pkg_row = pkg_result.fetchone()
    if not pkg_row:
        raise HTTPException(status_code=404, detail="Package not found")
        
    result = await db.execute(
        text("""
            SELECT pd.id, pd.package_id, pd.field_key_id, tf.field_name AS field_key, pd.label, pd.field_group_id, tfg.group_name AS field_group, pd.data_type, pd.mandatory, pd.sort_order, pd.notes, pd.stage, pd.clinical_relevant, pd.billing_relevant, pd.discharge_relevant, pd.identity_relevant, pd.lab_relevant, pd.image_relevant, pd.radiology_relevant, pd.icp_relevant
            FROM package_documents pd
            JOIN text_fields tf ON tf.id = pd.field_key_id
            JOIN text_field_groups tfg ON tfg.id = pd.field_group_id
            WHERE pd.package_id = :pid
            ORDER BY pd.sort_order
        """),
        {"pid": pkg_row.id}
    )
    docs = []
    for row in result.fetchall():
        docs.append(PackageDocumentResponse(
            id=row.id,
            package_id=row.package_id,
            field_key_id=row.field_key_id,
            field_key=row.field_key,
            label=row.label,
            field_group_id=row.field_group_id,
            field_group=row.field_group,
            data_type=row.data_type,
            mandatory=row.mandatory,
            sort_order=row.sort_order,
            notes=row.notes,
            stage=row.stage,
            clinical_relevant=row.clinical_relevant,
            billing_relevant=row.billing_relevant,
            discharge_relevant=row.discharge_relevant,
            identity_relevant=row.identity_relevant,
            lab_relevant=row.lab_relevant,
            image_relevant=row.image_relevant,
            radiology_relevant=row.radiology_relevant,
            icp_relevant=row.icp_relevant
        ))
    return docs

@router.post("/packages/{code}/documents", response_model=PackageDocumentResponse)
async def create_package_document(code: str, payload: PackageDocumentCreate, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    pkg_result = await db.execute(text("SELECT id FROM packages WHERE code = :c"), {"c": code})
    pkg_row = pkg_result.fetchone()
    if not pkg_row:
        raise HTTPException(status_code=404, detail="Package not found")
        
    # Verify field_key_id exists
    fk_res = await db.execute(
        text("SELECT field_name FROM text_fields WHERE id = :fid"), {"fid": payload.field_key_id}
    )
    fk_row = fk_res.fetchone()
    if not fk_row:
        raise HTTPException(status_code=400, detail="Provided field_key_id does not exist")
    fk_str = fk_row.field_name

    # Verify field_group_id exists
    fg_res = await db.execute(
        text("SELECT group_name FROM text_field_groups WHERE id = :gid"), {"gid": payload.field_group_id}
    )
    fg_row = fg_res.fetchone()
    if not fg_row:
        raise HTTPException(status_code=400, detail="Provided field_group_id does not exist")
    fg_str = fg_row.group_name

    try:
        result = await db.execute(
            text("""
                INSERT INTO package_documents (package_id, field_key_id, label, field_group_id, data_type, mandatory, sort_order, notes, stage, clinical_relevant, billing_relevant, discharge_relevant, identity_relevant, lab_relevant, image_relevant, radiology_relevant, icp_relevant)
                VALUES (:pid, :fkid, :l, :fgid, :dt, :m, :so, :n, :stg, :cr, :br, :dr, :ir, :lr, :imr, :rr, :icpr)
                RETURNING id, package_id, label, data_type, mandatory, sort_order, notes, stage, clinical_relevant, billing_relevant, discharge_relevant, identity_relevant, lab_relevant, image_relevant, radiology_relevant, icp_relevant
            """),
            {
                "pid": pkg_row.id,
                "fkid": payload.field_key_id,
                "l": payload.label,
                "fgid": payload.field_group_id,
                "dt": payload.data_type,
                "m": payload.mandatory,
                "so": payload.sort_order,
                "n": payload.notes,
                "stg": payload.stage.value if hasattr(payload.stage, 'value') else payload.stage,
                "cr": payload.clinical_relevant,
                "br": payload.billing_relevant,
                "dr": payload.discharge_relevant,
                "ir": payload.identity_relevant,
                "lr": payload.lab_relevant,
                "imr": payload.image_relevant,
                "rr": payload.radiology_relevant,
                "icpr": payload.icp_relevant
            }
        )
        row = result.fetchone()
        return PackageDocumentResponse(
            id=row.id,
            package_id=row.package_id,
            field_key_id=payload.field_key_id,
            field_key=fk_str,
            label=row.label,
            field_group_id=payload.field_group_id,
            field_group=fg_str,
            data_type=row.data_type,
            mandatory=row.mandatory,
            sort_order=row.sort_order,
            notes=row.notes,
            stage=row.stage,
            clinical_relevant=row.clinical_relevant,
            billing_relevant=row.billing_relevant,
            discharge_relevant=row.discharge_relevant,
            identity_relevant=row.identity_relevant,
            lab_relevant=row.lab_relevant,
            image_relevant=row.image_relevant,
            radiology_relevant=row.radiology_relevant,
            icp_relevant=row.icp_relevant
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail="Document field_key_id might already exist for this package")

@router.put("/packages/{code}/documents/{doc_id}", response_model=PackageDocumentResponse)
async def update_package_document(code: str, doc_id: int, payload: PackageDocumentUpdate, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    updates = []
    params = {"did": doc_id}
    
    if payload.field_key_id is not None:
        # Verify field_key_id exists
        fk_res = await db.execute(
            text("SELECT id FROM text_fields WHERE id = :fid"), {"fid": payload.field_key_id}
        )
        if not fk_res.fetchone():
            raise HTTPException(status_code=400, detail="Provided field_key_id does not exist")
        updates.append("field_key_id = :fkid")
        params["fkid"] = payload.field_key_id

    if payload.label is not None:
        updates.append("label = :l")
        params["l"] = payload.label

    if payload.field_group_id is not None:
        # Verify field_group_id exists
        fg_res = await db.execute(
            text("SELECT id FROM text_field_groups WHERE id = :gid"), {"gid": payload.field_group_id}
        )
        if not fg_res.fetchone():
            raise HTTPException(status_code=400, detail="Provided field_group_id does not exist")
        updates.append("field_group_id = :fgid")
        params["fgid"] = payload.field_group_id

    if payload.data_type is not None:
        updates.append("data_type = :dt")
        params["dt"] = payload.data_type
    if payload.mandatory is not None:
        updates.append("mandatory = :m")
        params["m"] = payload.mandatory
    if payload.sort_order is not None:
        updates.append("sort_order = :so")
        params["so"] = payload.sort_order
    if payload.notes is not None:
        updates.append("notes = :n")
        params["n"] = payload.notes
    if payload.stage is not None:
        updates.append("stage = :stg")
        params["stg"] = payload.stage.value if hasattr(payload.stage, 'value') else payload.stage
    if payload.clinical_relevant is not None:
        updates.append("clinical_relevant = :cr")
        params["cr"] = payload.clinical_relevant
    if payload.billing_relevant is not None:
        updates.append("billing_relevant = :br")
        params["br"] = payload.billing_relevant
    if payload.discharge_relevant is not None:
        updates.append("discharge_relevant = :dr")
        params["dr"] = payload.discharge_relevant
    if payload.identity_relevant is not None:
        updates.append("identity_relevant = :ir")
        params["ir"] = payload.identity_relevant
    if payload.lab_relevant is not None:
        updates.append("lab_relevant = :lr")
        params["lr"] = payload.lab_relevant
    if payload.image_relevant is not None:
        updates.append("image_relevant = :imr")
        params["imr"] = payload.image_relevant
    if payload.radiology_relevant is not None:
        updates.append("radiology_relevant = :rr")
        params["rr"] = payload.radiology_relevant
    if payload.icp_relevant is not None:
        updates.append("icp_relevant = :icpr")
        params["icpr"] = payload.icp_relevant
        
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
        
    query = f"UPDATE package_documents SET {', '.join(updates)} WHERE id = :did RETURNING id, package_id, field_key_id, label, field_group_id, data_type, mandatory, sort_order, notes, stage, clinical_relevant, billing_relevant, discharge_relevant, identity_relevant, lab_relevant, image_relevant, radiology_relevant, icp_relevant"
    try:
        result = await db.execute(text(query), params)
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Document not found")
            
        # Get final field_key and field_group names via join
        res_full = await db.execute(
            text("""
                SELECT tf.field_name AS field_key, tfg.group_name AS field_group, pd.stage, pd.clinical_relevant, pd.billing_relevant, pd.discharge_relevant, pd.identity_relevant, pd.lab_relevant, pd.image_relevant, pd.radiology_relevant, pd.icp_relevant
                FROM package_documents pd
                JOIN text_fields tf ON tf.id = pd.field_key_id
                JOIN text_field_groups tfg ON tfg.id = pd.field_group_id
                WHERE pd.id = :did
            """),
            {"did": doc_id}
        )
        full_row = res_full.fetchone()
        
        return PackageDocumentResponse(
            id=row.id,
            package_id=row.package_id,
            field_key_id=row.field_key_id,
            field_key=full_row.field_key,
            label=row.label,
            field_group_id=row.field_group_id,
            field_group=full_row.field_group,
            data_type=row.data_type,
            mandatory=row.mandatory,
            sort_order=row.sort_order,
            notes=row.notes,
            stage=full_row.stage,
            clinical_relevant=full_row.clinical_relevant,
            billing_relevant=full_row.billing_relevant,
            discharge_relevant=full_row.discharge_relevant,
            identity_relevant=full_row.identity_relevant,
            lab_relevant=full_row.lab_relevant,
            image_relevant=full_row.image_relevant,
            radiology_relevant=full_row.radiology_relevant,
            icp_relevant=full_row.icp_relevant
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail="Update failed, possibly duplicate field_key_id")


@router.delete("/packages/{code}/documents/{doc_id}")
async def delete_package_document(code: str, doc_id: int, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    result = await db.execute(text("DELETE FROM package_documents WHERE id = :did RETURNING id"), {"did": doc_id})
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Document not found")
    return {"message": "Document deleted successfully"}

@router.get("/agents/scoring-names", response_model=List[str])
async def get_scoring_agent_names(admin: User = Depends(get_current_admin_user)):
    """Returns the list of agent names that are eligible for dynamic scoring weights."""
    return [
        "IdentityValidatorAgent",
        "PackageComplianceAgent",
        "ClinicalRelevanceAgent",
        "LabAnalyzerAgent",
        "ImageValidatorAgent",
        "RadiologyValidatorAgent",
        "BillingAnalyserAgent",
        "DischargeSummaryAnalyserAgent"
    ]

@router.get("/agents/prompts", response_model=List[AgentPromptResponse])
async def get_all_agent_prompts(db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    """
    Live scoring prompts. Scoring uses these first; if a prompt is empty or
    fails to render, the hardcoded default in agents/prompts.py is used.
    Edit via PUT /agents/{agent_name}/prompt and re-score to test.
    Keep JSON example braces doubled as {{ }}.
    """
    result = await db.execute(text("SELECT agent_name, system_prompt, updated_at FROM agent_prompts ORDER BY agent_name"))
    return [AgentPromptResponse(agent_name=r.agent_name, system_prompt=r.system_prompt, updated_at=str(r.updated_at)) for r in result.fetchall()]

@router.put("/agents/{agent_name}/prompt", response_model=AgentPromptResponse)
async def update_agent_prompt(agent_name: str, payload: AgentPromptUpdate, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    query = """
        UPDATE agent_prompts SET system_prompt = :prompt, updated_at = now()
        WHERE agent_name = :name RETURNING agent_name, system_prompt, updated_at
    """
    result = await db.execute(text(query), {"prompt": payload.system_prompt, "name": agent_name})
    row = result.fetchone()
    if not row:
        query = """
            INSERT INTO agent_prompts (agent_name, system_prompt) VALUES (:name, :prompt)
            RETURNING agent_name, system_prompt, updated_at
        """
        result = await db.execute(text(query), {"name": agent_name, "prompt": payload.system_prompt})
        row = result.fetchone()
    
    return AgentPromptResponse(agent_name=row.agent_name, system_prompt=row.system_prompt, updated_at=str(row.updated_at))

@router.get("/users", response_model=List[User])
async def get_users(db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    result = await db.execute(text("SELECT username, email, full_name, role, disabled FROM users ORDER BY created_at DESC"))
    users = []
    for row in result.fetchall():
        users.append(User(username=row.username, email=row.email, full_name=row.full_name, role=row.role, disabled=row.disabled))
    return users

@router.put("/users/{username}", response_model=User)
async def update_user(username: str, payload: UserUpdate, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    updates = []
    params = {"u": username}
    if payload.email is not None:
        updates.append("email = :e")
        params["e"] = payload.email
    if payload.full_name is not None:
        updates.append("full_name = :f")
        params["f"] = payload.full_name
    if payload.role is not None:
        updates.append("role = :r")
        params["r"] = payload.role
    if payload.disabled is not None:
        updates.append("disabled = :d")
        params["d"] = payload.disabled
        
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
        
    query = f"UPDATE users SET {', '.join(updates)} WHERE username = :u RETURNING username, email, full_name, role, disabled"
    result = await db.execute(text(query), params)
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
        
    return User(username=row.username, email=row.email, full_name=row.full_name, role=row.role, disabled=row.disabled)

@router.get("/packages", response_model=List[PackageSummary])
async def get_packages(db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    result = await db.execute(text("SELECT id, code, name, specialty, is_active FROM packages ORDER BY id DESC"))
    pkgs = []
    for row in result.fetchall():
        pkgs.append(PackageSummary(id=row.id, code=row.code, name=row.name, specialty=row.specialty, is_active=row.is_active))
    return pkgs

@router.put("/packages/{code}", response_model=PackageSummary)
async def update_package(code: str, payload: PackageUpdate, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    updates = []
    params = {"c": code}
    if payload.name is not None:
        updates.append("name = :n")
        params["n"] = payload.name
    if payload.specialty is not None:
        updates.append("specialty = :s")
        params["s"] = payload.specialty
    if payload.is_active is not None:
        updates.append("is_active = :a")
        params["a"] = payload.is_active
        
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
        
    query = f"UPDATE packages SET {', '.join(updates)} WHERE code = :c RETURNING id, code, name, specialty, is_active"
    result = await db.execute(text(query), params)
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Package not found")
        
    return PackageSummary(id=row.id, code=row.code, name=row.name, specialty=row.specialty, is_active=row.is_active)


@router.delete("/packages/{code}")
async def delete_package(code: str, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    # 1. Fetch package ID
    pkg_result = await db.execute(text("SELECT id FROM packages WHERE code = :c"), {"c": code})
    pkg_row = pkg_result.fetchone()
    if not pkg_row:
        raise HTTPException(status_code=404, detail="Package not found")
    
    package_id = pkg_row.id

    # 2. Check if package is used in claims
    claim_check = await db.execute(text("SELECT 1 FROM claims WHERE package_id = :pid LIMIT 1"), {"pid": package_id})
    if claim_check.fetchone():
        raise HTTPException(
            status_code=400, 
            detail="Cannot delete package because it is currently associated with one or more claims. Please deactivate it instead."
        )

    # 3. Check if package is used in preauths
    preauth_check = await db.execute(text("SELECT 1 FROM preauths WHERE package_id = :pid LIMIT 1"), {"pid": package_id})
    if preauth_check.fetchone():
        raise HTTPException(
            status_code=400, 
            detail="Cannot delete package because it is currently associated with one or more pre-authorizations. Please deactivate it instead."
        )

    # 4. Safe to delete. 
    # Delete scoring weights
    await db.execute(text("DELETE FROM scoring_weights WHERE package_id = :pid"), {"pid": package_id})
    
    # Delete package documents
    await db.execute(text("DELETE FROM package_documents WHERE package_id = :pid"), {"pid": package_id})
    
    # Delete the package
    await db.execute(text("DELETE FROM packages WHERE id = :pid"), {"pid": package_id})
    
    return {"message": f"Package {code} deleted successfully"}


# ═══════════════════════════════════════════════════════════════
# TEXT FIELD GROUPS — Master CRUD
# ═══════════════════════════════════════════════════════════════

@router.get("/text-field-groups", response_model=List[TextFieldGroupResponse])
async def list_text_field_groups(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user),
):
    result = await db.execute(
        text("SELECT id, group_name, description, is_active, created_at, updated_at FROM text_field_groups ORDER BY group_name")
    )
    return [
        TextFieldGroupResponse(
            id=r.id, group_name=r.group_name, description=r.description,
            is_active=r.is_active, created_at=str(r.created_at), updated_at=str(r.updated_at),
        )
        for r in result.fetchall()
    ]


@router.get("/text-field-groups/{group_id}", response_model=TextFieldGroupDetailResponse)
async def get_text_field_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user),
):
    """Get a single group with all its mapped text fields."""
    grp = await db.execute(
        text("SELECT id, group_name, description, is_active, created_at, updated_at FROM text_field_groups WHERE id = :gid"),
        {"gid": group_id},
    )
    row = grp.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Text field group not found")

    mappings = await db.execute(
        text("""
            SELECT m.id, m.group_id, m.field_id, f.field_name, m.created_at
            FROM text_field_group_mappings m
            JOIN text_fields f ON f.id = m.field_id
            WHERE m.group_id = :gid
            ORDER BY f.field_name
        """),
        {"gid": group_id},
    )
    fields = [
        TextFieldGroupMappingResponse(
            id=m.id, group_id=m.group_id, field_id=m.field_id,
            field_name=m.field_name, created_at=str(m.created_at),
        )
        for m in mappings.fetchall()
    ]

    return TextFieldGroupDetailResponse(
        id=row.id, group_name=row.group_name, description=row.description,
        is_active=row.is_active, created_at=str(row.created_at),
        updated_at=str(row.updated_at), fields=fields,
    )


@router.post("/text-field-groups", response_model=TextFieldGroupResponse)
async def create_text_field_group(
    payload: TextFieldGroupCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user),
):
    try:
        result = await db.execute(
            text("""
                INSERT INTO text_field_groups (group_name, description, is_active)
                VALUES (:gn, :desc, :act)
                RETURNING id, group_name, description, is_active, created_at, updated_at
            """),
            {"gn": payload.group_name, "desc": payload.description, "act": payload.is_active},
        )
        row = result.fetchone()
        return TextFieldGroupResponse(
            id=row.id, group_name=row.group_name, description=row.description,
            is_active=row.is_active, created_at=str(row.created_at), updated_at=str(row.updated_at),
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Group name already exists")


@router.put("/text-field-groups/{group_id}", response_model=TextFieldGroupResponse)
async def update_text_field_group(
    group_id: int,
    payload: TextFieldGroupUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user),
):
    updates, params = [], {"gid": group_id}
    if payload.group_name is not None:
        updates.append("group_name = :gn")
        params["gn"] = payload.group_name
    if payload.description is not None:
        updates.append("description = :desc")
        params["desc"] = payload.description
    if payload.is_active is not None:
        updates.append("is_active = :act")
        params["act"] = payload.is_active
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates.append("updated_at = now()")
    query = f"UPDATE text_field_groups SET {', '.join(updates)} WHERE id = :gid RETURNING id, group_name, description, is_active, created_at, updated_at"
    result = await db.execute(text(query), params)
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Text field group not found")
    return TextFieldGroupResponse(
        id=row.id, group_name=row.group_name, description=row.description,
        is_active=row.is_active, created_at=str(row.created_at), updated_at=str(row.updated_at),
    )


@router.delete("/text-field-groups/{group_id}")
async def delete_text_field_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user),
):
    result = await db.execute(
        text("DELETE FROM text_field_groups WHERE id = :gid RETURNING id"), {"gid": group_id}
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Text field group not found")
    return {"message": "Text field group deleted successfully"}


# ═══════════════════════════════════════════════════════════════
# TEXT FIELDS — Master CRUD
# ═══════════════════════════════════════════════════════════════

@router.get("/text-fields", response_model=List[TextFieldResponse])
async def list_text_fields(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user),
):
    result = await db.execute(
        text("SELECT id, field_name, description, is_active, created_at, updated_at FROM text_fields ORDER BY field_name")
    )
    return [
        TextFieldResponse(
            id=r.id, field_name=r.field_name, description=r.description,
            is_active=r.is_active, created_at=str(r.created_at), updated_at=str(r.updated_at),
        )
        for r in result.fetchall()
    ]


@router.get("/text-fields/{field_id}", response_model=TextFieldResponse)
async def get_text_field(
    field_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user),
):
    result = await db.execute(
        text("SELECT id, field_name, description, is_active, created_at, updated_at FROM text_fields WHERE id = :fid"),
        {"fid": field_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Text field not found")
    return TextFieldResponse(
        id=row.id, field_name=row.field_name, description=row.description,
        is_active=row.is_active, created_at=str(row.created_at), updated_at=str(row.updated_at),
    )


@router.post("/text-fields", response_model=TextFieldResponse)
async def create_text_field(
    payload: TextFieldCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user),
):
    try:
        result = await db.execute(
            text("""
                INSERT INTO text_fields (field_name, description, is_active)
                VALUES (:fn, :desc, :act)
                RETURNING id, field_name, description, is_active, created_at, updated_at
            """),
            {"fn": payload.field_name, "desc": payload.description, "act": payload.is_active},
        )
        row = result.fetchone()
        return TextFieldResponse(
            id=row.id, field_name=row.field_name, description=row.description,
            is_active=row.is_active, created_at=str(row.created_at), updated_at=str(row.updated_at),
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Field name already exists")


@router.put("/text-fields/{field_id}", response_model=TextFieldResponse)
async def update_text_field(
    field_id: int,
    payload: TextFieldUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user),
):
    updates, params = [], {"fid": field_id}
    if payload.field_name is not None:
        updates.append("field_name = :fn")
        params["fn"] = payload.field_name
    if payload.description is not None:
        updates.append("description = :desc")
        params["desc"] = payload.description
    if payload.is_active is not None:
        updates.append("is_active = :act")
        params["act"] = payload.is_active
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates.append("updated_at = now()")
    query = f"UPDATE text_fields SET {', '.join(updates)} WHERE id = :fid RETURNING id, field_name, description, is_active, created_at, updated_at"
    result = await db.execute(text(query), params)
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Text field not found")
    return TextFieldResponse(
        id=row.id, field_name=row.field_name, description=row.description,
        is_active=row.is_active, created_at=str(row.created_at), updated_at=str(row.updated_at),
    )


@router.delete("/text-fields/{field_id}")
async def delete_text_field(
    field_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user),
):
    result = await db.execute(
        text("DELETE FROM text_fields WHERE id = :fid RETURNING id"), {"fid": field_id}
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Text field not found")
    return {"message": "Text field deleted successfully"}


# ═══════════════════════════════════════════════════════════════
# TEXT FIELD GROUP ↔ TEXT FIELD MAPPINGS  (one group → many fields)
# ═══════════════════════════════════════════════════════════════

@router.get("/text-field-groups/{group_id}/mappings", response_model=List[TextFieldGroupMappingResponse])
async def list_group_mappings(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user),
):
    """List all text fields mapped to a given group."""
    result = await db.execute(
        text("""
            SELECT m.id, m.group_id, m.field_id, f.field_name, m.created_at
            FROM text_field_group_mappings m
            JOIN text_fields f ON f.id = m.field_id
            WHERE m.group_id = :gid
            ORDER BY f.field_name
        """),
        {"gid": group_id},
    )
    return [
        TextFieldGroupMappingResponse(
            id=r.id, group_id=r.group_id, field_id=r.field_id,
            field_name=r.field_name, created_at=str(r.created_at),
        )
        for r in result.fetchall()
    ]


@router.post("/text-field-groups/{group_id}/mappings", response_model=List[TextFieldGroupMappingResponse])
async def add_fields_to_group(
    group_id: int,
    payload: TextFieldGroupMappingCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user),
):
    """Map multiple text fields to a group."""
    # Verify group exists
    grp = await db.execute(text("SELECT id FROM text_field_groups WHERE id = :gid"), {"gid": group_id})
    if not grp.fetchone():
        raise HTTPException(status_code=404, detail="Text field group not found")

    inserted = []
    for fid in payload.field_ids:
        # Verify field exists
        fld = await db.execute(text("SELECT id, field_name FROM text_fields WHERE id = :fid"), {"fid": fid})
        frow = fld.fetchone()
        if not frow:
            continue

        try:
            # Insert mapping
            res = await db.execute(
                text("""
                    INSERT INTO text_field_group_mappings (group_id, field_id)
                    VALUES (:gid, :fid)
                    ON CONFLICT (group_id, field_id) DO NOTHING
                    RETURNING id, group_id, field_id, created_at
                """),
                {"gid": group_id, "fid": fid},
            )
            row = res.fetchone()
            if row:
                inserted.append(TextFieldGroupMappingResponse(
                    id=row.id, group_id=row.group_id, field_id=row.field_id,
                    field_name=frow.field_name, created_at=str(row.created_at)
                ))
            else:
                # Already exists, fetch existing row for the mapping
                exist = await db.execute(
                    text("SELECT id, created_at FROM text_field_group_mappings WHERE group_id = :gid AND field_id = :fid"),
                    {"gid": group_id, "fid": fid}
                )
                erow = exist.fetchone()
                inserted.append(TextFieldGroupMappingResponse(
                    id=erow.id, group_id=group_id, field_id=fid,
                    field_name=frow.field_name, created_at=str(erow.created_at)
                ))
        except Exception:
            pass

    return inserted


@router.delete("/text-field-groups/{group_id}/mappings/{mapping_id}")
async def remove_field_from_group(
    group_id: int,
    mapping_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user),
):
    """Remove a text field mapping from a group."""
    result = await db.execute(
        text("DELETE FROM text_field_group_mappings WHERE id = :mid AND group_id = :gid RETURNING id"),
        {"mid": mapping_id, "gid": group_id},
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Mapping not found")
    return {"message": "Field removed from group successfully"}
