from __future__ import annotations
from typing import Dict, Any, List
from pydantic import BaseModel, ValidationError
from laneA.catalog_ops.engine import run_catalog_op, ALLOWED_OPS
from laneA import planner as qa_planner
from laneA.planner_llm import plan_with_llm, compose_with_llm
import os
from difflib import get_close_matches
import time

# Semantic Cache (very lightweight)
class CacheEntry(BaseModel):
    key: str
    question: str
    answer: str
    created_at: float

_CACHE: dict[str, CacheEntry] = {}
CACHE_TTL_SECONDS = 300

def _cache_key(q: str) -> str:
    return q.lower().strip()

def cache_lookup(q: str) -> str | None:
    now = time.time()
    key = _cache_key(q)
    exact = _CACHE.get(key)
    if exact and now - exact.created_at < CACHE_TTL_SECONDS:
        return exact.answer
    # fuzzy near match
    candidates = [e.question for e in _CACHE.values() if now - e.created_at < CACHE_TTL_SECONDS]
    close = get_close_matches(q, candidates, n=1, cutoff=0.92)
    if close:
        ck = _cache_key(close[0])
        entry = _CACHE.get(ck)
        if entry:
            return entry.answer
    return None

def cache_store(q: str, answer: str):
    _CACHE[_cache_key(q)] = CacheEntry(key=_cache_key(q), question=q, answer=answer, created_at=time.time())

# Plan Model
class CallSpec(BaseModel):
    op: str
    params: dict

class PlanModel(BaseModel):
    calls: List[CallSpec]

def make_plan(question: str) -> dict:
    # Switch between heuristic and LLM based on env flag
    if os.getenv("CHURCH_BRAIN_USE_LLM"):
        try:
            return plan_with_llm(question)
        except Exception as e:
            # fallback to heuristic on LLM failure
            return qa_planner.plan(question)
    return qa_planner.plan(question)

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
    if os.getenv("CHURCH_BRAIN_USE_LLM"):
        facts = {"calls": [c.dict() for c in plan.calls], "results": results}
        try:
            return compose_with_llm(question, facts)
        except Exception:
            # fall back to heuristic
            pass
    # simple heuristic composition
    lower = question.lower()
    if any(r["op"].startswith("service_times") for r in results):
        svc_res = next(r for r in results if r["op"].startswith("service_times"))
        if svc_res["rows"]:
            times = ", ".join(f"{row['time']}" for row in svc_res["rows"])
            campus = svc_res["rows"][0]["campus_name"]
            answer = f"Next Sunday services at {campus} are at {times}."
            if any(r["op"].startswith("childcare.policy") for r in results):
                ch = next(r for r in results if r["op"].startswith("childcare.policy"))
                if ch["rows"] and any(row["childcare_available"] for row in ch["rows"]):
                    answer += " Childcare is available."
            if "parking" in lower:
                pk = next((r for r in results if r["op"].startswith("parking.by_campus") and r["rows"]), None)
                if pk:
                    answer += f" Parking: {pk['rows'][0]['parking_notes']}"
            return answer + " Need anything else about staff or events?"
    # FAQ fallback
    faq_res = next((r for r in results if r["op"] == "faq.search" and r["rows"]), None)
    if faq_res:
        top = faq_res["rows"][0]
        return top["answer"] + " (Ask for service times, parking, or childcare if needed.)"
    # Generic insufficient data
    return "I couldn't find specific data for that. You can ask about service times, staff, parking, childcare, or events."

def answer_question(question: str) -> dict:
    cached = cache_lookup(question)
    if cached:
        return {"cached": True, "answer": cached, "plan": {"calls": []}, "results": []}
    raw_plan = make_plan(question)
    try:
        plan_model = validate_plan(raw_plan)
    except ValueError as e:
        return {"error": str(e)}
    results = execute_calls(plan_model)
    answer = compose_answer(question, plan_model, results)
    cache_store(question, answer)
    return {"cached": False, "answer": answer, "plan": plan_model.dict(), "results": results}