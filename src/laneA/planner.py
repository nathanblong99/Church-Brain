from __future__ import annotations
from typing import Dict, Any, List
import re

# Heuristic rule-based planner for Phase 2 (LLM placeholder).
# Input: natural language question.
# Output: {"calls": [{"op": op_name, "params": {...}} ...]}

SERVICE_PATTERN = re.compile(r"service|what time.*service", re.IGNORECASE)
CHILDCARE_PATTERN = re.compile(r"child ?care|kids|nursery", re.IGNORECASE)
PARKING_PATTERN = re.compile(r"parking", re.IGNORECASE)
STAFF_PATTERN = re.compile(r"staff|pastor|who leads|contact", re.IGNORECASE)
EVENTS_PATTERN = re.compile(r"upcoming events|what's happening|events", re.IGNORECASE)
FAQ_HINT = re.compile(r"\?$|how |when |where |what |why |is ", re.IGNORECASE)

def plan(question: str) -> Dict[str, Any]:
    q = question.strip()
    calls: List[dict] = []
    lower = q.lower()

    if SERVICE_PATTERN.search(q):
        # default to next_sunday if date not specified
        calls.append({"op": "service_times.by_date_and_campus", "params": {"date": "next_sunday"}})
        if CHILDCARE_PATTERN.search(q):
            calls.append({"op": "childcare.policy.by_service", "params": {"date": "next_sunday"}})
    elif CHILDCARE_PATTERN.search(q):
        calls.append({"op": "childcare.policy.by_service", "params": {"date": "next_sunday"}})

    if PARKING_PATTERN.search(q):
        calls.append({"op": "parking.by_campus", "params": {}})

    if STAFF_PATTERN.search(q):
        # crude role extraction
        if "pastor" in lower:
            calls.append({"op": "staff.lookup", "params": {"role": "pastor"}})

    if EVENTS_PATTERN.search(q):
        calls.append({"op": "events.upcoming.by_campus", "params": {"limit": 3}})

    # fallback to FAQ if nothing else chosen or direct question sign
    if not calls or FAQ_HINT.search(q):
        calls.append({"op": "faq.search", "params": {"query": q}})

    # Deduplicate preserving order (op+params tuple key)
    seen = set()
    deduped = []
    for c in calls:
        key = (c["op"], tuple(sorted(c["params"].items())))
        if key not in seen:
            seen.add(key)
            deduped.append(c)

    return {"calls": deduped}