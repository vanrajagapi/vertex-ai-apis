"""
Base Agent — v2
Accepts claim_context: dict  (not a Pydantic model)
LangSmith tracing: each agent run and AI call is tracked.
"""

from abc import ABC, abstractmethod
from models.schemas import AgentResult
import time

try:
    from langsmith import traceable
except ImportError:
    def traceable(**kwargs):
        def decorator(func):
            return func
        return decorator


class BaseAgent(ABC):
    name: str = "BaseAgent"

    def __init__(self, ai_client=None):
        self.ai_client = ai_client   # ← AI plugged in here

    @abstractmethod
    async def run(self, claim: dict, context: dict) -> AgentResult:
        """
        claim   = claim_context dict from orchestrator
        context = outputs from previously-run agents
        """
        ...

    @traceable(run_type="chain", name="agent_call_ai")
    async def _call_ai(self, prompt: str, images: list = []) -> str:
        if self.ai_client is None:
            return self._stub_response()
        raw = await self.ai_client.call(prompt=prompt, images=images)
        if not raw:
            return ""
        
        cleaned = raw.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].split("```")[0].strip()
            
        # Robustly extract JSON object if there's leading/trailing text without markdown blocks
        start = cleaned.find('{')
        end = cleaned.rfind('}')
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start:end+1]
            
        return cleaned

    def _stub_response(self) -> str:
        import json
        return json.dumps({
            "status": "stub",
            "score": 75,
            "flags": [],
            "note": "StubClient — no AI key configured"
        })
