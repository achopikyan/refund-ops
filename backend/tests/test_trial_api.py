from fastapi.testclient import TestClient
from refundops.main import create_app
from conftest import raw,csv_text,small_policy,complete_model_fixture


def test_trial_api_and_recorded_quality_findings(tmp_path):
    with TestClient(create_app(tmp_path/"trial-api.sqlite3",seed=False),headers={'X-Demo-Role':'manager'}) as client:
        store=client.app.state.store
        p=small_policy(store.policy()["data"],7500)
        settings={"min_prospective_auto":1,"min_changed_cases":1,"min_shadow_hours":0.0,"max_error_bps":10000,"max_projected_loss_cents":10000000}
        created=client.post('/api/trials',json={"policy":p,"settings":settings})
        assert created.status_code==200
        eid=created.json()["id"]
        assert client.post(f'/api/trials/{eid}/promote',json={"reason":"bypass"}).status_code==409
        assert client.post(f'/api/trials/{eid}/start').status_code==409
        assert client.post(f'/api/trials/{eid}/backtest').status_code==200
        assert client.post(f'/api/trials/{eid}/start').status_code==200
        text=csv_text(raw(amount_usd="60"))
        preview=client.post('/api/imports/preview',files={"file":("new.csv",text,"text/csv")},data={"kind":"pending"}).json()
        assert client.post('/api/imports/'+preview["id"]+'/commit').status_code==200
        complete_model_fixture(store,store.request('TEST-1'))
        report=client.get('/api/trials/'+eid).json();oid=report["observations"][0]["id"]
        assert client.post(f'/api/trials/{eid}/observations/{oid}/review',headers={'X-Demo-Role':'reviewer'},json={"allowed_cents":6000,"note":"No shadow review endpoint"}).status_code==403
        obj=client.get('/api/requests').json()[0]
        assert client.post(f'/api/requests/{obj["id"]}/decisions',headers={'X-Demo-Role':'reviewer'},json={
            'version':obj['version'],'action':'approved','amount_cents':6000,'reason':'Verified fixture through the normal workflow',
            'idempotency_key':'normal-review-reference'}).status_code==200
        assert client.post(f'/api/trials/{eid}/promote',json={"reason":"API test only"}).status_code==200
        assert store.apply_automation()['applied']==[]
        preview=client.post('/api/imports/preview',files={'file':('new-auto.csv',csv_text(raw(request_id='AUTO-NEXT',amount_usd='60')),'text/csv')},data={'kind':'pending'}).json()
        client.post('/api/imports/'+preview['id']+'/commit')
        complete_model_fixture(store,store.request('AUTO-NEXT'))
        assert len(store.apply_automation()["applied"])==1
        obj=next(r for r in client.get('/api/requests').json() if r['external_id']=='AUTO-NEXT')
        client.post(f'/api/requests/{obj["id"]}/outcomes',headers={'X-Demo-Role':'reviewer'},json={"type":"audit_fail","note":"Post-release error found"})
        assert client.get('/api/health').json()["state"]["mode"]=="simulate"
        assert client.get('/api/release-budget').json()["release_spent_cents"]==6000
        assert client.get('/api/rule-discovery').json() is None
        assert client.post('/api/rule-discovery',json={"adverse_bps":-1}).status_code==422
        assert client.post('/api/rule-discovery',json={}).status_code==200


def test_settings_are_immutable_and_model_change_stales_trial(tmp_path, monkeypatch):
    for name in ('AI_PROVIDER','OPENAI_API_KEY','OPENROUTER_API_KEY','OPENAI_MODEL','OPENROUTER_MODEL'):
        monkeypatch.setenv(name, '')
    with TestClient(create_app(tmp_path/"freeze.sqlite3",seed=False),headers={'X-Demo-Role':'manager'}) as client:
        assert client.get('/api/settings/llm').json()['provider'] == 'openai'
        policy=client.app.state.store.policy()["data"]
        eid=client.post('/api/trials',json={"policy":policy}).json()["id"]
        assert client.put('/api/trials/'+eid,json={"settings":{"min_prospective_auto":1}}).status_code==405
        response = client.put('/api/settings/llm',json={"provider":"openai","model":"gpt-different-test-model"})
        assert response.status_code == 200
        assert client.post(f'/api/trials/{eid}/backtest').status_code==409
