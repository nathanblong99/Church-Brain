from fastapi.testclient import TestClient
from main import app
import os

client = TestClient(app)

def test_execute_returns_clarify_block():
    # Plan creating a volunteer request
    plan_resp = client.post('/plan', json={
        'tenant_id':'t1','actor_id':'u1','actor_roles':['planning.create'],'text':'Invite 3 basketball and 2 volleyball volunteers'
    }).json()
    cid = plan_resp['correlation_id']
    plan_json = plan_resp['plan']
    exec_resp = client.post('/execute', json={
        'correlation_id': cid,
        'plan': plan_json,
        'tenant_id': 't1',
        'actor_id': 'u1',
        'actor_roles': ['planning.create']
    }).json()
    assert exec_resp['result']['ok'] is True
    clarify = exec_resp['result'].get('clarify')
    assert clarify is not None
    assert 'summary' in clarify
    # When LLM disabled fallback question appears
    if not os.getenv('CHURCH_BRAIN_USE_LLM'):
        assert clarify.get('clarifying_question') is not None


def test_conversation_state_persisted():
    plan_resp = client.post('/plan', json={
        'tenant_id':'t1','actor_id':'u1','actor_roles':['planning.create'],'text':'Invite 1 basketball volunteer'
    }).json()
    cid = plan_resp['correlation_id']
    plan_json = plan_resp['plan']
    exec_resp = client.post('/execute', json={
        'correlation_id': cid,
        'plan': plan_json,
        'tenant_id': 't1',
        'actor_id': 'u1',
        'actor_roles': ['planning.create']
    }).json()
    clarify = exec_resp['result'].get('clarify')
    assert clarify is not None
    # No direct API yet to fetch conversation state; this test ensures presence only
