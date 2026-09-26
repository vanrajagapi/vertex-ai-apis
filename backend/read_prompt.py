import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    from core.config import settings
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT system_prompt FROM agent_prompts WHERE agent_name='DocumentExtractorAgent'"))
        old_prompt = res.scalar()
        
        # Double the curly braces for JSON block so LangChain PromptTemplate doesn't crash
        new_prompt = old_prompt.replace("{", "{{").replace("}", "}}")
        
        await conn.execute(text("UPDATE agent_prompts SET system_prompt = :p WHERE agent_name='DocumentExtractorAgent'"), {"p": new_prompt})
        await conn.commit()
        print("Fixed prompt!")

asyncio.run(main())
