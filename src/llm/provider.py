from __future__ import annotations
import os
import json
from typing import Optional, Tuple, Any
import httpx


class LLMError(Exception):
    pass


def _provider() -> str:
    provider = os.getenv("LLM_PROVIDER")
    if not provider:
        raise LLMError("LLM_PROVIDER not set.")
    return provider.lower()


def call_llm(
    prompt: str,
    *,
    model: Optional[str] = None,
    temperature: float = 0.0,
    max_retries: int = 1,
    response_mime_type: Optional[str] = None,
) -> str:
    """Unified LLM call. Only real providers are supported; no offline mock."""
    if not os.getenv("CHURCH_BRAIN_USE_LLM"):
        raise LLMError("CHURCH_BRAIN_USE_LLM must be set to use the LLM planner.")

    provider = _provider()
    if provider == "gemini":
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise LLMError("GOOGLE_API_KEY not set.")
        model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "contents": [
                {"parts": [{"text": prompt}]}
            ],
        }
        if response_mime_type:
            payload["generationConfig"] = {"responseMimeType": response_mime_type}
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(url, json=payload)
                if resp.status_code != 200:
                    raise LLMError(f"gemini_http_{resp.status_code}:{resp.text[:120]}")
                data = resp.json()
        except Exception as e:
            raise LLMError(f"gemini_call_failed:{e}")
        try:
            candidates = data.get("candidates") or []
            if not candidates:
                raise ValueError("no_candidates")
            first = candidates[0]
            parts = first.get("content", {}).get("parts", [])
            texts = [p.get("text", "") for p in parts if isinstance(p, dict)]
            out = "\n".join([t for t in texts if t]) or ""
            return out or ""
        except Exception as e:
            raise LLMError(f"gemini_parse_failed:{e}")
    elif provider == "openai":
        raise LLMError("OpenAI provider not yet implemented.")
    else:
        raise LLMError(f"Unknown provider {provider}")


def safe_json_parse(raw: str) -> Tuple[Optional[Any], Optional[str]]:
    try:
        return json.loads(raw), None
    except Exception as e:
        return None, str(e)
