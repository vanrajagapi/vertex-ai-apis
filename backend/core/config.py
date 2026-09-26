"""
App configuration — all values from environment / .env file
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # PostgreSQL
    DATABASE_URL: str = "postgresql+asyncpg://vanraj:123456@localhost:5433/pmjay"

    # AI Provider: stub | claude | openai | gemini
    AI_PROVIDER: str = "stub"
    AI_API_KEY: str = ""

    # Scoring verdicts
    PASS_THRESHOLD: float = 85.0
    REVIEW_THRESHOLD: float = 60.0

    DEBUG: bool = True
    APP_VERSION: str = "2.0.0"

    # Auth
    SECRET_KEY: str = "super-secret-key-for-development"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
