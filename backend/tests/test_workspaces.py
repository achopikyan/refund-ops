from conftest import shadow_reference_fixture
import json
import pytest
from fastapi.testclient import TestClient
from refundops.main import create_app
from refundops.storage import Store, Conflict
from refundops.domain import initial_policy, normalize, pending_evidence, evaluate
from conftest import ROOT, raw, csv_text

def test_roles_enforced_without_claiming_authentication(tmp_path):
    with TestClient(create_app(tmp_path/'roles.sqlite3',seed=False)) as client:
        assert client.get('/api/health').status_code==200
        assert client.get('/api/requests').status_code==401
        for role,method,path in [('reviewer','get','/api/policies'),('reviewer','get','/api/settings/llm'),
                                 ('reviewer','post','/api/automation/simulate'),('manager','post','/api/requests/none/decisions')]:
            assert getattr(client,method)(path,headers={'X-Demo-Role':role}).status_code==403
        assert client.get('/api/requests',headers={'X-Demo-Role':'reviewer'}).status_code==200
        assert client.get('/api/policies',headers={'X-Demo-Role':'manager'}).status_code==200

def test_fresh_manual_baseline_cannot_execute_without_an_approval_rule(tmp_path):
    store=Store(tmp_path/'fresh.sqlite3')
    batch=store.import_preview(csv_text(raw()),'fresh.csv','pending');store.import_commit(batch['id'])
    obj=store.request('TEST-1')
    assert obj['evaluation']['action']!='auto_approve'
    assert store.mode('simulate')['mode']=='simulate'
    with pytest.raises(Conflict):store.decide(obj['id'],obj['version'],'approved',4000,'Bypass','automation','fresh-bypass',True)
    assert store.metrics()['refund_count']==0

def test_first_policy_is_traceable_history_derived_and_never_active(tmp_path):
    store=Store(tmp_path/'first.sqlite3');store.seed(ROOT/'data')
    active=store.policy()['id'];before=store.metrics()['refund_count']
    draft=store.generate_initial()
    assert draft['status']=='draft' and 'small_customer_enabled' not in draft['data']
    mined=[r for r in draft['data']['rules'] if r['id'].startswith('mined-')]
    assert mined and all(r['conditions'] for r in mined)
    source=store.draft_source(draft['id'])
    assert source['input_rows']==248 and source['baseline']['unknown_outcomes']>0
    assert all(r['source'] for r in source['rules'])
    assert source['data_hash'] and source['training_count']>source['later_count']
    assert store.policy()['id']==active and store.metrics()['refund_count']==before
    # An entirely different dataset must not reproduce a decorative fixed starter set.
    other=Store(tmp_path/'other.sqlite3')
    history=[raw(request_id=f'H{i}',customer_id=f'C{i}',decision='approved',decided_by='reviewer',review_minutes='10',stated_reason='wrong_size',amount_usd='20',requested_at=f'2026-08-{i+1:02d}') for i in range(20)]
    info=other.import_preview(csv_text(*history),'history.csv','history');other.import_commit(info['id'])
    result=other.generate_initial()
    assert result['source']['data_hash']!=source['data_hash']
    assert all(r['conditions'][0]['value']=='wrong_size' for r in result['data']['rules'] if r['id'].startswith('mined-'))

def test_no_history_no_generated_policy(tmp_path):
    with pytest.raises(ValueError,match='Import historical'):Store(tmp_path/'empty.sqlite3').generate_initial()

def test_reopen_cannot_repay_and_feedback_has_policy_and_rule(one):
    store,obj=one
    obj=store.decide(obj['id'],obj['version'],'approved',4000,'Checked','Alex','original-refund')
    reopened=store.reopen(obj['id'],obj['version'],'Customer appealed')
    assert reopened['follow_up']['closed']==0 and reopened['status']=='resolved'
    with pytest.raises(Conflict):store.decide(obj['id'],reopened['version'],'approved',4000,'Again','Alex','second-payment')
    assert store.metrics()['refund_count']==1
    assert store.feedback()['groups'][0]['policy_id']==store.policy()['id']
    assert store.feedback()['groups'][0]['rule_id']=='test-small-refund'

def test_hold_and_waiting_block_payment(one):
    store,obj=one
    held=store.workflow(obj['id'],obj['version'],'hold','Alex','Carrier incident')
    with pytest.raises(Conflict,match='resume'):store.decide(obj['id'],held['version'],'approved',4000,'Checked','Alex','hold-attempt')
    resumed=store.workflow(obj['id'],held['version'],'resume','Alex','Carrier has cleared incident')
    assert resumed['status']=='ready'

def test_general_policy_hold_and_same_route_backtest_changes(store):
    p=initial_policy();p['rules'].insert(0,{'id':'hold-region','name':'Hold electronics during incident','priority':1000,'match':'all','enabled':True,'action':'hold','conditions':[{'field':'category','op':'eq','value':'electronics'}]})
    r=normalize(raw(category='electronics'));assert evaluate(r,pending_evidence(r),p)['action']=='hold'
    hist=store.import_preview(csv_text(raw(decision='approved',amount_usd='350')),'history.csv','history');store.import_commit(hist['id'])
    p=initial_policy();p['rules'][0]['name']='New explanation for same review route'
    ex=store.create_experiment(p);report=store.backtest_experiment(ex['id'])
    assert report['changed']==1 and report['new_auto']==report['old_auto']==0

def test_pii_masked_before_ai_call(store,monkeypatch):
    import httpx2 as httpx
    from test_api_ai import provider,success
    sent=[]
    def handler(request):
        sent.append(json.loads(request.content));return httpx.Response(200,json=success({'summary':'Delivery photo received','facts':[{'name':'photo','value':'yes','source':'support_note','quote':'photo received'}]}))
    llm=provider(store,monkeypatch,handler)
    llm.extract(normalize(raw(customer_note='Contact jane@example.com at +1 555 123 4567',support_note='photo received')),[])
    assert 'jane@example.com' not in json.dumps(sent) and '555 123' not in json.dumps(sent)

def test_policy_versions_and_trials_are_exact_and_traceable(tmp_path):
    store=Store(tmp_path/'versions.sqlite3')
    active=store.policy();p=initial_policy();p['rules'][0]['reason_code']='high_value';p['rules'][0]['reason']='High value needs an independent review.'
    first=store.save_draft(p,parent_id=active['id'])
    p['rules'][0]['conditions'][0]['value']=25000
    second=store.save_draft(p,parent_id=first['id'])
    assert second['version']>first['version']>active['version']
    assert second['parent_id']==first['id'] and store.policy()['id']==active['id']
    ex=store.create_experiment(second['data'],policy_id=second['id'])
    assert ex['source_policy_id']==second['id']
    with pytest.raises(ValueError):store.create_experiment(first['data'],policy_id=second['id'])
    row=normalize(raw(amount_usd='275'));ev=evaluate(row,pending_evidence(row),second['data'])
    assert ev['reason_code']=='high_value' and ev['explanation']=='High value needs an independent review.'
    assert next(p for p in store.policies() if p['id']==first['id'])['data']['rules'][0]['conditions'][0]['value']==30000

def test_checked_version_itself_becomes_active_without_duplicate(tmp_path):
    from conftest import small_policy, complete_model_fixture
    store=Store(tmp_path/'one-concept.sqlite3');p=small_policy()
    saved=store.save_draft(p)
    settings={'min_prospective_auto':1,'min_changed_cases':1,'min_shadow_hours':0,'max_error_bps':10000,'max_projected_loss_cents':10000000}
    ex=store.create_experiment(saved['data'],settings,policy_id=saved['id'])
    with pytest.raises(Conflict,match='already has validation'):store.create_experiment(saved['data'],settings,policy_id=saved['id'])
    store.backtest_experiment(ex['id']);store.start_experiment(ex['id'])
    batch=store.import_preview(csv_text(raw()),'prospective.csv','pending');store.import_commit(batch['id'])
    complete_model_fixture(store,store.request('TEST-1'))
    observation=store.experiment_report(ex['id'])['observations'][0]
    shadow_reference_fixture(store,ex['id'],observation['id'],4000,False,'Synthetic fixture verified','Reviewer')
    count=len(store.policies());active=store.promote_experiment(ex['id'],'Synthetic release verification')
    assert active['id']==saved['id'] and active['version']==saved['version']
    assert len(store.policies())==count and store.metrics()['refund_count']==0
