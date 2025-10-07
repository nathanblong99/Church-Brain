from __future__ import annotations
from fastapi import FastAPI
from pydantic import BaseModel
from datetime import datetime
import uuid
from laneB.planner import planner
from laneB.executor.executor import Executor
from state.event_log import log
from laneA.qa_flow import answer_question
from router.llm_router import route_with_plan
from router.classifier import derive_event_key
from state.seed import load_dev_seed

app = FastAPI(title="Church Brain Kernel Phase 1")

# Load development mega-church seed data (idempotent)
load_dev_seed()

class InboundMessage(BaseModel):
    tenant_id: str
    actor_id: str
    actor_roles: list[str]
    text: str
    existing_request_id: str | None = None

class PlanResponse(BaseModel):
    correlation_id: str
    plan: dict

class ExecuteResponse(BaseModel):
    correlation_id: str
    result: dict

@app.post("/plan", response_model=PlanResponse)
def plan(msg: InboundMessage):
    correlation_id = uuid.uuid4().hex
    plan_json = planner.plan(msg.tenant_id, msg.actor_id, msg.text, msg.existing_request_id)
    log("plan_created", correlation_id, msg.actor_id, msg.tenant_id, plan_json.get("shard"), {"plan": plan_json})
    return PlanResponse(correlation_id=correlation_id, plan=plan_json)

class ExecuteRequest(BaseModel):
    correlation_id: str
    plan: dict
    tenant_id: str
    actor_id: str
    actor_roles: list[str]

@app.post("/execute", response_model=ExecuteResponse)
def execute(req: ExecuteRequest):
    execr = Executor(req.correlation_id, req.tenant_id, req.actor_id, req.actor_roles)
    result = execr.execute(req.plan)
    return ExecuteResponse(correlation_id=req.correlation_id, result=result)

@app.get("/health")
def health():
    return {"ok": True, "time": datetime.utcnow().isoformat()}

class QARequest(BaseModel):
    question: str

class QAResponse(BaseModel):
    answer: str
    cached: bool
    plan: dict
    results: list

@app.post("/qa", response_model=QAResponse)
def qa(req: QARequest):
    out = answer_question(req.question)
    if "error" in out:
        return QAResponse(answer=out["error"], cached=False, plan=out.get("plan", {}), results=out.get("results", []))
    return QAResponse(answer=out["answer"], cached=out["cached"], plan=out["plan"], results=out["results"])

# ---- Router Phase 3 ----
class RouteRequest(BaseModel):
    tenant_id: str
    actor_id: str
    actor_roles: list[str]
    channel: str = "cli"
    text: str

class RouteResponse(BaseModel):
    correlationId: str
    lane: str
    eventKey: str
    tenantId: str
    actor: str
    channel: str

@app.post("/route", response_model=RouteResponse)
def route(req: RouteRequest):
    routing = route_with_plan(
        req.text,
        tenant_id=req.tenant_id,
        actor_id=req.actor_id,
        actor_roles=req.actor_roles,
        existing_request_id=None,
        include_plan=False,
    )
    lane = routing["lane"]
    event_key = derive_event_key(req.text)
    cid = uuid.uuid4().hex
    log("routed", cid, req.actor_id, req.tenant_id, None, {"lane": lane, "eventKey": event_key})
    return RouteResponse(correlationId=cid, lane=lane, eventKey=event_key, tenantId=req.tenant_id, actor=req.actor_id, channel=req.channel)

class IngestRequest(RouteRequest):
    existing_request_id: str | None = None

class IngestResponse(BaseModel):
    correlationId: str
    lane: str
    eventKey: str
    answer: str | None = None
    plan: dict | None = None
    results: list | None = None

@app.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest):
    event_key = derive_event_key(req.text)
    cid = uuid.uuid4().hex
    routing = route_with_plan(
        req.text,
        tenant_id=req.tenant_id,
        actor_id=req.actor_id,
        actor_roles=req.actor_roles,
        existing_request_id=req.existing_request_id,
        include_plan=True,
    )
    lane = routing["lane"]
    if lane == "A":
        qa_plan = routing.get("qa_plan")
        out = answer_question(req.text, precomputed_plan=qa_plan)
        log("ingest_laneA", cid, req.actor_id, req.tenant_id, None, {"calls": out.get("plan", {}).get("calls", [])})
        return IngestResponse(correlationId=cid, lane=lane, eventKey=event_key, answer=out.get("answer"), plan=out.get("plan"), results=out.get("results"))
    if lane == "B":
        exec_plan_raw = routing.get("execution_plan")
        if not exec_plan_raw:
            return IngestResponse(correlationId=cid, lane=lane, eventKey=event_key, plan=None, answer="Unable to plan lane B action.")
        try:
            validated = planner.validate_plan(exec_plan_raw, req.existing_request_id)
        except ValueError as e:
            return IngestResponse(correlationId=cid, lane=lane, eventKey=event_key, plan=None, answer=str(e))
        log("ingest_laneB_plan", cid, req.actor_id, req.tenant_id, validated.get("shard"), {"plan": validated})
        return IngestResponse(correlationId=cid, lane=lane, eventKey=event_key, plan=validated)
    # HYBRID: answer first, propose plan (no execution)
    qa_plan = routing.get("qa_plan")
    exec_plan_raw = routing.get("execution_plan")
    ans = answer_question(req.text, precomputed_plan=qa_plan)
    exec_plan_validated = None
    if exec_plan_raw:
        try:
            exec_plan_validated = planner.validate_plan(exec_plan_raw, req.existing_request_id)
        except ValueError as e:
            exec_plan_validated = {"error": str(e)}
    log("ingest_hybrid", cid, req.actor_id, req.tenant_id, (exec_plan_validated or {}).get("shard") if isinstance(exec_plan_validated, dict) else None, {"qa_calls": ans.get("plan", {}).get("calls", []), "plan": exec_plan_validated})
    return IngestResponse(correlationId=cid, lane=lane, eventKey=event_key, answer=ans.get("answer"), plan=exec_plan_validated, results=ans.get("results"))
