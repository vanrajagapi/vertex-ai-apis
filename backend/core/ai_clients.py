"""
AI Client Abstraction Layer
───────────────────────────
Swap AI providers without touching any agent logic.
All clients implement: async call(prompt, images) -> str

Usage:
    from core.ai_clients import ClaudeClient, OpenAIClient, StubClient

    # For PoC / testing (no API key needed):
    client = StubClient()

    # For Claude:
    client = ClaudeClient(api_key="sk-ant-...")

    # For GPT-4o:
    client = OpenAIClient(api_key="sk-...")

    # Pass to any agent:
    agent = ClinicalRelevanceAgent(ai_client=client)
"""

import json
import httpx
import logging
from abc import ABC, abstractmethod
from typing import Optional

try:
    from langsmith import traceable
    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False
    def traceable(**kwargs):
        """No-op decorator when langsmith is not installed."""
        def decorator(func):
            return func
        return decorator


# ─────────────────────────────────────────
# Abstract Interface
# ─────────────────────────────────────────

class AIClient(ABC):
    """Base interface for all AI providers."""

    async def call(self, prompt: str, images: list[str] = [], system: str = "") -> str:
        """
        Call the AI model.
        images: list of base64-encoded image strings (for vision models)
        Returns: raw text response
        """
        import sys

        raw_response = await self._call_impl(prompt, images, system)

        # 1. Output to standard stdout and flush immediately
        sys.stdout.write(f"\n=================== AI MODEL RESPONSE ===================\n{raw_response}\n==========================================================\n")
        sys.stdout.flush()

        # 2. Output to standard stderr and flush immediately
        sys.stderr.write(f"\n=================== AI MODEL RESPONSE (STDERR) ===================\n{raw_response}\n==========================================================\n")
        sys.stderr.flush()

        # 3. Output to uvicorn logger if running under uvicorn
        logger = logging.getLogger("uvicorn")
        logger.info(f"AI Model Response:\n{raw_response}")

        # 4. Output to generic print
        print(f"AI Model Response printed: {raw_response}", flush=True)

        return raw_response

    @abstractmethod
    async def _call_impl(self, prompt: str, images: list[str] = [], system: str = "") -> str:
        ...


# ─────────────────────────────────────────
# Stub Client (PoC default — no API key)
# ─────────────────────────────────────────

class StubClient(AIClient):
    """
    Returns hardcoded responses for offline PoC testing.
    Replace with real client when AI keys are available.
    """

    @traceable(run_type="llm", name="StubClient")
    async def _call_impl(self, prompt: str, images: list[str] = [], system: str = "") -> str:
        return json.dumps({
            "status": "stub",
            "score": 75,
            "flags": [],
            "note": "StubClient — plug in real AI client to activate"
        })


# ─────────────────────────────────────────
# Claude Client (Anthropic)
# ─────────────────────────────────────────

class ClaudeClient(AIClient):
    """
    Anthropic Claude API client.
    Supports text + vision (image base64).

    Models: claude-opus-4-6, claude-sonnet-4-6 (recommended for PoC)
    """

    BASE_URL = "https://api.anthropic.com/v1/messages"
    DEFAULT_MODEL = "claude-opus-4-6"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, max_tokens: int = 2048):
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens

    @staticmethod
    def _detect_media_type(b64_data: str) -> tuple[str, str]:
        """
        Detect content type from base64 data prefix.
        Returns (claude_type, media_type):
          - ("document", "application/pdf") for PDFs
          - ("image", "image/png") for PNGs
          - ("image", "image/gif") for GIFs
          - ("image", "image/webp") for WebP
          - ("image", "image/jpeg") for everything else (default)
        """
        prefix = b64_data[:20] if b64_data else ""
        if prefix.startswith("JVBERi"):       # %PDF
            return "document", "application/pdf"
        elif prefix.startswith("iVBORw"):      # PNG
            return "image", "image/png"
        elif prefix.startswith("R0lGOD"):      # GIF
            return "image", "image/gif"
        elif prefix.startswith("UklGR"):       # WebP (RIFF)
            return "image", "image/webp"
        else:
            return "image", "image/jpeg"

    @traceable(run_type="llm", name="ClaudeClient", metadata={"provider": "anthropic"})
    async def _call_impl(self, prompt: str, images: list[str] = [], system: str = "") -> str:
        content = []

        async with httpx.AsyncClient(timeout=180) as client:
            for file_b64 in images:
                content_type, media_type = self._detect_media_type(file_b64)
                if content_type == "document":
                    try:
                        import base64
                        import uuid
                        pdf_bytes = base64.b64decode(file_b64)
                        
                        # Upload to Anthropic Files API
                        upload_res = await client.post(
                            "https://api.anthropic.com/v1/files",
                            headers={
                                "x-api-key": self.api_key,
                                "anthropic-version": "2023-06-01",
                                "anthropic-beta": "files-api-2025-04-14"
                            },
                            files={"file": (f"doc_{uuid.uuid4().hex}.pdf", pdf_bytes, "application/pdf")}
                        )
                        upload_res.raise_for_status()
                        file_id = upload_res.json()["id"]
                        
                        # Attach via file_id
                        content.append({
                            "type": "document",
                            "source": {
                                "type": "file",
                                "file_id": file_id
                            }
                        })
                    except Exception as e:
                        import logging
                        logging.getLogger("uvicorn").error(f"Failed to upload PDF via Files API: {e}")
                    continue
                    
                # Standard base64 attachment for regular images (JPEG/PNG)
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": file_b64
                    }
                })

            content.append({"type": "text", "text": prompt})

            payload = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "messages": [{"role": "user", "content": content}]
            }
            if system:
                payload["system"] = system

            response = await client.post(
                self.BASE_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "anthropic-beta": "files-api-2025-04-14",
                    "content-type": "application/json",
                },
                json=payload,
            )
            if response.status_code != 200:
                error_body = response.text
                import logging
                logging.getLogger("uvicorn").error(
                    f"[ClaudeClient] API error {response.status_code}: {error_body}"
                )
                print(f"[ClaudeClient] API error {response.status_code}: {error_body}", flush=True)
                # Return a fallback JSON so the agent can gracefully degrade
                return json.dumps({
                    "error": True,
                    "status_code": response.status_code,
                    "message": f"Claude API returned {response.status_code}",
                    "detail": error_body[:500]
                })
            data = response.json()
            return data["content"][0]["text"]


# ─────────────────────────────────────────
# OpenAI GPT-4o Client
# ─────────────────────────────────────────

class OpenAIClient(AIClient):
    """
    OpenAI GPT-4o client.
    Supports text + vision.
    """

    BASE_URL = "https://api.openai.com/v1/chat/completions"
    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, max_tokens: int = 2048):
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens

    @traceable(run_type="llm", name="OpenAIClient", metadata={"provider": "openai"})
    async def _call_impl(self, prompt: str, images: list[str] = [], system: str = "") -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})

        user_content = []
        for img_b64 in images:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
            })
        user_content.append({"type": "text", "text": prompt})

        messages.append({"role": "user", "content": user_content})

        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": messages,
        }

        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                self.BASE_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]


# ─────────────────────────────────────────
# Google Gemini Client
# ─────────────────────────────────────────

class GeminiClient(AIClient):
    """
    Google Gemini Pro/Flash client.
    Good for high-volume lab/radiology at lower cost.

    Uses the Gemini File API for large files (>20KB base64):
      1. Upload file → get a file URI
      2. Reference URI in generateContent (tiny request body)
    Falls back to inlineData for small payloads.
    """

    DEFAULT_MODEL = "gemini-3.1-flash-lite"
    # Files larger than this (in base64 chars) use the File API upload path
    INLINE_THRESHOLD = 20_000

    UPLOAD_URL = "https://generativelanguage.googleapis.com/upload/v1beta/files"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self.api_key = api_key
        self.model = model

    def _base_url(self) -> str:
        return (
            f"https://generativelanguage.googleapis.com/v1beta/models"
            f"/{self.model}:generateContent?key={self.api_key}"
        )

    @staticmethod
    def _detect_mime(b64: str) -> str:
        """Detect MIME type from base64 magic bytes."""
        if b64.startswith("data:"):
            header = b64.split(";", 1)[0]
            return header.replace("data:", "")
        if b64.startswith("JVBER"):
            return "application/pdf"
        if b64.startswith("iVBORw0KGgo"):
            return "image/png"
        if b64.startswith("/9j/"):
            return "image/jpeg"
        return "image/jpeg"

    @staticmethod
    def _strip_data_uri(b64: str) -> str:
        """Remove data:...;base64, prefix if present."""
        if b64.startswith("data:"):
            return b64.split(",", 1)[-1]
        return b64

    async def _upload_file(self, client: httpx.AsyncClient, raw_bytes: bytes, mime_type: str) -> str:
        """
        Upload binary content via Gemini File API.
        Returns the file URI to reference in generateContent.
        """
        import uuid as _uuid
        display_name = f"pmjay-upload-{_uuid.uuid4().hex[:8]}"

        # Multipart upload: metadata JSON + raw file bytes
        headers = {
            "X-Goog-Upload-Protocol": "multipart",
            "x-goog-api-key": self.api_key,
        }
        metadata = json.dumps({"file": {"displayName": display_name}})

        # Build multipart/related body manually
        boundary = f"----PmjayBoundary{_uuid.uuid4().hex[:12]}"
        body = (
            f"--{boundary}\r\n"
            f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{metadata}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8") + raw_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

        headers["Content-Type"] = f"multipart/related; boundary={boundary}"

        resp = await client.post(self.UPLOAD_URL, content=body, headers=headers)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            print(f"Gemini File Upload Error: {resp.text}", flush=True)
            raise
        file_info = resp.json()
        file_uri = file_info["file"]["uri"]
        print(f"[Gemini File API] Uploaded {display_name} → {file_uri}", flush=True)
        return file_uri

    @traceable(run_type="llm", name="GeminiClient", metadata={"provider": "google"})
    async def _call_impl(self, prompt: str, images: list[str] = [], system: str = "") -> str:
        import base64 as _b64

        parts = []

        async with httpx.AsyncClient(timeout=180) as client:
            for img_b64 in images:
                mime_type = self._detect_mime(img_b64)
                clean_b64 = self._strip_data_uri(img_b64)

                if len(clean_b64) > self.INLINE_THRESHOLD:
                    # Large file → upload via File API, reference by URI
                    raw_bytes = _b64.b64decode(clean_b64)
                    file_uri = await self._upload_file(client, raw_bytes, mime_type)
                    parts.append({
                        "fileData": {"mimeType": mime_type, "fileUri": file_uri}
                    })
                else:
                    # Small file → inline (faster for tiny images)
                    parts.append({
                        "inlineData": {"mimeType": mime_type, "data": clean_b64}
                    })

            parts.append({"text": prompt})

            payload = {"contents": [{"parts": parts}]}

            response = await client.post(self._base_url(), json=payload)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                print(f"Gemini API Error: {response.text}", flush=True)
                raise e
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]


# ─────────────────────────────────────────
# Client Factory
# ─────────────────────────────────────────

def get_ai_client(provider: str, api_key: Optional[str] = None) -> AIClient:
    """
    Factory to get an AI client by provider name.
    Used by dependency injection in FastAPI.

    provider: "claude" | "openai" | "gemini" | "stub"
    """
    if provider == "claude" and api_key:
        return ClaudeClient(api_key=api_key)
    elif provider == "openai" and api_key:
        return OpenAIClient(api_key=api_key)
    elif provider == "gemini" and api_key:
        return GeminiClient(api_key=api_key)
    else:
        return StubClient()
