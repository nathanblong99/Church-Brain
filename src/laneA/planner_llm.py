from __future__ import annotations
from typing import Dict, Any

from llm.provider import call_llm, safe_json_parse
from laneA.catalog_ops.engine import ALLOWED_OPS

PLAN_TEMPLATE = (
    "You are the Lane A planner. Output ONLY valid JSON with schema {{\n"
    '  "calls": [ {{"op": "name", "params": {{}} }} ]\n'
    "}}\n"
    "Plan every catalog call needed to answer all parts of the question. "
    "If the user references staff (e.g., a pastor), include the appropriate staff.lookup call.\n"
    "Preserve descriptive qualifiers (campus names, ministry names, age groups, etc.) in the params "
    "so downstream ops can return precise results (e.g., role \"middle_school_pastor\", name \"middle school\").\n"
    "Allowed ops: {allowed}\n"
    "{history}\n"
    "User question: {question}\n"
    "Return JSON ONLY."
)


def plan_with_llm(question: str, conversation_history: str | None = None) -> Dict[str, Any]:
    history_block = (
        "Recent conversation history (oldest to newest):\n"
        f"{conversation_history}"
        if conversation_history
        else "Recent conversation history: none provided."
    )
    prompt = PLAN_TEMPLATE.format(
        allowed=", ".join(ALLOWED_OPS.keys()),
        history=history_block,
        question=question.strip(),
    )
    raw = call_llm(prompt, response_mime_type="application/json")
    data, err = safe_json_parse(raw)
    if err or not isinstance(data, dict) or "calls" not in data:
        repair = prompt + f"\nPrevious invalid output:\n{raw}\nReturn ONLY correct JSON now."
        raw2 = call_llm(repair, response_mime_type="application/json")
        data2, err2 = safe_json_parse(raw2)
        if err2 or not isinstance(data2, dict) or "calls" not in data2:
            raise ValueError(f"LLM plan parse failure: {err2 or 'missing calls'}")
        return data2
    return data


COMPOSE_TEMPLATE = (
    "You are the Lane A composer. Think of yourself as the friendly front-desk assistant for Church Brain, an AI that helps churches answer questions, welcome guests, and coordinate follow-up.\n"
    "Answer the user's question kindly and concisely using ONLY the provided results JSON when it contains relevant facts.\n"
    "If the user is asking what Church Brain is, who you are, or why they are receiving help—and the results array is empty—respond from your built-in knowledge instead of saying you could not find anything. Give a warm, human-friendly introduction such as: 'Hi there! I'm Church Brain, the front-desk assistant for your church. I can answer questions, help guests feel welcome, and loop in the right teammate so your staff can focus on people instead of paperwork.' Invite them to ask anything else.\n"
    "Never apologize or say you couldn't find information in that scenario; always provide the welcoming introduction above.\n"
    "For all other questions, summarize every distinct fact in the results that answers the user's question—including key people, times, locations, counts, and other specifics when they are present.\n"
    "If the question includes specific qualifiers (like a ministry name or age group) and the results do not contain matching data, clearly say you could not find that detail.\n"
    "Offer one short follow-up suggestion. If the user expresses interest in visiting (mentions coming, visiting, attending, first time, etc.), ask whether they would like to sit with a friendly volunteer who can show them around, and note there is no pressure.\n"
    "No invented data beyond the allowed self-introduction.\n"
    "{history}\n"
    "Question: {question}\nResults JSON: {results}\nAnswer:"
)


def compose_with_llm(question: str, facts: Dict[str, Any], conversation_history: str | None = None) -> str:
    import json

    history_block = (
        "Recent conversation history (oldest to newest):\n"
        f"{conversation_history}"
        if conversation_history
        else "Recent conversation history: none provided."
    )
    prompt = COMPOSE_TEMPLATE.format(
        question=question.strip(),
        results=json.dumps(facts, ensure_ascii=False),
        history=history_block,
    )
    return call_llm(prompt)
