from __future__ import annotations
from typing import Dict, Any
import os
from llm.provider import call_llm, safe_json_parse, LLMError
import re

# Very naive rule-based planner (Phase 1). Returns plan JSON.
# Recognizes patterns like:
#   "Invite 10 volunteers (5 basketball, 5 volleyball). Rent Gym 5:00-8:00"
#   "Make it 8 volunteers total; 5:30-8:30 pm"

VOLUNTEER_PATTERN = re.compile(r"(?P<total>\d+)\s+volunteers|Invite\s+(?P<invite>\d+)", re.IGNORECASE)
ROLE_SPLIT_PATTERN = re.compile(r"(\d+)\s*(basketball|volleyball)", re.IGNORECASE)
ROOM_PATTERN = re.compile(r"(rent|book)\s+([A-Za-z0-9_ ]+)?\s?(?:\broom\b|gym|hall)?\s*(?P<start>\d{1,2}:\d{2})\s*[-to ]+(?P<end>\d{1,2}:\d{2})", re.IGNORECASE)
ADJUST_PATTERN = re.compile(r"make it (\d+) volunteers", re.IGNORECASE)
TIME_ADJUST_PATTERN = re.compile(r"(\d{1,2}:\d{2})\s*[-to ]+(\d{1,2}:\d{2})", re.IGNORECASE)


def parse_roles(text: str) -> dict:
    roles = {"basketball": 0, "volleyball": 0}
    for m in ROLE_SPLIT_PATTERN.finditer(text):
        count = int(m.group(1))
        role = m.group(2).lower()
        roles[role] += count
    return roles


def _plan_with_llm(text: str) -> Dict[str, Any]:
    prompt = (
        "You are the Lane B operations planner. Output ONLY JSON {\\"steps\\":[{\\"verb\\":\\"name\\",\\"args\\":{}}]}\n"
        "Supported verbs examples: create_record, update_record (volunteer_request).\n"
        f"User text: {text}\nJSON:"
    )
    raw = call_llm(prompt)
    data, err = safe_json_parse(raw)
    if err or not isinstance(data, dict) or 'steps' not in data:
        repair = prompt + f"\nPrevious invalid output:\n{raw}\nReturn ONLY correct JSON now."
        raw2 = call_llm(repair)
        data2, err2 = safe_json_parse(raw2)
        if err2 or not isinstance(data2, dict) or 'steps' not in data2:
            raise ValueError("LLM Lane B planner parse failure")
        return data2
    return data

def plan(tenant_id: str, actor_id: str, text: str, existing_request_id: str | None = None) -> Dict[str, Any]:
    if os.getenv("CHURCH_BRAIN_USE_LLM"):
        try:
            llm_plan = _plan_with_llm(text)
            # we still enrich with shard detection from heuristic below
            # reuse existing logic to compute shard based on counts if needed
            # if llm plan empty we fallback
            if llm_plan.get("steps"):
                # naive shard inference: if any create/update volunteer_request
                shard = None
                for s in llm_plan["steps"]:
                    if s.get("verb") in ("create_record","update_record"):
                        shard = "VolunteerRequest:new"
                llm_plan.setdefault("shard", shard)
                return llm_plan
        except Exception:
            pass
    text_lower = text.lower()
    roles = parse_roles(text)
    total = sum(roles.values())
    steps = []
    shard = None
    if total > 0 and not existing_request_id:
        shard = f"VolunteerRequest:new"
        steps.append({"verb": "create_record", "args": {"kind": "volunteer_request", "data": {"basketball_needed": roles["basketball"], "volleyball_needed": roles["volleyball"]}}})
    elif total > 0 and existing_request_id:
        shard = f"VolunteerRequest:{existing_request_id}"
        steps.append({"verb": "update_record", "args": {"kind": "volunteer_request", "id": existing_request_id, "data": {"basketball_needed": roles["basketball"], "volleyball_needed": roles["volleyball"]}}})

    # Room planning (placeholder: not integrated with allocator verbs yet)
    room_match = ROOM_PATTERN.search(text)
    if room_match:
        # In Phase 1 we don't have explicit room verbs; placeholder no-op
        pass

    return {"steps": steps, "shard": shard}
