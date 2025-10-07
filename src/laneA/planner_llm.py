from __future__ import annotations
import os
from typing import Dict, Any, List
from llm.provider import call_llm, safe_json_parse, LLMError
from laneA.catalog_ops.engine import ALLOWED_OPS

PLAN_TEMPLATE = (
    "You are the Lane A planner. Output ONLY valid JSON with schema {{\n"
    "  \"calls\": [ {{\"op\": \"name\", \"params\": {{}} }} ]\n}}\n"
    "Plan every catalog call needed to answer all parts of the question. "
    "If the user references staff (e.g., a pastor), include the appropriate staff.lookup call.\n"
    "Preserve descriptive qualifiers (campus names, ministry names, age groups, etc.) in the params "
    "so downstream ops can return precise results (e.g., role \"middle_school_pastor\", name \"middle school\").\n"
    "Allowed ops: {allowed}\n"
    "User question: {question}\n"
    "Return JSON ONLY."
)

def plan_with_llm(question: str) -> Dict[str, Any]:
    prompt = PLAN_TEMPLATE.format(
        allowed=", ".join(ALLOWED_OPS.keys()),
        question=question.strip()
    )
    raw = call_llm(prompt, response_mime_type="application/json")
    data, err = safe_json_parse(raw)
    if err or not isinstance(data, dict) or "calls" not in data:
        # one repair attempt
        repair = prompt + f"\nPrevious invalid output:\n{raw}\nReturn ONLY correct JSON now."
        raw2 = call_llm(repair, response_mime_type="application/json")
        data2, err2 = safe_json_parse(raw2)
        if err2 or not isinstance(data2, dict) or "calls" not in data2:
            raise ValueError(f"LLM plan parse failure: {err2 or 'missing calls'}")
        return data2
    return data

COMPOSE_TEMPLATE = (
    "You are the Lane A composer. Answer the user's question kindly and concisely using ONLY the provided results JSON.\n"
    "Summarize every distinct fact in the results that answers the user's question—include key people, times, locations, counts, and other specifics when they are present.\n"
    "If the question includes specific qualifiers (like a ministry name or age group) and the results do not contain matching data, clearly say you could not find that detail.\n"
    "Offer one short follow-up suggestion. No invented data.\n"
    "Question: {question}\nResults JSON: {results}\nAnswer:"
)

def compose_with_llm(question: str, facts: Dict[str, Any]) -> str:
    import json
    prompt = COMPOSE_TEMPLATE.format(question=question.strip(), results=json.dumps(facts, ensure_ascii=False))
    return call_llm(prompt)
