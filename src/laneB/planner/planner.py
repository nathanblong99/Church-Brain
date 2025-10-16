from __future__ import annotations
from typing import Dict, Any, List
from pydantic import BaseModel, ValidationError
from llm.provider import call_llm, safe_json_parse
from laneB.verbs.registry import VERBS

VERB_CHEATSHEET = """
Verb cheat sheet (only call verbs that exist in the registry and supply all required fields):
- guest_pairing.request_create: Capture a guest's info when they express interest in being paired. Args: guest_name, contact, age_range, gender, marital_status, optional notes.
- guest_pairing.match: Suggest active volunteers for a guest request. Args: request_id, optional limit (default 3). Use after request_create.
- guest_pairing.assign: Confirm a pairing once a volunteer is selected. Args: request_id, volunteer_id. Use after match.
- guest_pairing.volunteer_register: When a volunteer opts in via SMS, store or update their profile. Args include name, phone, age_range, gender, marital_status, optional active.
- sms.send: Send a templated text. Args: to, template, variables, idempotency_key. Use to gather missing details or confirm next steps.
- notify.staff: Alert a staff role about work that needs a human. Args: staff_role, template, variables.
- create_record / update_record: Generic data writes. Provide kind and structured data.
- make_offers / wait_for_replies / assign / unassign: Use for volunteer role scheduling flows.
- schedule.timer: Queue a follow-up action after delay_seconds with a payload.
If the inbound message lacks required data for a verb, plan a step (e.g., sms.send or notify.staff) to obtain it rather than inventing values.
"""


class LLMPlanStep(BaseModel):
    verb: str
    args: Dict[str, Any]


class LLMPlan(BaseModel):
    steps: List[LLMPlanStep]
    shard: str | None = None


def _plan_with_llm(
    text: str,
    tenant_id: str,
    actor_id: str,
    existing_request_id: str | None,
    conversation_history: str | None = None,
) -> Dict[str, Any]:
    history_block = (
        "Recent conversation history (oldest to newest):\n"
        f"{conversation_history}\n"
        if conversation_history
        else "Recent conversation history: none provided.\n"
    )
    prompt = (
        "You are the Lane B operations planner. Output ONLY valid JSON with schema "
        '{"steps":[{"verb":"name","args":{}}], "shard": "optional-string"}.\n'
        "Only use verbs that exist in the executor registry and keep arguments minimal.\n"
        "You MUST avoid side effects in planning; the executor will run verbs later.\n"
        f"{VERB_CHEATSHEET}\n"
        f"Tenant: {tenant_id}\nActor: {actor_id}\nExistingVolunteerRequestId: {existing_request_id}\n"
        f"{history_block}"
        f"User text: {text}\nJSON:"
    )
    raw = call_llm(prompt, response_mime_type="application/json")
    data, err = safe_json_parse(raw)
    if err or not isinstance(data, dict) or "steps" not in data:
        repair = prompt + f"\nPrevious invalid output:\n{raw}\nReturn ONLY valid JSON now."
        raw2 = call_llm(repair, response_mime_type="application/json")
        data2, err2 = safe_json_parse(raw2)
        if err2 or not isinstance(data2, dict) or "steps" not in data2:
            raise ValueError("llm_plan_parse_failed")
        return data2
    return data


def _infer_shard(plan: LLMPlan, existing_request_id: str | None) -> str | None:
    if plan.shard:
        return plan.shard
    shard = None
    for step in plan.steps:
        verb = step.verb
        args = step.args or {}
        if verb == "create_record" and args.get("kind") == "volunteer_request":
            shard = "VolunteerRequest:new"
        elif verb == "update_record" and args.get("kind") == "volunteer_request":
            target_id = args.get("id") or existing_request_id
            if target_id:
                shard = f"VolunteerRequest:{target_id}"
    return shard


def validate_plan(raw_data: Dict[str, Any], existing_request_id: str | None = None) -> Dict[str, Any]:
    try:
        plan = LLMPlan(**raw_data)
    except ValidationError as e:
        raise ValueError(f"llm_plan_invalid:{e}")

    sanitized_steps: List[Dict[str, Any]] = []
    for step in plan.steps:
        if step.verb not in VERBS:
            raise ValueError(f"llm_plan_unknown_verb:{step.verb}")
        args = step.args or {}
        sanitized_steps.append({"verb": step.verb, "args": args})
    shard = _infer_shard(plan, existing_request_id)
    return {"steps": sanitized_steps, "shard": shard}


def plan(
    tenant_id: str,
    actor_id: str,
    text: str,
    existing_request_id: str | None = None,
    conversation_history: str | None = None,
) -> Dict[str, Any]:
    raw_plan = _plan_with_llm(text, tenant_id, actor_id, existing_request_id, conversation_history)
    return validate_plan(raw_plan, existing_request_id)
