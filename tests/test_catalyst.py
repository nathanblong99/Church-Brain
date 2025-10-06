from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_basic_volunteer_plan_and_execute():
    msg = {
        "tenant_id": "t1",
        "actor_id": "intern1",
        "actor_roles": ["intern"],
        "text": "Invite 4 volunteers (2 basketball, 2 volleyball)."
    }
    plan_resp = client.post("/plan", json=msg).json()
    assert "plan" in plan_resp
    corr = plan_resp["correlation_id"]
    exec_req = {
        "correlation_id": corr,
        "plan": plan_resp["plan"],
        "tenant_id": "t1",
        "actor_id": "intern1",
        "actor_roles": ["intern"],
    }
    exec_resp = client.post("/execute", json=exec_req).json()
    # intern lacks volunteer.manage, so only create_record should succeed (planning.create allowed)
    if exec_resp["result"]["ok"]:
        # Acceptable minimal path
        assert exec_resp["result"]["results"][0]["verb"] == "create_record"
    else:
        # Plan may have been empty
        assert exec_resp["result"]["error"].startswith("plan_invalid") is False
