from __future__ import annotations
"""LLM-backed summary + clarifying question phrasing for Lane B.
We accept deterministic signals and an optional chosen question descriptor.
If LLM env active we attempt to produce a natural language summary + question; otherwise fallback
on simple templates.
"""
from typing import List, Dict, Any, Optional
from llm.provider import call_llm, safe_json_parse


def _fallback_summary(signals: List[Dict[str, Any]]) -> str:
    parts = []
    for s in signals:
        if s["type"].startswith("volunteer_request_"):
            if s["type"] == "volunteer_request_created":
                parts.append(f"Created volunteer request needing basketball={s.get('basketball_needed')} volleyball={s.get('volleyball_needed')}")
            elif s["type"] == "volunteer_request_updated":
                parts.append(f"Updated volunteer request {s.get('request_id')} totals basketball={s.get('basketball_needed')} volleyball={s.get('volleyball_needed')}")
        elif s["type"] == "room_hold_created":
            parts.append(f"Placed hold for room {s.get('room_id')}")
        elif s["type"] == "room_hold_failed":
            parts.append(f"Room hold failed for {s.get('room_id')}")
    return "; ".join(parts) or "Executed plan."\


def _fallback_question(chosen: Dict[str, Any]) -> str:
    code = chosen.get("code")
    if code == "invite_next":
        return "Do you want me to start inviting volunteers now?"
    if code == "adjust_follow_up":
        return "Should I proceed to invite the updated number of volunteers?"
    if code == "room_alternative":
        return "Would you like to try a different room or time?"
    return "Anything else you want to adjust?"


def summarize_and_clarify(signals: List[Dict[str, Any]], chosen_question: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    # Build compact structured description of signals for prompt
    signal_desc = [{"type": s.get("type"), **{k:v for k,v in s.items() if k not in ("type",)}} for s in signals]
    question_code = chosen_question.get("code") if chosen_question else None
    prompt = (
        "You are a concise operations assistant. Given structured execution signals and an optional question code, "
        "produce JSON {\"summary\": str, \"question\": str|null}. Summary: 1 sentence. Question should be friendly and clear if code present.\n"
        f"Signals: {signal_desc}\nQuestionCode: {question_code}\nJSON:"
    )
    try:
        raw = call_llm(prompt, response_mime_type="application/json")
        data, err = safe_json_parse(raw)
        if err or not isinstance(data, dict) or 'summary' not in data:
            raise ValueError(err or "missing_summary")
    except Exception:
        # Retry once; if it still fails, fall back to deterministic phrasing.
        try:
            repair = prompt + "\nPrevious output invalid. Return ONLY valid JSON."
            raw2 = call_llm(repair, response_mime_type="application/json")
            data2, err2 = safe_json_parse(raw2)
            if err2 or not isinstance(data2, dict) or 'summary' not in data2:
                raise ValueError(err2 or "missing_summary")
            data = data2
        except Exception:
            return {
                "summary": _fallback_summary(signals),
                "clarifying_question": _fallback_question(chosen_question) if chosen_question else None,
                "clarifying_code": question_code,
                "_fallback_reason": "llm_parse_failed",
            }
    return {
        "summary": data.get("summary") or _fallback_summary(signals),
        "clarifying_question": data.get("question") if question_code else None,
        "clarifying_code": question_code,
    }
