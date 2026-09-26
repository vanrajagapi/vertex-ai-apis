import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    from core.config import settings
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.connect() as conn:
        await conn.execute(text("TRUNCATE agent_prompts"))
        await conn.commit()
        print("Truncated all broken DB prompts. App will use safe defaults from prompts.py")

asyncio.run(main())
