import asyncio
import asyncpg
from core.config import settings

async def run_migration():
    db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    print(f"Connecting to DB...")
    conn = await asyncpg.connect(db_url)
    try:
        print("Reading migration SQL...")
        with open("migrations/009_preauth_flow.sql", "r", encoding="utf-8") as f:
            sql = f.read()
        print("Executing migration SQL...")
        await conn.execute(sql)
        print("Migration 009_preauth_flow.sql executed successfully.")
    except Exception as e:
        print(f"Error during migration: {e}")
        raise e
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(run_migration())
