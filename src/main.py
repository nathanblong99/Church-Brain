from __future__ import annotations
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from datetime import datetime
import uuid
from dotenv import load_dotenv
from laneB.planner import planner
from laneB.executor.executor import Executor
from psycopg import connect
from psycopg.types.json import Json
from state.event_log import log
from laneA.qa_flow import answer_question
from router.llm_router import route_with_plan
from router.classifier import derive_event_key
from state.seed import load_dev_seed
from state.repository import GLOBAL_DB

app = FastAPI(title="Church Brain Kernel Phase 1")

# Load development mega-church seed data (idempotent)
load_dotenv()
load_dev_seed()

HISTORY_LIMIT = 12


def _format_history_for_prompt(tenant_id: str, actor_id: str) -> str | None:
    history = GLOBAL_DB.get_conversation_history(tenant_id, actor_id, limit=HISTORY_LIMIT)
    if not history:
        return None
    lines: list[str] = []
    for msg in history:
        speaker = "User" if msg.role == "user" else "Assistant"
        lines.append(f"{speaker}: {msg.content}")
    text = "\n".join(lines)
    if len(text) > 2000:
        text = text[-2000:]
    return text

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
    history_text = _format_history_for_prompt(msg.tenant_id, msg.actor_id)
    plan_json = planner.plan(
        msg.tenant_id,
        msg.actor_id,
        msg.text,
        msg.existing_request_id,
        conversation_history=history_text,
    )
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
    history_text = _format_history_for_prompt(req.tenant_id, req.actor_id)
    routing = route_with_plan(
        req.text,
        tenant_id=req.tenant_id,
        actor_id=req.actor_id,
        actor_roles=req.actor_roles,
        existing_request_id=None,
        include_plan=False,
        conversation_history=history_text,
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
    history_text = _format_history_for_prompt(req.tenant_id, req.actor_id)
    routing = route_with_plan(
        req.text,
        tenant_id=req.tenant_id,
        actor_id=req.actor_id,
        actor_roles=req.actor_roles,
        existing_request_id=req.existing_request_id,
        include_plan=True,
        conversation_history=history_text,
    )
    lane = routing["lane"]
    assistant_text: str | None = None
    plan_payload: dict | None = None
    results_payload: list | None = None

    if lane == "SMALLTALK":
        assistant_text = routing.get("smalltalk_response") or "Hi there! I'm Church Brain—how can I help today?"
        log("ingest_smalltalk", cid, req.actor_id, req.tenant_id, None, {"text": assistant_text})
        response = IngestResponse(
            correlationId=cid,
            lane=lane,
            eventKey=event_key,
            answer=assistant_text,
            plan=None,
            results=None,
        )
    elif lane == "A":
        qa_plan = routing.get("qa_plan")
        out = answer_question(req.text, precomputed_plan=qa_plan, conversation_history=history_text)
        log(
            "ingest_laneA",
            cid,
            req.actor_id,
            req.tenant_id,
            None,
            {"calls": out.get("plan", {}).get("calls", [])},
        )
        assistant_text = out.get("answer") or out.get("error")
        plan_payload = out.get("plan") if isinstance(out.get("plan"), dict) else None
        results_payload = out.get("results")
        response = IngestResponse(
            correlationId=cid,
            lane=lane,
            eventKey=event_key,
            answer=assistant_text,
            plan=plan_payload,
            results=results_payload,
        )
    elif lane == "B":
        exec_plan_raw = routing.get("execution_plan")
        if not exec_plan_raw:
            assistant_text = "Unable to plan lane B action."
            response = IngestResponse(
                correlationId=cid,
                lane=lane,
                eventKey=event_key,
                plan=None,
                answer=assistant_text,
            )
        else:
            try:
                validated = planner.validate_plan(exec_plan_raw, req.existing_request_id)
            except ValueError as e:
                assistant_text = str(e)
                response = IngestResponse(
                    correlationId=cid,
                    lane=lane,
                    eventKey=event_key,
                    plan=None,
                    answer=assistant_text,
                )
            else:
                log(
                    "ingest_laneB_plan",
                    cid,
                    req.actor_id,
                    req.tenant_id,
                    validated.get("shard"),
                    {"plan": validated},
                )
                plan_payload = validated
                response = IngestResponse(
                    correlationId=cid,
                    lane=lane,
                    eventKey=event_key,
                    plan=validated,
                )
    else:  # HYBRID
        qa_plan = routing.get("qa_plan")
        exec_plan_raw = routing.get("execution_plan")
        ans = answer_question(req.text, precomputed_plan=qa_plan, conversation_history=history_text)
        exec_plan_validated = None
        if exec_plan_raw:
            try:
                exec_plan_validated = planner.validate_plan(exec_plan_raw, req.existing_request_id)
            except ValueError as e:
                exec_plan_validated = {"error": str(e)}
        log(
            "ingest_hybrid",
            cid,
            req.actor_id,
            req.tenant_id,
            (exec_plan_validated or {}).get("shard") if isinstance(exec_plan_validated, dict) else None,
            {"qa_calls": ans.get("plan", {}).get("calls", []), "plan": exec_plan_validated},
        )
        assistant_text = ans.get("answer") or ans.get("error")
        plan_payload = exec_plan_validated
        results_payload = ans.get("results")
        response = IngestResponse(
            correlationId=cid,
            lane=lane,
            eventKey=event_key,
            answer=assistant_text,
            plan=plan_payload,
            results=results_payload,
        )

    GLOBAL_DB.append_conversation_message(req.tenant_id, req.actor_id, "user", req.text)
    if assistant_text:
        GLOBAL_DB.append_conversation_message(req.tenant_id, req.actor_id, "assistant", assistant_text)

    return response


def _get_database_url() -> str:
    db_url = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL_DEV")
    if not db_url:
        raise RuntimeError("DATABASE_URL or DATABASE_URL_DEV must be set for the test UI.")
    return db_url


def _create_guest_actor(
    tenant_id: str,
    first_name: str,
    last_name: str,
    phone: str,
    email: str,
) -> uuid.UUID:
    actor_uuid = uuid.uuid4()
    household_uuid = uuid.uuid4()
    with connect(_get_database_url(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into household (id, tenant_id, name, address_json)
                values (%s, %s, %s, %s)
                on conflict (id) do nothing
                """,
                (
                    household_uuid,
                    tenant_id,
                    f"{last_name or first_name} Household",
                    Json(
                        {
                            "street": "123 Guest Lane",
                            "city": "Springfield",
                            "state": "IL",
                            "zip": "62701",
                        }
                    ),
                ),
            )
            cur.execute(
                """
                insert into entity (id, tenant_id, type)
                values (%s, %s, %s)
                on conflict (id) do nothing
                """,
                (actor_uuid, tenant_id, "guest"),
            )
            cur.execute(
                """
                insert into person (
                    entity_id,
                    tenant_id,
                    first_name,
                    last_name,
                    gender,
                    contact_json,
                    primary_household_id
                ) values (%s, %s, %s, %s, %s, %s, %s)
                on conflict (entity_id) do nothing
                """,
                (
                    actor_uuid,
                    tenant_id,
                    first_name or "Guest",
                    last_name or "Visitor",
                    "unknown",
                    Json(
                        {
                            "phone": phone,
                            "email": email,
                            "seed_tag": "test_ui_guest",
                        }
                    ),
                    household_uuid,
                ),
            )
            cur.execute(
                """
                insert into person_household (
                    person_id,
                    household_id,
                    tenant_id,
                    role_in_household,
                    is_primary
                ) values (%s, %s, %s, %s, %s)
                on conflict do nothing
                """,
                (actor_uuid, household_uuid, tenant_id, "Head", True),
            )
    return actor_uuid


class TestSendRequest(BaseModel):
    message: str
    tenant_id: str = "11111111-1111-1111-1111-111111111111"
    actor_id: str | None = None
    use_new_actor: bool = False
    first_name: str | None = "Guest"
    last_name: str | None = "Visitor"
    phone: str | None = "(872) 555-0199"
    email: str | None = "guest@example.com"
    actor_roles: list[str] = []


@app.post("/test/send")
def test_send(req: TestSendRequest):
    try:
        tenant_uuid = uuid.UUID(req.tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid tenant_id: {req.tenant_id}") from exc

    if req.use_new_actor or not req.actor_id:
        actor_uuid = _create_guest_actor(
            str(tenant_uuid),
            (req.first_name or "Guest").strip(),
            (req.last_name or "Visitor").strip(),
            (req.phone or "").strip(),
            (req.email or "guest@example.com").strip(),
        )
    else:
        try:
            actor_uuid = uuid.UUID(req.actor_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid actor_id: {req.actor_id}") from exc

    ingest_request = IngestRequest(
        tenant_id=str(tenant_uuid),
        actor_id=str(actor_uuid),
        actor_roles=req.actor_roles,
        channel="test_ui",
        text=req.message,
        existing_request_id=None,
    )

    response = ingest(ingest_request)
    return {
        "actor_id": str(actor_uuid),
        "tenant_id": str(tenant_uuid),
        "ingest": response,
    }


@app.get("/test/chat", response_class=HTMLResponse)
def test_chat_ui():
    return HTMLResponse(
        """<!DOCTYPE html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <title>Church Brain Test Chat</title>
    <style>
      body { font-family: Arial, sans-serif; margin: 2rem; background: #f5f5f5; }
      .card { max-width: 720px; margin: 0 auto; background: white; border-radius: 12px; padding: 24px; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.12); }
      label { display: block; font-weight: 600; margin-top: 16px; }
      input, textarea, select { width: 100%; padding: 10px 12px; border-radius: 8px; border: 1px solid #d1d5db; margin-top: 6px; font-size: 0.95rem; }
      textarea { min-height: 120px; resize: vertical; }
      button { margin-top: 20px; padding: 12px 18px; border: none; border-radius: 8px; background: #2563eb; color: white; font-size: 1rem; cursor: pointer; }
      button:hover { background: #1e50c5; }
      .row { display: flex; gap: 12px; }
      .row > div { flex: 1; }
      .hidden { display: none; }
      pre { white-space: pre-wrap; word-wrap: break-word; background: #0f172a; color: #f8fafc; padding: 16px; border-radius: 8px; margin-top: 20px; }
    </style>
  </head>
  <body>
    <div class=\"card\">
      <h2>Church Brain Test Chat</h2>
      <p>Use this lightweight UI to send messages into the running FastAPI instance. Leave Actor ID empty to create a new guest automatically.</p>
      <form id=\"chat-form\">
        <label>Tenant ID
          <input type=\"text\" id=\"tenantId\" value=\"11111111-1111-1111-1111-111111111111\" required />
        </label>
        <label>Actor Mode
          <select id=\"actorMode\">
            <option value=\"new\" selected>Create new guest</option>
            <option value=\"existing\">Use existing actor UUID</option>
          </select>
        </label>
        <div id=\"existing-fields\" class=\"hidden\">
          <label>Existing Actor UUID
            <input type=\"text\" id=\"actorId\" placeholder=\"e.g. 31d80aeb-b2df-4295-97fc-baccf54194a1\" />
          </label>
        </div>
        <div id=\"new-fields\">
          <div class=\"row\">
            <div>
              <label>First Name
                <input type=\"text\" id=\"firstName\" value=\"Guest\" />
              </label>
            </div>
            <div>
              <label>Last Name
                <input type=\"text\" id=\"lastName\" value=\"Visitor\" />
              </label>
            </div>
          </div>
          <div class=\"row\">
            <div>
              <label>Phone
                <input type=\"text\" id=\"phone\" value=\"(872) 555-0199\" />
              </label>
            </div>
            <div>
              <label>Email
                <input type=\"email\" id=\"email\" value=\"guest@example.com\" />
              </label>
            </div>
          </div>
        </div>
        <label>Actor Roles (comma separated)
          <input type=\"text\" id=\"roles\" placeholder=\"e.g. volunteer, usher\" />
        </label>
        <label>Message
          <textarea id=\"message\" placeholder=\"Type the message Church Brain should receive...\" required></textarea>
        </label>
        <button type=\"submit\">Send Message</button>
      </form>
      <pre id=\"output\">Awaiting input...</pre>
    </div>
    <script>
      const actorMode = document.getElementById('actorMode');
      const existingFields = document.getElementById('existing-fields');
      const newFields = document.getElementById('new-fields');
      actorMode.addEventListener('change', () => {
        if (actorMode.value === 'existing') {
          existingFields.classList.remove('hidden');
          newFields.classList.add('hidden');
        } else {
          existingFields.classList.add('hidden');
          newFields.classList.remove('hidden');
        }
      });

      const form = document.getElementById('chat-form');
      const output = document.getElementById('output');
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const payload = {
          tenant_id: document.getElementById('tenantId').value.trim(),
          message: document.getElementById('message').value,
          actor_roles: document.getElementById('roles').value
            .split(',')
            .map((role) => role.trim())
            .filter(Boolean),
        };

        if (actorMode.value === 'existing') {
          payload.actor_id = document.getElementById('actorId').value.trim();
          payload.use_new_actor = false;
        } else {
          payload.use_new_actor = true;
          payload.first_name = document.getElementById('firstName').value;
          payload.last_name = document.getElementById('lastName').value;
          payload.phone = document.getElementById('phone').value;
          payload.email = document.getElementById('email').value;
        }

        output.textContent = 'Sending...';
        try {
          const res = await fetch('/test/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          const data = await res.json();
          output.textContent = JSON.stringify(data, null, 2);
        } catch (err) {
          output.textContent = 'Error: ' + err;
        }
      });
    </script>
  </body>
</html>
"""
    )
