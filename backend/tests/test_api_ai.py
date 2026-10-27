import json
import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from refundops.main import create_app
from refundops.llm import ProviderError
from refundops.providers import AIProvider
import refundops.providers as providers
from openai import OpenAI, DefaultHttpx2Client
from refundops.domain import normalize
from conftest import raw,csv_text

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path/"api.sqlite3",seed=False),headers={"X-Demo-Role":"manager"}) as c:yield c
def test_api_full_reviewer_flow(client):
    upload=client.post("/api/imports/preview",files={"file":("requests.csv",csv_text(raw()),"text/csv")},data={"kind":"pending","date_format":"DMY"})
    assert upload.status_code==200
    assert client.post("/api/imports/"+upload.json()["id"]+"/commit").status_code==200
    client.headers['X-Demo-Role']='reviewer'
    r=client.get("/api/requests").json()[0];rid=r["id"]
    payload={"version":r['version'],"action":"approved","amount_cents":4000,"reason":"Verified source","idempotency_key":"api-decision-1"}
    decision=client.post(f"/api/requests/{rid}/decisions",json=payload)
    assert decision.status_code==200 and decision.json()["ledger"]["status"]=="simulated_succeeded"
    assert client.post(f"/api/requests/{rid}/decisions",json=payload).json()["decision"]==decision.json()["decision"]
    assert client.post(f"/api/requests/{rid}/outcomes",json={"type":"audit_pass","note":"All records reconcile"}).status_code==200
    assert "TEST-1" in client.get("/api/exports/decisions").text
@pytest.mark.parametrize("origin",["https://evil.example","http://localhost.evil.example:8000","http://127.0.0.1:123@evil.example","null"])
def test_cross_origin_rejected(client,origin):assert client.get("/api/requests",headers={"Origin":origin}).status_code==403
def test_local_origin(client):assert client.get("/api/requests",headers={"Origin":"http://localhost:5173"}).status_code==200
def test_key_not_returned(client):
    key="sk-or-test-credential-never-print-this"
    r=client.put("/api/settings/llm",json={"key":key,"model":"provider/model"})
    assert r.status_code==200 and key not in r.text and key not in client.get("/api/health").text
    assert client.delete("/api/settings/llm").json()["configured"] is False
def test_unsupported_decision_schema(client):assert client.post("/api/requests/none/decisions",headers={"X-Demo-Role":"reviewer"},json={"version":1,"action":"send_money"}).status_code==422

@pytest.mark.parametrize('payload',[
    {'type':'photo','note':'Not an outcome'},
    {'type':'chargeback','note':{'text':'Wrong JSON type'}},
    {'type':'audit_pass','note':None},
    {'type':'audit_pass','note':'ok','amount_cents':1000},
])
def test_outcome_payload_is_validated_before_request_lookup(client,payload):
    response=client.post('/api/requests/none/outcomes',headers={'X-Demo-Role':'reviewer'},json=payload)
    assert response.status_code==422
def test_ai_offline_error_is_actionable(client):
    client.delete("/api/settings/llm")
    store=client.app.state.store
    batch=store.import_preview(csv_text(raw()),'in.csv','pending');store.import_commit(batch['id'])
    analysis=client.get('/api/requests/TEST-1').json()['analysis']
    assert analysis['status']=='unavailable' and 'configure the AI connection' in analysis['error']
    assert client.post('/api/analyse').status_code in (404,405)
def provider(store,monkeypatch,handler):
    def factory(**kwargs):
        kwargs['http_client'].close()
        kwargs['http_client']=DefaultHttpx2Client(transport=httpx.MockTransport(handler),follow_redirects=False)
        return OpenAI(**kwargs)
    monkeypatch.setattr(providers,'OpenAI',factory)
    llm=AIProvider(store)
    llm.configure('sk-or-test-credential-for-tests-only',model='openai/gpt-6.1-sol',provider='openrouter')
    return llm

def success(payload):
    if 'facts' in payload:
        from refundops.domain import FACTS
        payload={'assessed_facts':sorted(FACTS),**payload}
    return {"id":"gen-test","provider":"test","usage":{"prompt_tokens":10,"completion_tokens":20,"cost":0.001},"choices":[{"finish_reason":"stop","message":{"content":json.dumps(payload)}}]}
def test_ai_input_allowlist_and_cache(store,monkeypatch):
    sent=[]
    def handler(request):sent.append(json.loads(request.content));return httpx.Response(200,json=success({"summary":"No findings","facts":[]}))
    llm=provider(store,monkeypatch,handler)
    r=normalize(raw(outcome_note="SECRET FUTURE",customer_id="SECRET ID",decision="approved"))
    a=llm.extract(r,[]);b=llm.extract(r,[])
    assert a==b and len(sent)==1
    assert "SECRET" not in json.dumps(sent)
    assert sent[0]["provider"]=={"require_parameters":True,"allow_fallbacks":False}
    assert store.metrics()["ai"]["calls"]==1
@pytest.mark.parametrize("code",[401,402,429,500])
def test_provider_http_errors_do_not_pay(store,monkeypatch,code):
    llm=provider(store,monkeypatch,lambda _:httpx.Response(code,json={"error":"credential might be echoed here"}))
    with pytest.raises(ProviderError) as ex:llm.extract(normalize(raw()),[])
    assert "credential" not in str(ex.value) and store.metrics()["refund_count"]==0
def test_timeout(store,monkeypatch):
    def timeout(request):raise httpx.ReadTimeout("network",request=request)
    llm=provider(store,monkeypatch,timeout)
    with pytest.raises(ProviderError):llm.extract(normalize(raw()),[])
    assert store.metrics()["ai"]["failures"]==1
def test_bad_quote_not_cached(store,monkeypatch):
    llm=provider(store,monkeypatch,lambda _:httpx.Response(200,json=success({"summary":"fabricated","facts":[{"name":"photo","value":"yes","source":"support_note","quote":"nonexistent"}]})))
    with pytest.raises(ProviderError,match="citation"):llm.extract(normalize(raw()),[])
    with store.connect() as c:assert c.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0]==0
    assert store.metrics()["ai"]["failures"]==1

def test_validation_retry_is_bounded_and_only_valid_output_is_cached(store,monkeypatch):
    sent=[]
    def handler(request):
        sent.append(json.loads(request.content))
        quote='invented quotation' if len(sent)==1 else 'photos clear'
        response=success({'summary':'Photo received','facts':[{'name':'photo','value':'yes','source':'support_note','quote':quote}]})
        response['id']='retry-'+str(len(sent))
        return httpx.Response(200,json=response)
    llm=provider(store,monkeypatch,handler)
    evidence=llm.extract(normalize(raw(support_note='photos clear')),[])
    assert evidence['complete'] and evidence['facts']['photo']['quote']=='photos clear'
    assert len(sent)==2
    feedback=json.loads(sent[1]['messages'][1]['content'])['validation_feedback']
    assert feedback==['Source quotation could not be verified for photo']
    with store.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM llm_cache').fetchone()[0]==1
    assert store.metrics()['ai']['failures']==1
def test_model_malformed_json(store,monkeypatch):
    data=success({});data["choices"][0]["message"]["content"]="not json"
    llm=provider(store,monkeypatch,lambda _:httpx.Response(200,json=data))
    with pytest.raises(ProviderError):llm.extract(normalize(raw()),[])
def test_reported_cost_threshold_blocks_calls(store,monkeypatch):
    calls=[]
    llm=provider(store,monkeypatch,lambda _:calls.append(1))
    llm.budget=0
    with pytest.raises(ProviderError,match="reported-cost threshold"):llm.extract(normalize(raw()),[])
    assert not calls

def test_network_error_has_safe_machine_readable_code(store,monkeypatch):
    def blocked(request):raise httpx.ConnectError('[WinError 10013] SECRET transport detail',request=request)
    llm=provider(store,monkeypatch,blocked)
    with pytest.raises(ProviderError) as ex:llm.extract(normalize(raw()),[])
    assert ex.value.code=='network_blocked'
    assert 'SECRET' not in str(ex.value)


@pytest.mark.parametrize('method,path',[
    ('POST','/api/policies/generate'),('POST','/api/policies/validate'),
    ('POST','/api/policies/propose'),('POST','/api/policies/preview'),
    ('POST','/api/policies/activate'),('POST','/api/automation/simulate'),
    ('POST','/api/execute-approved'),('GET','/api/feedback'),('GET','/api/jobs/old'),
])
def test_retired_manual_execution_and_legacy_endpoints_are_not_exposed(client,method,path):
    assert client.request(method,path,json={} if method=='POST' else None).status_code in (404,405)
    assert client.app.state.store.metrics()['refund_count']==0
