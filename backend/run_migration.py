import asyncio
import asyncpg
from core.config import settings

async def run_migration():
    print(f"Connecting to {settings.DATABASE_URL.replace('postgresql+asyncpg://', 'postgresql://')}")
    conn = await asyncpg.connect(settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        with open("migrations/013_icp_agent.sql", "r", encoding="utf-8") as f:
            sql = f.read()
        await conn.execute(sql)
        print("Migration 013_icp_agent.sql executed successfully.")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(run_migration())
