# PMJAY Pre-Authorization & Claim Workflow Integration

We have successfully integrated a complete, robust, and database-driven **Pre-Authorization (PreAuth)** workflow into the existing PMJAY claims engine pipeline.

This implementation allows hospitals to submit and score pre-authorizations before performing a procedure, and maps subsequent claims back to their pre-authorizations—combining documents from both stages for final claim evaluation.

---

## 🏗️ 1. Architecture & Workflow Design

The lifecycle of a PMJAY claim now consists of two distinct stages:

```mermaid
graph TD
    A[Patient Registered] --> B[GET /packages/{code}/form-schema?stage=preauth]
    B --> C[POST /api/v1/claims/preauth]
    C --> D[POST /api/v1/claims/preauth/{id}/score]
    D -->|PreAuth Approved| E[GET /packages/{code}/form-schema?stage=claim]
    E --> F[POST /api/v1/claims/ with preauth_id]
    F --> G[POST /api/v1/claims/{id}/score]
    G -->|Combined Assessment| H[Final Verdict & Claim Payment]
```

### Key Workflow Highlights:
1. **Stage Classification**: Dynamic package fields are now marked as `preauth` or `claim` stage using a new `stage` column in `package_documents`.
2. **Form-Schema Filtering**: The dynamic form generator endpoint `/form-schema` supports filtering fields by stage, allowing the frontend to render the appropriate form for each stage.
3. **Multi-Stage Orchestration**: When scoring a final claim that has a mapped pre-authorization, the claims engine dynamically merges documents from **both** the preauth stage and claim stage to check compliance and perform AI-driven medical audits.

---

## 💾 2. Database Schema (Migration 009)

We created and executed a new database migration (`migrations/009_preauth_flow.sql`) to set up the relational mapping:

*   **`package_documents.stage`**: Added a `stage` VARCHAR column with a check constraint `('preauth', 'claim')`.
*   **Backfill Logic**: Automatically updated existing documents:
    *   `discharge_summary`, `ot_notes`, `surgery_photos`, and `others` are classified under the `claim` stage.
    *   Diagnostic and clinical files (`clinical_notes`, `consent_form`, `pathology`, `radiology`) are defaulted to the `preauth` stage.
*   **`preauths`**: Tracks pre-authorizations including unique reference IDs, status, patient/package links, and admission date.
*   **`preauth_documents`**: Stores pre-authorization text and file submissions.
*   **`preauth_score_reports`**: Persists scoring reports, agent verdicts, module weights, and flags.
*   **`claim_preauth_mappings`**: Connects claims with their associated pre-authorizations.

---

## 🛡️ 3. API Endpoints Reference

### A. Pre-Authorization APIs

#### 1. Submit PreAuth Documents
*   **Method / Route**: `POST /api/v1/claims/preauth`
*   **Payload**: `PreauthSubmitRequest`
*   **Response**: Returns `preauth_id`, `preauth_ref`, `status: "PENDING"`, and submission receipt details.

#### 2. PreAuth Pre-Flight Check
*   **Method / Route**: `GET /api/v1/claims/preauth/{preauth_id}/preflight`
*   **Response**: Returns validation compliance check of mandatory documents required *only* for the `preauth` stage.

#### 3. Run PreAuth Scoring Engine
*   **Method / Route**: `POST /api/v1/claims/preauth/{preauth_id}/score`
*   **Processing**: Runs all 7 AI-driven specialized agents (Identity, Compliance, Clinical Relevance, Pathology, Radiology, Image, etc.) using weights configured in the DB for the package.
*   **Response**: Returns `PreauthScoreReport`.

#### 4. Fetch PreAuth Score Report
*   **Method / Route**: `GET /api/v1/claims/preauth/{preauth_id}/report`
*   **Response**: Returns the saved score report for manual verification.

---

### B. Updated Claims APIs

#### 1. Map PreAuth to Claims
*   **Method / Route**: `POST /api/v1/claims/`
*   **Updated Payload**: Now accepts an optional `preauth_id`. If provided, it registers the claim-to-preauth relationship in the mapping table.

#### 2. Aggregate Documents on Claim Scoring
*   **Method / Route**: `POST /api/v1/claims/{claim_id}/score`
*   **Updated Processing**: Dynamically fetches all documents submitted during the associated Pre-Authorization step and combines them with those submitted in the claim step, ensuring the AI scoring context contains the full patient clinical picture.

---

## 🛠️ 4. Configuration & Schema Updates

We modified:
1.  **`models/schemas.py`**: Introduced `ClaimStage` Enum and added `stage` fields to admin schemas. Defined `PreauthSubmitRequest` and `PreauthScoreReport` for complete Swagger integration.
2.  **`packages.py`**: Added stage query parameters to dynamic form generator `/packages/{code}/form-schema` to filter document requirements.
3.  **`admin.py`**: Added full Stage management in Package Documents CRUD (GET, POST, and PUT) to allow administrators to configure stages dynamically.
4.  **`claims.py`**: Wired up all PreAuth workflow logic, including DB storage, preflight checks, scoring processes, and mapping capabilities.
