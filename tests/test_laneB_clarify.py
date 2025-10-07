from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_execute_returns_clarify_block():
    # Plan creating a volunteer request
    plan_resp = client.post('/plan', json={
        'tenant_id':'t1','actor_id':'u1','actor_roles':['intern'],'text':'Invite 3 basketball and 2 volleyball volunteers'
    }).json()
    cid = plan_resp['correlation_id']
    plan_json = plan_resp['plan']
    exec_resp = client.post('/execute', json={
        'correlation_id': cid,
        'plan': plan_json,
        'tenant_id': 't1',
        'actor_id': 'u1',
        'actor_roles': ['intern']
    }).json()
    assert exec_resp['result']['ok'] is True
    clarify = exec_resp['result'].get('clarify')
    assert clarify is not None
    assert 'summary' in clarify
    # Clarifying question may be None depending on signals; ensure structure present
    assert 'clarifying_question' in clarify


def test_conversation_state_persisted():
    plan_resp = client.post('/plan', json={
        'tenant_id':'t1','actor_id':'u1','actor_roles':['intern'],'text':'Invite 1 basketball volunteer'
    }).json()
    cid = plan_resp['correlation_id']
    plan_json = plan_resp['plan']
    exec_resp = client.post('/execute', json={
        'correlation_id': cid,
        'plan': plan_json,
        'tenant_id': 't1',
        'actor_id': 'u1',
        'actor_roles': ['intern']
    }).json()
    clarify = exec_resp['result'].get('clarify')
    assert clarify is not None
    # No direct API yet to fetch conversation state; this test ensures presence only
