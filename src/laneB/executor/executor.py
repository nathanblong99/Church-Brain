from __future__ import annotations
from typing import List, Dict, Any
from pydantic import BaseModel, ValidationError
from laneB.verbs.registry import run_verb, VerbContext
from laneB.clarify.detectors import detect_signals, choose_clarifying_question
from laneB.clarify.compose_llm import summarize_and_clarify
from state.repository import GLOBAL_DB
from state import locks
from state.event_log import log

class PlanStep(BaseModel):
    verb: str
    args: Dict[str, Any]

class ExecutionPlan(BaseModel):
    steps: List[PlanStep]
    shard: str | None = None

class Executor:
    def __init__(self, correlation_id: str, tenant_id: str, actor_id: str, actor_roles: list[str]):
        self.correlation_id = correlation_id
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.actor_roles = actor_roles

    def execute(self, plan_json: Dict[str, Any]) -> Dict[str, Any]:
        try:
            plan = ExecutionPlan(**plan_json)
        except ValidationError as e:
            return {"ok": False, "error": f"plan_invalid:{e}"}
        shard_owner = f"exec:{self.correlation_id}" if plan.shard else None
        acquired = True
        if plan.shard:
            acquired = locks.acquire(plan.shard, shard_owner or "")
        if not acquired:
            log("shard_busy", self.correlation_id, self.actor_id, self.tenant_id, plan.shard, {"plan": plan_json})
            return {"ok": False, "error": "shard_locked"}
        results = []
        try:
            for step in plan.steps:
                ctx = VerbContext(
                    correlation_id=self.correlation_id,
                    tenant_id=self.tenant_id,
                    actor_id=self.actor_id,
                    actor_roles=self.actor_roles,
                    shard=plan.shard,
                )
                res = run_verb(step.verb, step.args, ctx)
                if not res.ok:
                    return {"ok": False, "error": res.error, "results": results}
                results.append({"verb": step.verb, "data": res.data})
            log("plan_executed", self.correlation_id, self.actor_id, self.tenant_id, plan.shard, {"steps": len(plan.steps)})
            # Clarify phase (post execution, no side effects other than summary)
            try:
                signals = detect_signals(plan_json, results)
                chosen = choose_clarifying_question(signals)
                clarify = summarize_and_clarify(signals, chosen)
            except Exception as e:
                clarify = {"summary": "Execution completed.", "clarifying_question": None, "_clarify_error": str(e)}
            # Persist conversation clarify state (ephemeral)
            GLOBAL_DB.set_conversation_state(self.correlation_id, {
                "clarify": clarify,
                "signals": signals,
            })
            return {"ok": True, "results": results, "clarify": clarify}
        finally:
            if plan.shard:
                locks.release(plan.shard, shard_owner or "")
