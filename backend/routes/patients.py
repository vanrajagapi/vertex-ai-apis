"""
Patient Routes
POST /api/v1/patients/          — Register new patient → patient_id
GET  /api/v1/patients/{id}      — Get patient by ID
GET  /api/v1/patients/pmjay/{pmjay_number} — Lookup by PMJAY number
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from datetime import datetime
from typing import List, Optional

from core.database import get_db
from core.auth import get_current_active_user
from models.schemas import PatientCreate, PatientResponse

router = APIRouter()


@router.get("/", response_model=List[PatientResponse])
async def list_patients(
    search: Optional[str] = Query(None, description="Search by name or PMJAY number"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_user),
):
    """
    Get all patients. Accessible to all logged-in users (reviewer and admin).
    Supports optional search by name or PMJAY number, with pagination.
    """
    if search:
        result = await db.execute(
            text("""
                SELECT id, name, dob, age, gender, pmjay_number, phone, created_at
                FROM patients
                WHERE name ILIKE :search OR pmjay_number ILIKE :search
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :skip
            """),
            {"search": f"%{search}%", "limit": limit, "skip": skip},
        )
    else:
        result = await db.execute(
            text("""
                SELECT id, name, dob, age, gender, pmjay_number, phone, created_at
                FROM patients
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :skip
            """),
            {"limit": limit, "skip": skip},
        )

    rows = result.fetchall()
    return [
        PatientResponse(
            patient_id=row.id, name=row.name, dob=row.dob, age=row.age,
            gender=row.gender, pmjay_number=row.pmjay_number, phone=row.phone,
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]


@router.post("/", response_model=PatientResponse, status_code=201)
async def register_patient(
    body: PatientCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Register a new patient.
    Returns patient_id — pass this along with package_code to get the form schema.
    """
    # Check if PMJAY number already exists
    existing = await db.execute(
        text("SELECT id FROM patients WHERE pmjay_number = :pmjay"),
        {"pmjay": body.pmjay_number},
    )
    if existing.fetchone():
        raise HTTPException(
            status_code=409,
            detail=f"Patient with PMJAY number {body.pmjay_number} already registered.",
        )

    result = await db.execute(
        text("""
            INSERT INTO patients (name, dob, age, gender, pmjay_number, phone)
            VALUES (:name, :dob, :age, :gender, :pmjay, :phone)
            RETURNING id, name, dob, age, gender, pmjay_number, phone, created_at
        """),
        {
            "name":   body.name,
            "dob":    body.dob,
            "age":    body.age,
            "gender": body.gender,
            "pmjay":  body.pmjay_number,
            "phone":  body.phone,
        },
    )
    row = result.fetchone()
    return PatientResponse(
        patient_id=row.id,
        name=row.name,
        dob=row.dob,
        age=row.age,
        gender=row.gender,
        pmjay_number=row.pmjay_number,
        phone=row.phone,
        created_at=row.created_at.isoformat(),
    )


@router.get("/{patient_id}", response_model=PatientResponse)
async def get_patient(patient_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT * FROM patients WHERE id = :id"),
        {"id": patient_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Patient not found")
    return PatientResponse(
        patient_id=row.id, name=row.name, dob=row.dob, age=row.age,
        gender=row.gender, pmjay_number=row.pmjay_number, phone=row.phone,
        created_at=row.created_at.isoformat(),
    )


@router.get("/pmjay/{pmjay_number}", response_model=PatientResponse)
async def get_patient_by_pmjay(pmjay_number: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT * FROM patients WHERE pmjay_number = :pmjay"),
        {"pmjay": pmjay_number},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Patient not found")
    return PatientResponse(
        patient_id=row.id, name=row.name, dob=row.dob, age=row.age,
        gender=row.gender, pmjay_number=row.pmjay_number, phone=row.phone,
        created_at=row.created_at.isoformat(),
    )
