from __future__ import annotations
import os
from typing import Dict, Any, List
from llm.provider import call_llm, safe_json_parse, LLMError
from laneA.catalog_ops.engine import ALLOWED_OPS

PLAN_TEMPLATE = (
    "You are the Lane A planner. Output ONLY valid JSON with schema {\n"
    "  \"calls\": [ {\"op\": \"name\", \"params\": {}} ]\n}\n"
    "Allowed ops: {allowed}\n"
    "User question: {question}\n"
    "Return JSON ONLY."
)

def plan_with_llm(question: str) -> Dict[str, Any]:
    prompt = PLAN_TEMPLATE.format(
        allowed=", ".join(ALLOWED_OPS.keys()),
        question=question.strip()
    )
    raw = call_llm(prompt)
    data, err = safe_json_parse(raw)
    if err or not isinstance(data, dict) or "calls" not in data:
        # one repair attempt
        repair = prompt + f"\nPrevious invalid output:\n{raw}\nReturn ONLY correct JSON now."
        raw2 = call_llm(repair)
        data2, err2 = safe_json_parse(raw2)
        if err2 or not isinstance(data2, dict) or "calls" not in data2:
            raise ValueError(f"LLM plan parse failure: {err2 or 'missing calls'}")
        return data2
    return data

COMPOSE_TEMPLATE = (
    "You are the Lane A composer. Answer the user's question kindly and concisely using ONLY the provided results JSON.\n"
    "If service times are present, list them. If staff with role 'pastor' present and user asks 'head pastor', choose the first as lead unless a 'lead' indicator exists.\n"
    "Offer one short follow-up suggestion. No invented data.\n"
    "Question: {question}\nResults JSON: {results}\nAnswer:"
)

def compose_with_llm(question: str, facts: Dict[str, Any]) -> str:
    import json
    prompt = COMPOSE_TEMPLATE.format(question=question.strip(), results=json.dumps(facts, ensure_ascii=False))
    return call_llm(prompt)
