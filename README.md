# Church Brain (Phase 1 Kernel Skeleton)

Mission: Less admin. More ministry.

This repository implements the Phase 1 kernel skeleton of the Church Brain per `COPILOT_BUILD_GUIDE.md`.

Two lanes, one truth: Lane A reads via Catalog Ops; Lane B acts via Verbs. Planner plans; Executor acts.

## Current Scope (Phase 1 Targets)
- Folder scaffold for lanes, verbs, allocator, authz, state, observability, methods, templates.
- Add in-memory state primitives (repositories, locks, idempotency, event log) — TODO
- Basic role-based authz stub enforcing default deny — TODO
- Allocator skeleton (room hold->confirm + volunteer overlap) — TODO
- Verb registry + core verbs (people.search, catalog.run stub, make_offers, wait_for_replies stub, assign, unassign, sms.send (dev), email.send (dev), notify.staff, create_record, update_record, schedule.timer) — TODO
- Executor orchestrating per-shard serialization, authz, idempotency, logging — TODO
- Planner stub producing JSON plan for simple natural language requests — TODO
- Methods data files: fill_roles, rebalance_roles — TODO
- Templates: invite, transfer, last_call, summaries — TODO
- FastAPI entrypoint with routing and correlation IDs — TODO
- Lane A placeholders (schema card, catalog ops stub) — TODO
- Catalyst scenario test — TODO

## Non-Goals (Phase 1)
- Real database integrations
- External SMS/email providers
- Lane A full Q&A logic
- Full policy NL->diff engine
- Observability production stack

## Dev Quickstart
```bash
# 1. Create and activate the venv (Python 3.11 recommended)
python3.11 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 3. Launch the API (loads .env automatically via repository bootstrap)
PYTHONPATH=src uvicorn src.main:app --host 127.0.0.1 --port 8100 --reload
```

## Database & Neon Setup
We now back the conversational history and guest pairing flows with Neon (PostgreSQL):

1. Provision a Neon project/branch and copy the connection string.
2. Add it to `.env` – e.g.
   ```
   DATABASE_URL_DEV=postgresql://user:pass@ep-...neon.tech/neondb?sslmode=require
   ```
   `src/state/repository.py` calls `load_dotenv()` on import, so the server sees the value without extra shell steps.
3. Apply the migrations in `db/migrations` (built in this repo):
   ```bash
   source .env
   psql "$DATABASE_URL_DEV" -f db/migrations/0001_initial.sql
   psql "$DATABASE_URL_DEV" -f db/migrations/0002_dev_seed.sql
   psql "$DATABASE_URL_DEV" -f db/migrations/0003_dev_people_seed.sql
   psql "$DATABASE_URL_DEV" -f db/migrations/0004_guest_pairing.sql
   ```
   Run them once per environment (dev/prod) or through your migration orchestrator.

### Seeded Tenants & Personas
- `0002_dev_seed.sql` inserts a deterministic tenant (`11111111-...1111`) plus a demo entity – useful for smoke tests.
- `0003_dev_people_seed.sql` creates 100 staff + 100 member records with UUIDs, households, volunteer tags, and realistic contact JSON. Handy helper queries:
  ```bash
  -- Sample a seeded member
  psql "$DATABASE_URL_DEV" -c "select entity_id, first_name, last_name from person where contact_json->>'seed_tag'='dev_seed_member' limit 5"

  -- View conversation messages
  psql "$DATABASE_URL_DEV" -c "select direction, body from message_log order by created_at desc limit 5"
  ```

## Manual Messaging Loop (Local)
With the server running on port 8100, you can simulate inbound messages via `curl`:

```bash
# Example: seeded member asking about a visit
curl -s -X POST http://127.0.0.1:8100/ingest \
  -H 'Content-Type: application/json' \
  -d '{
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "actor_id": "31d80aeb-b2df-4295-97fc-baccf54194a1",
        "actor_roles": [],
        "text": "I want to visit your church"
      }'
```

Conversation history persists to Neon (`conversation` + `message_log`), so you can inspect it later even after restarts.

## Guest Pairing Persistence
The existing `guest_pairing.*` verbs now write to real tables:

- `guest_connection_request`: rows created whenever guests accept the offer to sit with a volunteer.
- `guest_connection_volunteer`: tracks available hosts, status, and minimal metadata.

`guest_pairing.request_create` can consume either explicit arguments or a `visitor_id`. When given a `visitor_id`, the verb auto-hydrates the request (name, phone/email, household info) from the `person` table and stores contextual notes (e.g., preferred date). This keeps the workflow reliable while still allowing more modular verbs for future custom behavior (search volunteers, send notifications, etc.).

To execute a lane B plan that includes the pairing verb:
```bash
curl -s -X POST http://127.0.0.1:8100/execute \
  -H 'Content-Type: application/json' \
  -d '{
        "correlation_id": "<from /ingest plan>",
        "plan": {
          "steps": [
            {
              "verb": "guest_pairing.request_create",
              "args": {
                "visitor_id": "267a252f-8206-469c-b19f-23459b2117d5",
                "preferred_date": "2025-10-19",
                "notes": "User accepted offer to sit with a volunteer."
              }
            }
          ]
        },
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "actor_id": "267a252f-8206-469c-b19f-23459b2117d5",
        "actor_roles": []
      }'
```

Check the resulting pairing record:
```bash
psql "$DATABASE_URL_DEV" -c \
  "select guest_name, contact, status, notes from guest_connection_request order by created_at desc limit 5"
```

## Guiding Mantra
Two lanes, one truth.

## Quality Gates & Coverage Mapping (Phase 1 Snapshot)
Requirement -> Status
- Per-shard serialization: Executor lock via state.locks
- Authz at verb boundaries: authz.engine enforced in run_verb
- Idempotency (messages): Outbox idempotency_key suppression
- Allocator Hold->Confirm: allocator/allocator.py + room.* verbs
- Planner separate from executor: planner.planner.plan used before /execute
- Small verbs surface: registry lists verbs; room verbs added minimally
- Lane A placeholder only: schema_card + catalog_ops stub (no side effects)
- Catalyst scenario (simplified) test: tests/test_catalyst.py

Next Steps (Phase 1 polish):
- Expand Catalyst test to include override + room adjustment once room verbs integrated into planner.
- Add structured logging wiring (currently event_log + simple print JSON).

## Phase 2 (Lane A) Additions
Components:
- `laneA/schema_card.txt`: Versioned schema card (<=900 tokens) guiding Q&A.
- `laneA/catalog_ops/engine.py`: In-memory dataset + whitelisted Catalog Ops.
- `laneA/planner_llm.py`: LLM plan generator -> JSON calls list.
- `laneA/qa_flow.py`: Plan validation, execution, composition, semantic cache.
- `/qa` endpoint: POST {question} -> {answer, cached, plan, results}.

Example usage:
```
POST /qa {"question": "What time are services next Sunday?"}
=> { "answer": "Next Sunday services at Main are at 09:00, 11:00. Childcare is available. Need anything else about staff or events?", ... }
```

Cache: 5 minute TTL; fuzzy exact-match fallback; bypassed if question differs materially.

Tests: see `tests/test_laneA.py` for service times, staff lookup, FAQ cache, unknown op rejection.

## Phase 3 (Router & Hybrid)
Endpoints:
- POST `/route` -> { correlationId, lane, eventKey, tenantId, actor, channel }
- POST `/ingest` -> lane-specific outcome:
	- Lane A: { answer, plan(calls), results }
	- Lane B: { plan } (no execution performed automatically)
	- HYBRID: { answer (from Lane A flow), plan (Lane B proposal) }

Heuristics (classifier):
- Lane B triggers: invite, assign, book, rent, reserve, send, text, email, notify, create, update, adjust, hold, confirm, cancel
- Lane A triggers: when, where, what time, who, parking, childcare, schedule, event, service
- HYBRID: presence of at least one action cue + one informational cue in same message.

EventKey Format: <Topic|General>@<YYYY-MM-DD>@Main
- Topic extracted from keywords: Catalyst, Retreat, Camp, Outreach (default General).

Hybrid Contract: Provide informational answer first (read-only), then proposed operations plan (no side effects until explicitly executed via /execute).

Tests: `tests/test_router.py` validates lane classification, ingest behavior for A/B/HYBRID.

## Development Mega-Church Seed Data (Deterministic & Scalable)
File: `state/seed.py` (`load_dev_seed()` auto-invoked in `main.py`).

Purpose: Provide a realistic yet fully reproducible in-memory dataset for local development and tests. No randomness or wall-clock `utcnow()` variance is used during seeding.

Determinism Principles:
- Anchor date (default `2025-01-05`, a Sunday) controls all generated calendar entities.
- No `random` usage; all IDs and sequences are fixed & predictable.
- Stable IDs for services (`svc_<campus>_<date>_<time>`), events (`evt_###`), holds (`hold_<room>_n`), volunteer requests (`vr_static_n`).
- Reseeding without reset is idempotent (no duplication).

Environment Override:
Set `CHURCH_BRAIN_ANCHOR_DATE=YYYY-MM-DD` (must be a Sunday ideally) before process start to shift the entire calendar while keeping structure constant.

Included Data (scale=1):
- Campuses (Main, North, South)
- ~500 roles available when `CHURCH_BRAIN_SEED_SCALE=2` (base ~120)
- Staff: expanded role set (pastor, staff, intern, volunteer_coordinator, media, worship, kids, outreach, security, care, facilities, technical, production, hospitality, parking, followup); every 7th staff is multi-campus
- Services: 12 Sundays (09:00, 11:00) + 17:00 evening at Main every other week; childcare pattern deterministic
- Events: Up to 100 generated across weeks (Tue 18:00, Thu 18:00, Sat 09:00) rotating campuses and a fixed name list
- FAQs: 18+ entries (vision, giving, groups, baptism, membership, accessibility, translation, communion, etc.)
- Volunteer requests: 5 base + auto-generated to 30; some pre-filled assignments; one deliberately over-assigned for rebalance testing
- Rooms: Expanded metadata (gym, chapel, auditorium, kids_a, kids_b, studio, conference_a, cafe)
- Room holds: Confirmed + overlapping HOLD scenarios and additional scaled holds for allocator stress

Reset & Re-seed (Tests / Dev):
```
from state.seed import reset_db_state, load_dev_seed, snapshot_hash
reset_db_state(); load_dev_seed(); print(snapshot_hash())
```

Test Fixture Helper: `tests/fixtures.py` exposes `reset_and_seed()` returning the snapshot hash.

Snapshot Hash: `state.seed.snapshot_hash()` produces a SHA-256 over a normalized subset for reproducibility checks (used in `tests/test_reproducible_seed.py`). Changing the anchor date or seed module logic will alter the hash by design.

Scaling:
Set `CHURCH_BRAIN_SEED_SCALE` (integer) to multiply staff, weeks, events, volunteer requests, and room holds deterministically (no randomness introduced). Snapshot hash will change by design with scale.

Why deterministic? Ensures:
- Stable test expectations
- Easier diffs in planning/execution outputs
- Predictable QA answers (Lane A) independent of current real-world dates
- Repeatable performance or load experiments
- Reusable baseline for profiling (scale up without rewriting seed logic)

To simulate passage of time, prefer adjusting the anchor date (restart) instead of editing data ad hoc.

## LLM Integration (Optional Toggle)
The repository now supports an optional LLM-driven planning/composition path for both lanes.

Environment Flags:
- `CHURCH_BRAIN_USE_LLM=1` enables LLM planners (must be set).
- `LLM_PROVIDER=gemini` (only supported provider today).
- Gemini variables: `GOOGLE_API_KEY`, `GEMINI_MODEL` (e.g. `gemini-2.5-flash`).

Lane A Flow with LLM:
1. `planner_llm.plan_with_llm` builds JSON `{ "calls": [...] }` using allowed ops list.
2. JSON validated; single repair attempt if invalid.
3. Catalog ops executed.
4. `planner_llm.compose_with_llm` produces the final answer.

Lane B Flow with LLM:
1. `_plan_with_llm` returns `{ "steps": [...] }` (verbs only; no side effects).
2. If the LLM plan fails validation after one repair attempt, the request fails fast (no heuristic fallback).

- Safety note: if Gemini returns an error or credentials are missing, the planner/composer will raise and the request fails fast.

See `.env.example` for configuration scaffold.
