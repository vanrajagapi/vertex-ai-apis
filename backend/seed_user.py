import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from core.config import settings
from core.security import get_password_hash

async def add_normal_user():
    engine = create_async_engine(settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql+asyncpg://"))
    async with engine.begin() as conn:
        hashed_pw = get_password_hash("password123")
        await conn.execute(
            text("""
                INSERT INTO users (username, email, full_name, hashed_password, role)
                VALUES ('testuser', 'test@pmjay.gov.in', 'Test Reviewer', :h, 'reviewer')
                ON CONFLICT (username) DO NOTHING
            """),
            {"h": hashed_pw}
        )
        print("Normal user 'testuser' created successfully with password 'password123'")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(add_normal_user())
