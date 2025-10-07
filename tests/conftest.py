import json
import re
import pytest

from llm import provider as llm_provider
import laneA.planner_llm as laneA_planner_llm
import laneB.planner.planner as laneB_planner
import laneB.clarify.compose_llm as laneB_compose
import router.llm_router as llm_router


def _extract_between(prompt: str, marker: str) -> str | None:
    pattern = re.compile(re.escape(marker) + r"\s*(.+)")
    match = pattern.search(prompt)
    return match.group(1).strip() if match else None


def _mock_lane_b_plan(prompt: str) -> str:
    text = _extract_between(prompt, "User text:") or ""
    existing = _extract_between(prompt, "ExistingVolunteerRequestId:") or ""
    existing = None if existing in ("", "None") else existing
    roles = {"basketball": 0, "volleyball": 0}
    for count, role in re.findall(r"(\d+)\s*(basketball|volleyball)", text, re.IGNORECASE):
        roles[role.lower()] += int(count)
    total = sum(roles.values())
    steps: list[dict] = []
    shard = None
    if total > 0 and not existing:
        steps.append({
            "verb": "create_record",
            "args": {"kind": "volunteer_request", "data": {"basketball_needed": roles["basketball"], "volleyball_needed": roles["volleyball"]}},
        })
        shard = "VolunteerRequest:new"
    elif total > 0 and existing:
        steps.append({
            "verb": "update_record",
            "args": {"kind": "volunteer_request", "id": existing, "data": {"basketball_needed": roles["basketball"], "volleyball_needed": roles["volleyball"]}},
        })
        shard = f"VolunteerRequest:{existing}"
    return json.dumps({"steps": steps, "shard": shard})


def _mock_lane_a_plan(prompt: str) -> str:
    question = _extract_between(prompt, "User question:") or ""
    calls: list[dict] = []
    lower = question.lower()
    if "service" in lower or "time" in lower:
        calls.append({"op": "service_times.by_date_and_campus", "params": {"date": "next_sunday"}})
    if "child" in lower or "kid" in lower or "nursery" in lower:
        calls.append({"op": "childcare.policy.by_service", "params": {"date": "next_sunday"}})
    if "parking" in lower:
        calls.append({"op": "parking.by_campus", "params": {}})
    if "middle school" in lower:
        calls.append({"op": "staff.lookup", "params": {"role": "middle_school_pastor"}})
        calls.append({"op": "ministry.schedule.by_name", "params": {"name": "middle school"}})
    if ("pastor" in lower or "who leads" in lower or "staff" in lower) and not any(c["op"] == "staff.lookup" for c in calls):
        calls.append({"op": "staff.lookup", "params": {"role": "pastor"}})
    if "event" in lower or "happening" in lower:
        calls.append({"op": "events.upcoming.by_campus", "params": {"limit": 3}})
    calls.append({"op": "faq.search", "params": {"query": question}})
    deduped: list[dict] = []
    seen = set()
    for c in calls:
        key = (c["op"], tuple(sorted(c["params"].items())))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    return json.dumps({"calls": deduped})


def _mock_lane_a_compose(prompt: str) -> str:
    try:
        question = _extract_between(prompt, "Question:") or ""
        results_json = re.search(r"Results JSON:\s*(\{.*\})\s*Answer:", prompt, re.DOTALL)
        data = json.loads(results_json.group(1)) if results_json else {}
        results = data.get("results", [])
    except Exception:
        return "I cannot answer that right now."

    def _find(op_prefix: str):
        return next((r for r in results if r.get("op", "").startswith(op_prefix)), None)

    service = _find("service_times")
    childcare = _find("childcare.policy")
    parking = _find("parking.by_campus")
    staff_lookup = next((r for r in results if r.get("op") == "staff.lookup" and r.get("rows")), None)
    ministry_schedule = next((r for r in results if r.get("op") == "ministry.schedule.by_name" and r.get("rows")), None)
    faq = next((r for r in results if r.get("op") == "faq.search" and r.get("rows")), None)

    pieces: list[str] = []
    if service and service.get("rows"):
        campus = service["rows"][0]["campus_name"]
        times = ", ".join(row["time"] for row in service["rows"])
        pieces.append(f"Services at {campus} are at {times}.")
    if childcare and childcare.get("rows"):
        if any(row.get("childcare_available") for row in childcare["rows"]):
            pieces.append("Childcare is available for those services.")
    if parking and parking.get("rows"):
        notes = parking["rows"][0].get("parking_notes")
        if notes:
            pieces.append(f"Parking: {notes}")
    if staff_lookup:
        staff = staff_lookup["rows"][0]
        detail = staff.get("name", "")
        role = staff.get("role")
        campus = staff.get("campus_name")
        if role:
            detail += f" ({role})"
        if campus:
            detail += f" at {campus}"
        if detail:
            pieces.append(f"Lead contact: {detail}.")
    if ministry_schedule:
        sched = ministry_schedule["rows"][0]
        name = sched.get("name", "").title()
        day = sched.get("meeting_day")
        time = sched.get("meeting_time")
        location = sched.get("location")
        detail = f"{name} meets"
        if day:
            detail += f" on {day}"
        if time:
            detail += f" at {time}"
        if location:
            detail += f" in {location}"
        pieces.append(detail + ".")
    if not pieces and faq:
        pieces.append(faq["rows"][0]["answer"])
    if "middle school" in question.lower() and not (staff_lookup or ministry_schedule):
        pieces.append("I couldn't find specific details for the middle school ministry right now.")
    if not pieces:
        pieces.append("I could not find specific data for that question.")
    pieces.append("Anything else you need?")
    return " ".join(pieces)


def _mock_lane_b_clarify(prompt: str) -> str:
    try:
        signals_json = re.search(r"Signals:\s*(\[.*?\])\s*QuestionCode:", prompt, re.DOTALL)
        signals = json.loads(signals_json.group(1)) if signals_json else []
        code = _extract_between(prompt, "QuestionCode:") or ""
    except Exception:
        signals = []
        code = ""
    summary_parts = []
    for s in signals:
        stype = s.get("type")
        if stype == "volunteer_request_created":
            summary_parts.append(
                f"Created volunteer request needing basketball={s.get('basketball_needed')} volleyball={s.get('volleyball_needed')}"
            )
        elif stype == "volunteer_request_updated":
            summary_parts.append(
                f"Updated volunteer request {s.get('request_id')} totals basketball={s.get('basketball_needed')} volleyball={s.get('volleyball_needed')}"
            )
    if not summary_parts:
        summary_parts.append("Execution completed.")
    question_map = {
        "invite_next": "Do you want me to start inviting volunteers now?",
        "adjust_follow_up": "Should I invite volunteers based on the update?",
        "room_alternative": "Would you like to try a different room or time?",
    }
    question = question_map.get(code)
    return json.dumps({"summary": "; ".join(summary_parts), "question": question})


def _mock_response(prompt: str) -> str:
    lower = prompt.lower()
    if "church brain router" in lower:
        message_match = re.search(r"Message:\s*(.+)", prompt)
        msg = message_match.group(1) if message_match else ""
        msg_lower = msg.lower()
        if ("invite" in msg_lower and "when" in msg_lower) or ("book" in msg_lower and "what time" in msg_lower):
            return json.dumps({
                "lane": "HYBRID",
                "qa_plan": {"calls": [{"op": "service_times.by_date_and_campus", "params": {"date": "next_sunday"}}]},
                "execution_plan": {
                    "steps": [
                        {
                            "verb": "create_record",
                            "args": {
                                "kind": "volunteer_request",
                                "data": {"basketball_needed": 2, "volleyball_needed": 0}
                            },
                        }
                    ],
                    "shard": "VolunteerRequest:new",
                },
            })
        if "volunteer" in msg.lower():
            return json.dumps({
                "lane": "B",
                "qa_plan": None,
                "execution_plan": {
                    "steps": [
                        {
                            "verb": "create_record",
                            "args": {
                                "kind": "volunteer_request",
                                "data": {"basketball_needed": 3, "volleyball_needed": 2}
                            },
                        }
                    ],
                    "shard": "VolunteerRequest:new",
                },
            })
        return json.dumps({
            "lane": "A",
            "qa_plan": {"calls": [{"op": "faq.search", "params": {"query": msg}}]},
            "execution_plan": None,
        })

    if "lane b operations planner" in lower:
        return _mock_lane_b_plan(prompt)
    if "lane a planner" in lower:
        return _mock_lane_a_plan(prompt)
    if "lane a composer" in lower:
        return _mock_lane_a_compose(prompt)
    if "concise operations assistant" in lower:
        return _mock_lane_b_clarify(prompt)
    return "Mock LLM response"


@pytest.fixture(autouse=True)
def stub_llm(monkeypatch):
    """Replace LLM calls with deterministic mock for tests."""
    def fake_call(prompt: str, *, model=None, temperature: float = 0.0, max_retries: int = 1, response_mime_type=None) -> str:
        return _mock_response(prompt)

    monkeypatch.setenv("CHURCH_BRAIN_USE_LLM", "1")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    # Patch provider module and downstream imports
    monkeypatch.setattr(llm_provider, "call_llm", fake_call)
    monkeypatch.setattr(laneA_planner_llm, "call_llm", fake_call)
    monkeypatch.setattr(laneB_planner, "call_llm", fake_call)
    monkeypatch.setattr(laneB_compose, "call_llm", fake_call)
    monkeypatch.setattr(llm_router, "call_llm", fake_call)

    yield
