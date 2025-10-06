from __future__ import annotations
import os, json, time
import httpx
from typing import Optional, Tuple, Any, Dict

class LLMError(Exception):
    pass

def _provider() -> str:
    return (os.getenv("LLM_PROVIDER") or "mock").lower()

def call_llm(prompt: str, *, model: Optional[str] = None, temperature: float = 0.0, max_retries: int = 1) -> str:
    """Unified LLM call.
    Current modes:
      - mock (default): deterministic placeholder (no network)
      - openai: placeholder stub (requires OPENAI_API_KEY) – NOT implemented fully
    Switching is controlled by env LLM_PROVIDER.
    When CHURCH_BRAIN_USE_LLM is unset, raise LLMError to force fallback.
    """
    if not os.getenv("CHURCH_BRAIN_USE_LLM"):
        raise LLMError("LLM disabled (set CHURCH_BRAIN_USE_LLM=1)")
    provider = _provider()
    if provider == "mock":
        # Simple echo logic; if asking for plan JSON, return empty structure
        low = prompt.lower()
        if '"calls"' in low or 'calls":' in low:
            return '{"calls":[]}'
        if '"verbs"' in low or 'verbs":' in low:
            return '{"steps":[]}'
        return "Mock LLM response"
    elif provider == "openai":
        raise LLMError("OpenAI provider not yet implemented.")
    elif provider == "gemini":
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise LLMError("GOOGLE_API_KEY not set.")
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "contents": [
                {"parts": [{"text": prompt}]}
            ],
            # Keep default safety; we don't send temperature per user request
        }
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(url, json=payload)
                if resp.status_code != 200:
                    raise LLMError(f"gemini_http_{resp.status_code}:{resp.text[:120]}")
                data = resp.json()
        except Exception as e:
            raise LLMError(f"gemini_call_failed:{e}")
        # Extract text
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
    else:
        raise LLMError(f"Unknown provider {provider}")

def safe_json_parse(raw: str) -> Tuple[Optional[Any], Optional[str]]:
    try:
        return json.loads(raw), None
    except Exception as e:
        return None, str(e)
