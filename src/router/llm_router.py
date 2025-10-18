from __future__ import annotations
from typing import Any, Dict, Optional

from llm.provider import call_llm, safe_json_parse, LLMError
from laneA.catalog_ops.engine import ALLOWED_OPS
from laneB.verbs.registry import VERBS


ALLOWED_OP_NAMES = sorted(ALLOWED_OPS.keys())
VERB_NAMES = sorted(VERBS.keys())


def route_with_plan(
    message: str,
    *,
    tenant_id: str,
    actor_id: str,
    actor_roles: list[str],
    existing_request_id: Optional[str] = None,
    include_plan: bool = True,
    conversation_history: Optional[str] = None,
) -> Dict[str, Any]:
    ops_list = ", ".join(ALLOWED_OP_NAMES)
    verbs_list = ", ".join(VERB_NAMES)
    base_prompt = (
        "You are the Church Brain router. For each inbound message choose one of four paths:"
        "\n- SMALLTALK: reply directly in a warm, human tone (greeting, empathy, explain Church Brain)."
        "\n- Lane A: run catalog Q&A ops to answer informational questions."
        "\n- Lane B: plan operational verbs (no side effects during planning)."
        "\n- HYBRID: answer via Lane A then propose Lane B actions."
        "\nPrefer SMALLTALK whenever the user is just greeting you, asking who you are, introducing themselves, or otherwise making small talk that doesn’t need catalog data or verbs."
    )
    schema_prompt = (
        'Output STRICT JSON with schema {"lane": "SMALLTALK|A|B|HYBRID", '
        '"qa_plan": {...}|null, "execution_plan": {...}|null, "smalltalk_response": string|null}. '
        "No explanations, no prose."
    )
    lane_guidance = (
        "Lane definitions:\n"
        "- SMALLTALK: You answer directly. Give a friendly, concise reply in `smalltalk_response` and set qa_plan/execution_plan to null."
        "- Lane A: Read-only informational answers via allowed catalog ops."
        "- Lane B: Operational verbs from the registry (do not invent verbs)."
        "- HYBRID: Provide a Lane A answer first, then a Lane B plan."
    )
    plan_guidance: str
    if include_plan:
        plan_guidance = (
            "If lane is A or HYBRID you MUST populate qa_plan as {\"calls\":[{\"op\":name,\"params\":{}}]}."
            f" Allowed catalog ops: {ops_list}."
            " If lane is B or HYBRID you MUST populate execution_plan as {\"steps\":[{\"verb\":name,\"args\":{}}], \"shard\": string|null}."
            f" Allowed verbs: {verbs_list}."
            " Use existingRequestId if provided when updating an existing request."
            " When planning Lane B actions, prefer modular verbs (conversation.*, guest_request.*, guest_volunteer.*, create_record, update_record, schedule.timer) before falling back to guest_pairing.* verbs."
            " Treat stubbed verbs (e.g., people.search, catalog.run) as unavailable until they are implemented."
            " If lane is SMALLTALK, set qa_plan and execution_plan to null and fill smalltalk_response with your conversational reply."
        )
    else:
        plan_guidance = (
            "Set qa_plan and execution_plan to null. For SMALLTALK return your conversational reply in smalltalk_response; otherwise set smalltalk_response to null."
        )

    history_block = (
        "Recent conversation history (oldest to newest):\n"
        f"{conversation_history}"
        if conversation_history
        else "Recent conversation history: none provided."
    )

    context = (
        f"Tenant: {tenant_id}\nActor: {actor_id}\nActorRoles: {actor_roles}\n"
        f"ExistingRequestId: {existing_request_id or 'null'}\n"
        f"{history_block}\n"
        f"New inbound message: {message}"
    )

    prompt = "\n\n".join([base_prompt, lane_guidance, plan_guidance, schema_prompt, context, "JSON:"])

    raw = call_llm(prompt, response_mime_type="application/json")
    data, err = safe_json_parse(raw)
    if err or not isinstance(data, dict):
        raise LLMError(f"router_parse_failed:{err or 'invalid structure'}")
    lane = data.get("lane")
    if lane not in {"SMALLTALK", "A", "B", "HYBRID"}:
        raise LLMError("router_invalid_lane")
    qa_plan = data.get("qa_plan")
    execution_plan = data.get("execution_plan")
    smalltalk_response = data.get("smalltalk_response")
    return {
        "lane": lane,
        "qa_plan": qa_plan if include_plan else None,
        "execution_plan": execution_plan if include_plan else None,
        "smalltalk_response": smalltalk_response,
    }
