"""LLM Phraser (Rewriter) with provider fallback.

Goal: When user input is ambiguous/underspecified and deterministic parsing is low-confidence,
try rewriting the prompt into a clearer, backend-friendly instruction.

Provider order (configurable):
1) Baseten (OpenAI-compatible) model (e.g., openai/gpt-oss-120b)
2) Groq (LLaMA) model (uses existing Groq credentials)
3) Optional third model (Groq) if configured

Safety/behavior:
- Preserve intent; do not add new operations.
- Output ONLY the rewritten instruction text.
- If a provider is not configured or fails, fall back to next.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import json
import os

import httpx

from app.config import settings


@dataclass
class RephraseResult:
    text: str
    provider: str


_REPHRASE_SYSTEM = """You rewrite user instructions into a single clear command for a PDF processing backend.

Rules:
- Preserve the user’s intent and constraints.
- Do NOT add new operations.
- Do NOT remove constraints like target size (e.g., 2MB), page ranges, degrees, formats.
- Do NOT mention that you are rephrasing.
- Output ONLY the rewritten instruction (no quotes, no bullets).

If the instruction is already clear, return it unchanged.
"""


def _build_user_message(user_prompt: str, file_names: Optional[list[str]] = None) -> str:
    files = file_names or []
    if files:
        return (
            f"User instruction: {user_prompt}\n"
            f"Available files: {json.dumps(files)}\n"
            "Rewrite the instruction to be unambiguous for the backend."
        )
    return (
        f"User instruction: {user_prompt}\n"
        "Rewrite the instruction to be unambiguous for the backend."
    )


class BasetenOpenAICompatRephraser:
    def __init__(self):
        self.api_key = getattr(settings, "baseten_api_key", None) or os.getenv("BASETEN_API_KEY")
        self.base_url = getattr(settings, "baseten_base_url", None) or os.getenv(
            "BASETEN_BASE_URL", "https://inference.baseten.co/v1"
        )
        self.model = getattr(settings, "baseten_model", None) or os.getenv(
            "BASETEN_MODEL", "openai/gpt-oss-120b"
        )
        self.timeout_s = float(getattr(settings, "baseten_timeout_seconds", 12.0) or 12.0)

    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def rephrase(self, user_prompt: str, file_names: Optional[list[str]] = None) -> Optional[RephraseResult]:
        if not self.is_configured():
            return None

        url = self.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _REPHRASE_SYSTEM},
                {"role": "user", "content": _build_user_message(user_prompt, file_names)},
            ],
            "temperature": 0.2,
            "top_p": 1,
            "max_tokens": 200,
        }

        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()

            text = (
                (data.get("choices") or [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            text = (text or "").strip()
            if not text:
                return None
            return RephraseResult(text=text, provider=f"baseten:{self.model}")
        except Exception:
            return None


class GroqRephraser:
    def __init__(self, model: str, provider_name: str):
        self.model = model
        self.provider_name = provider_name

    def is_configured(self) -> bool:
        return bool(getattr(settings, "groq_api_key", None)) and bool(self.model)

    def rephrase(self, user_prompt: str, file_names: Optional[list[str]] = None) -> Optional[RephraseResult]:
        if not self.is_configured():
            return None

        try:
            # Lazy import to avoid any import-time cost.
            from groq import Groq

            client = Groq(api_key=settings.groq_api_key)
            resp = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _REPHRASE_SYSTEM},
                    {"role": "user", "content": _build_user_message(user_prompt, file_names)},
                ],
                temperature=0.2,
                max_tokens=200,
                top_p=1,
            )
            text = (resp.choices[0].message.content or "").strip()
            if not text:
                return None
            return RephraseResult(text=text, provider=self.provider_name)
        except Exception:
            return None


def rephrase_with_fallback(
    user_prompt: str,
    file_names: Optional[list[str]] = None,
) -> Optional[RephraseResult]:
    """Try multiple providers to rephrase a prompt.

    Returns first successful result; None if none succeed.
    """

    if not user_prompt or not user_prompt.strip():
        return None

    providers = []

    # 1) Baseten first (if configured)
    providers.append(BasetenOpenAICompatRephraser())

    # 2) Groq primary model (your existing "llama" model)
    providers.append(GroqRephraser(settings.llm_model, provider_name=f"groq:{settings.llm_model}"))

    # 3) Groq fallback model (optional)
    third = getattr(settings, "llm_model_rephrase_third", None)
    if third:
        providers.append(GroqRephraser(third, provider_name=f"groq:{third}"))
    elif getattr(settings, "llm_model_fallback", None) and settings.llm_model_fallback != settings.llm_model:
        providers.append(
            GroqRephraser(settings.llm_model_fallback, provider_name=f"groq:{settings.llm_model_fallback}")
        )

    original = user_prompt.strip()
    for p in providers:
        out = p.rephrase(original, file_names=file_names)
        if out and out.text and out.text.strip():
            # Avoid returning something wildly longer than the original.
            text = out.text.strip()
            if len(text) > 4 * len(original) and len(text) > 200:
                continue
            return RephraseResult(text=text, provider=out.provider)

    return None
