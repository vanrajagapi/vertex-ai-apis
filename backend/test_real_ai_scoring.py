import asyncio
import sys
import os
import json
import httpx
from unittest.mock import MagicMock

sys.path.insert(0, r"d:\pmjay\backend")

from main import app
from core.database import AsyncSessionLocal
from core.auth import get_current_active_user
from sqlalchemy import text
from datetime import date

# Override auth dependency to allow requests
app.dependency_overrides[get_current_active_user] = lambda: {
    "username": "testuser",
    "email": "test@pmjay.gov.in",
    "full_name": "Test Reviewer",
    "role": "reviewer",
    "disabled": False
}

# A valid 1x1 pixel transparent JPEG base64 string
VALID_1X1_JPEG_BASE64 = "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="

async def setup_test_data():
    async with AsyncSessionLocal() as db:
        # 1. Insert patient if not exists
        await db.execute(
            text("""
                INSERT INTO patients (id, name, dob, age, gender, pmjay_number, phone)
                VALUES (999, 'John Doe', '1980-01-01', 46, 'Male', 'PMJ-REAL-AI-TEST', '9876543210')
                ON CONFLICT (pmjay_number) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
            """)
        )
        await db.commit()
        
        # 2. Insert claim
        # package P19001 (Cataract Surgery)
        pkg_res = await db.execute(text("SELECT id FROM packages WHERE code = 'P19001'"))
        pkg = pkg_res.fetchone()
        if not pkg:
            raise Exception("Package P19001 not found. Please run migrations/seed first.")
        pkg_id = pkg.id
        
        # Insert a new claim
        claim_ref = "CLM-TEST-REAL-AI"
        await db.execute(
            text("DELETE FROM claims WHERE claim_ref = :ref"),
            {"ref": claim_ref}
        )
        await db.commit()
        
        claim_res = await db.execute(
            text("""
                INSERT INTO claims (claim_ref, patient_id, package_id, hospital_id, admission_date, discharge_date, status)
                VALUES (:ref, 999, :pkg_id, 'HOSP-REAL-AI', '2026-05-10', '2026-05-12', 'PENDING')
                RETURNING id
            """),
            {"ref": claim_ref, "pkg_id": pkg_id}
        )
        claim_id = claim_res.fetchone().id
        await db.commit()
        
        # 3. Insert claim documents
        # P19001 mandatory fields are: clinical_notes, consent_form, discharge_summary, surgery_photos
        docs = [
            ("clinical_notes", "text", "Clinical notes: Patient John Doe, 46yo male, presented with progressive blurring of vision in the left eye. Diagnostic evaluation confirmed left eye senile immature cataract. Consent obtained for left eye cataract surgery under local anesthesia. Procedure performed on 2026-05-11. Left eye cataract extraction with intraocular lens implantation was completed successfully. Post-op vision is stable. Discharged in stable condition.", None),
            ("consent_form", "text", "Consent form: I, John Doe, hereby give my consent for left eye cataract surgery (phacoemulsification with IOL implantation) at HOSP-REAL-AI. I understand the procedure and risks. Signed, John Doe, 2026-05-10.", None),
            ("discharge_summary", "text", "Discharge Summary: Patient Name: John Doe. Age: 46. Hospital: HOSP-REAL-AI. Diagnosis: Left eye Cataract. Procedure: Left eye cataract surgery on 2026-05-11. Condition on discharge: Stable. Signed by Dr. ophthalmologist.", None),
            ("surgery_photos", "others", None, "surgery_postop.jpg"),
        ]
        
        for fkey, fgrp, text_content, filename in docs:
            await db.execute(
                text("""
                    INSERT INTO claim_documents (claim_id, field_key, field_group, text_content, filename, content_base64)
                    VALUES (:cid, :fkey, :fgrp, :txt, :fname, :b64)
                """),
                {
                    "cid": claim_id,
                    "fkey": fkey,
                    "fgrp": fgrp,
                    "txt": text_content,
                    "fname": filename,
                    "b64": VALID_1X1_JPEG_BASE64 if filename else None
                }
            )
        await db.commit()
        print(f"Test data seeded successfully. Claim ID: {claim_id}")
        return claim_id

async def run_scoring(claim_id: int):
    print(f"\n--- Running scoring API for Claim ID: {claim_id} with original AI ---")
    async with httpx.AsyncClient(app=app, base_url="http://test", timeout=120.0) as ac:
        response = await ac.post(f"/api/v1/claims/{claim_id}/score")
    
    print(f"Response Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print("\n=== CLAIM SCORE REPORT ===")
        print(f"Verdict: {data.get('verdict')}")
        print(f"Total Score: {data.get('total_score')}")
        print(f"Hard Block: {data.get('hard_block')} (Reason: {data.get('hard_block_reason')})")
        print("\nAgent Scores:")
        for res in data.get('agent_results', []):
            print(f"  - {res['agent_name']}: score={res['score']}, passed={res['passed']}")
            if res.get('flags'):
                print("    Flags:")
                for f in res['flags']:
                    print(f"      * [{f['severity']}] in field {f['field']}: {f['reason']}")
        
        print("\nMissing Documents:", data.get('missing_documents'))
        print("Identity Mismatches:", data.get('identity_mismatches'))
        print("Recommendations:", data.get('recommendations'))
        print(f"Processing Time: {data.get('processing_time_ms')} ms")
    else:
        print("Scoring failed:", response.text)

async def main():
    claim_id = await setup_test_data()
    await run_scoring(claim_id)

if __name__ == "__main__":
    asyncio.run(main())
