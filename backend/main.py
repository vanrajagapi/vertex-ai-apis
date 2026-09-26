"""
PMJAY Claim Pre-Authorization Prediction API — v2.0
"""

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from routes import claims, packages, health, patients, auth, admin
from fastapi import Depends
from core.auth import get_current_active_user
from core.config import settings

app = FastAPI(
    title="PMJAY Claim Pre-Auth API",
    description="AI-powered claim scoring — PostgreSQL backend, dynamic weights",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Wildcard origins + credentials is invalid CORS. Browsers then allow login
# (simple form POST, no Authorization) but block every Bearer GET/POST after
# OPTIONS preflight — which is what you see via ngrok.
# Echo any Origin in DEBUG so localhost + ngrok frontends both work.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=r".*" if settings.DEBUG else r"https://.*\.(ngrok-free\.app|ngrok\.io|ngrok\.app)",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["*"],
    expose_headers=["*"],
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Extract the first error message for a cleaner, frontend-friendly response
    errors = exc.errors()
    error_msg = errors[0]["msg"] if errors else "Validation error"
    
    # Return a normal 400 Bad Request instead of the confusing 422 Pydantic format
    return JSONResponse(
        status_code=400, 
        content={"detail": error_msg}
    )

app.include_router(auth.router,      prefix="/api/v1/auth",      tags=["Authentication"])
app.include_router(admin.router,     prefix="/api/v1/admin",     tags=["Admin"])
app.include_router(health.router,    prefix="/api/v1",           tags=["Health"])
app.include_router(patients.router,  prefix="/api/v1/patients",  tags=["Patients"], dependencies=[Depends(get_current_active_user)])
app.include_router(packages.router,  prefix="/api/v1/packages",  tags=["Packages"], dependencies=[Depends(get_current_active_user)])
app.include_router(claims.router,    prefix="/api/v1/claims",    tags=["Claims"], dependencies=[Depends(get_current_active_user)])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
