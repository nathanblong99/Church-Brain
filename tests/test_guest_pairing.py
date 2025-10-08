from laneB.verbs.registry import run_verb, VerbContext
from state.repository import GLOBAL_DB
from tests.fixtures import reset_and_seed


def make_ctx(roles: list[str]) -> VerbContext:
    return VerbContext(
        correlation_id="test-cid",
        tenant_id="tenant_dev",
        actor_id="tester",
        actor_roles=roles,
        shard=None,
    )


def test_guest_volunteer_register_upsert():
    reset_and_seed()
    ctx = make_ctx([])
    args = {
        "name": "Sam Volunteer",
        "phone": "555-3010",
        "age_range": "adult",
        "gender": "male",
        "marital_status": "married",
    }
    created = run_verb("guest_pairing.volunteer_register", args, ctx)
    assert created.ok and created.data["status"] == "created"
    volunteer_id = created.data["volunteer_id"]

    # update same phone with new profile info
    args_update = {
        "name": "Samuel Volunteer",
        "phone": "555-3010",
        "age_range": "senior",
        "gender": "male",
        "marital_status": "married",
        "active": False,
    }
    updated = run_verb("guest_pairing.volunteer_register", args_update, ctx)
    assert updated.ok and updated.data["status"] == "updated"
    assert updated.data["volunteer_id"] == volunteer_id

    vol = GLOBAL_DB.get_guest_connection_volunteer(volunteer_id)
    assert vol is not None
    assert vol.name == "Samuel Volunteer"
    assert vol.age_range == "senior"
    assert vol.active is False


def test_guest_pairing_flow_match_and_assign():
    reset_and_seed()
    guest_ctx = make_ctx([])
    create_res = run_verb(
        "guest_pairing.request_create",
        {
            "guest_name": "Curious Casey",
            "contact": "casey@example.com",
            "age_range": "adult",
            "gender": "female",
            "marital_status": "single",
            "notes": "Prefers first service.",
        },
        guest_ctx,
    )
    assert create_res.ok
    request_id = create_res.data["request_id"]

    staff_ctx = make_ctx(["staff"])
    match_res = run_verb(
        "guest_pairing.match",
        {"request_id": request_id, "limit": 5},
        staff_ctx,
    )
    assert match_res.ok
    matches = match_res.data["matches"]
    assert matches, "Expected at least one volunteer suggestion"

    # ensure already-matched volunteer (guest_volunteer_6) is filtered out
    matched_ids = {m["volunteer_id"] for m in matches}
    assert "guest_volunteer_6" not in matched_ids

    top_choice = matches[0]
    assign_res = run_verb(
        "guest_pairing.assign",
        {"request_id": request_id, "volunteer_id": top_choice["volunteer_id"]},
        staff_ctx,
    )
    assert assign_res.ok

    stored_request = GLOBAL_DB.get_guest_connection_request(request_id)
    assert stored_request is not None
    assert stored_request.status == "MATCHED"
    assert stored_request.volunteer_id == top_choice["volunteer_id"]

    volunteer = GLOBAL_DB.get_guest_connection_volunteer(top_choice["volunteer_id"])
    assert volunteer is not None
    assert volunteer.currently_assigned_request_id == request_id
