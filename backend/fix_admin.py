import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from core.config import settings
from core.security import get_password_hash

async def fix_admin_password():
    engine = create_async_engine(settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql+asyncpg://"))
    async with engine.begin() as conn:
        hashed_pw = get_password_hash("admin123")
        await conn.execute(
            text("UPDATE users SET hashed_password = :h WHERE username = 'admin'"),
            {"h": hashed_pw}
        )
        print("Admin password updated successfully to 'admin123'")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(fix_admin_password())
