from __future__ import annotations
from typing import Dict, Any, List
from pydantic import BaseModel, ValidationError
from laneA.catalog_ops.engine import run_catalog_op, ALLOWED_OPS
from laneA.planner_llm import plan_with_llm, compose_with_llm

# Plan Model
class CallSpec(BaseModel):
    op: str
    params: dict

class PlanModel(BaseModel):
    calls: List[CallSpec]

def make_plan(question: str) -> dict:
    return plan_with_llm(question)

def validate_plan(plan: dict) -> PlanModel:
    try:
        p = PlanModel(**plan)
    except ValidationError as e:
        raise ValueError(f"plan_invalid:{e}")
    # whitelist check
    for c in p.calls:
        if c.op not in ALLOWED_OPS:
            raise ValueError(f"unknown_op:{c.op}")
        # prune disallowed params (safety)
        allowed = set(ALLOWED_OPS[c.op])
        c.params = {k: v for k, v in c.params.items() if k in allowed}
    return p

def execute_calls(plan: PlanModel) -> list[dict[str, Any]]:
    results = []
    for c in plan.calls:
        out = run_catalog_op(c.op, c.params)
        results.append(out)
    return results

def compose_answer(question: str, plan: PlanModel, results: list[dict[str, Any]]) -> str:
    facts = {"calls": [c.dict() for c in plan.calls], "results": results}
    try:
        return compose_with_llm(question, facts)
    except Exception:
        # Minimal deterministic fallback to avoid empty responses during outages.
        if results:
            return "Unable to compose a full answer right now, but retrieved data successfully."
        return "Unable to compose an answer with the available information."

def answer_question(question: str, precomputed_plan: dict | None = None) -> dict:
    if precomputed_plan is not None:
        try:
            plan_model = validate_plan(precomputed_plan)
        except ValueError as e:
            return {"error": str(e)}
    else:
        raw_plan = make_plan(question)
        try:
            plan_model = validate_plan(raw_plan)
        except ValueError as e:
            return {"error": str(e)}
    results = execute_calls(plan_model)
    answer = compose_answer(question, plan_model, results)
    return {"cached": False, "answer": answer, "plan": plan_model.dict(), "results": results}
