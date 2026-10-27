from conftest import shadow_reference_fixture
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from conftest import raw, csv_text, small_policy, complete_model_fixture
from refundops.main import create_app
from refundops.storage import Store, Conflict


def add(store, name='SHARED-1', amount='60'):
    preview = store.import_preview(csv_text(raw(request_id=name,customer_id=name,amount_usd=amount)),name+'.csv','pending')
    store.import_commit(preview['id'])
    return complete_model_fixture(store,store.request(name))


def checked(store, name='Policy A', cap=7500, start=True):
    policy = small_policy(store.policy()['data'],cap)
    policy['name']=name
    saved = store.save_draft(policy)
    ex = store.create_experiment(policy,policy_id=saved['id'])
    store.backtest_experiment(ex['id'])
    if start:store.start_experiment(ex['id'])
    return ex['id']


def test_backtest_waits_for_manual_start_before_joining_shared_pool(store):
    old = add(store,'OLD')
    a,b = checked(store,start=False),checked(store,'Policy B',4000,start=False)
    waiting = add(store,'WAITING')
    store.decide(waiting['id'],waiting['version'],'approved',6000,'Reviewed before Shadow','Alex','waiting')
    for eid in (a,b):
        report=store.experiment_report(eid)
        assert report['experiment']['status']=='backtested' and report['observations']==[]
        assert not report['gate']['passed']
    assert store.shadow_dashboard()['versions']==[]
    for eid in (a,b):
        store.start_experiment(eid)
        started=store.experiment(eid)['started_at']
        store.start_experiment(eid)
        assert store.experiment(eid)['started_at']==started
    newer = add(store,'NEW')
    for eid in (a,b):
        report = store.experiment_report(eid)
        assert report['experiment']['status']=='shadow'
        assert {o['request_id'] for o in report['observations']}=={old['id'],waiting['id'],newer['id']}
        assert report['financial']['backlog']==2 and report['financial']['prospective']==1
        assert report['comparison']['candidate']['reviewed']==1
    checked(store,'Unstarted',start=False)
    dashboard=store.shadow_dashboard()
    assert dashboard['compared_requests']==3 and dashboard['excluded_requests']==0
    assert len(dashboard['versions'])==2 and store.metrics()['refund_count']==1


@pytest.mark.parametrize('action,amount,expected_loss',[('approved',6000,0),('partial',2500,3500),('rejected',None,6000)])
def test_normal_decision_updates_every_policy_without_extra_payments(store,action,amount,expected_loss):
    a,b=checked(store),checked(store,'Policy B',4000)
    obj=add(store)
    args=(obj['id'],obj['version'],action,amount,'Reviewed original evidence','Alex','shared-operation')
    store.decide(*args);store.decide(*args)
    for eid in (a,b):
        report=store.experiment_report(eid)
        assert report['comparison']['candidate']['reviewed']==1
        assert report['observations'][0]['label']['source']=='human_decision'
    assert store.experiment_report(a)['financial']['reviewed_auto']==1
    assert store.experiment_report(a)['comparison']['candidate']['overpayment_cents']==expected_loss
    assert store.experiment_report(b)['comparison']['candidate']['auto_count']==0
    dashboard=store.shadow_dashboard()
    assert dashboard['reviewed_requests']==1
    assert store.metrics()['refund_count']==(0 if action=='rejected' else 1)
    with store.connect() as c:assert c.execute('SELECT COUNT(*) FROM shared_reviews').fetchone()[0]==1


def test_automatic_payment_is_not_a_human_reference(store):
    eid=checked(store)
    obj=add(store,amount='40')
    store.mode('simulate')
    store.decide(obj['id'],obj['version'],'approved',4000,'Automatic fixture','automation','auto-reference',True)
    assert store.experiment_report(eid)['observations'][0]['label'] is None
    assert store.shadow_dashboard()['reviewed_requests']==0


def test_completed_requests_join_later_versions_as_retrospective(store):
    obj=add(store)
    store.decide(obj['id'],obj['version'],'partial',2500,'Verified partial','Alex','before-shadow')
    eid=checked(store)
    report=store.experiment_report(eid)
    assert len(report['observations'])==1
    assert report['comparison']['candidate']['reviewed']==1
    assert report['comparison']['candidate']['overpayment_cents']==3500
    assert report['financial']['prospective']==report['financial']['reviewed_auto']==0
    assert not report['gate']['passed']


def test_additional_assessment_is_shared_and_stale_inputs_do_not_reuse_it(store):
    a,b=checked(store),checked(store,'Policy B')
    obj=add(store)
    obs=store.experiment_report(a)['observations'][0]
    shadow_reference_fixture(store,a,obs['id'],2500,False,'Verified amount independently','Alex')
    assert store.experiment_report(b)['financial']['reviewed_auto']==1
    store.correct(obj['id'],obj['version'],{'amount_usd':'65'},'Receipt corrected','Alex')
    for eid in (a,b):
        report=store.experiment_report(eid)
        assert report['observations'][0]['label'] is None
        assert report['comparison']['candidate']['reviewed']==0


def test_recheck_retains_old_evidence_but_resets_prospective_cohort(store):
    eid=checked(store);obj=add(store)
    store.decide(obj['id'],obj['version'],'approved',6000,'Reviewed','Alex','before-recheck')
    count=len(store.policies())
    old=store.experiment_report(eid)
    store.runtime_manifest=lambda:{'ai':{'model':'changed'}}
    assert store.shadow_dashboard()['versions'][0]['stale']
    new=store.recheck_experiment(eid)
    assert new['experiment']['status']=='backtested' and new['observations']==[]
    new=store.start_experiment(new['experiment']['id'])
    assert len(store.policies())==count
    assert new['experiment']['source_policy_id']==old['experiment']['source_policy_id']
    assert new['financial']['prospective']==0 and new['comparison']['candidate']['reviewed']==1
    assert store.experiment_report(eid)['observations']==old['observations']
    assert store.experiment(eid)['status']=='superseded'
    assert store.shadow_dashboard()['versions'][0]['stale'] is False


def test_shared_semantic_checks_are_bound_to_question_definition(store):
    a=checked(store)
    policy=small_policy(store.policy()['data'],7500);policy['name']='With question'
    policy['criteria']=[{'id':'q','question':'Is this Northfield?','sources':['support_note']}]
    b=store.create_experiment(policy)['id'];store.backtest_experiment(b);store.start_experiment(b)
    obj=add(store)
    obs=store.experiment_report(b)['observations'][0]
    shadow_reference_fixture(store,b,obs['id'],6000,False,'Checked Northfield','Alex',{'q':'yes'})
    assert store.experiment_report(b)['observations'][0]['label']['semantic_checks']=={'q':'yes'}
    assert store.experiment_report(a)['observations'][0]['label']['semantic_checks']=={}


def test_legacy_human_decisions_backfilled_once_and_not_automation(store):
    manual=add(store,'MANUAL',amount='40');auto=add(store,'AUTO',amount='40')
    store.decide(manual['id'],manual['version'],'rejected',None,'Verified refusal','Alex','legacy-manual')
    store.mode('simulate');store.decide(auto['id'],auto['version'],'approved',4000,'Rule','automation','legacy-auto',True)
    with store.tx() as c:c.execute('DELETE FROM shared_reviews')
    restored=Store(store.path);Store(store.path)
    with restored.connect() as c:
        refs=c.execute('SELECT * FROM shared_reviews').fetchall()
        assert len(refs)==1 and refs[0]['request_id']==manual['id']


def test_no_assignment_step_and_normal_api_review_updates_dashboard(tmp_path):
    with TestClient(create_app(tmp_path/'shared-api.sqlite3',seed=False),headers={'X-Demo-Role':'manager'}) as client:
        store=client.app.state.store;eid=checked(store);obj=add(store)
        reviewer={'X-Demo-Role':'reviewer'}
        assert client.get('/api/shadow-policies',headers=reviewer).status_code==403
        for path in ('/api/shadow-reviews','/api/trials','/api/trials/'+eid,'/api/policies'):
            assert client.get(path,headers=reviewer).status_code==403
        assert client.post('/api/trials/'+eid+'/observations/any/review',headers=reviewer,json={'allowed_cents':6000,'note':'No shadow assessments'}).status_code==403
        assert 'Policy A' not in client.get('/api/requests',headers=reviewer).text
        assert client.post('/api/requests/'+obj['id']+'/workflow',headers=reviewer,json={'version':obj['version'],'action':'claim'}).status_code==422
        response=client.post('/api/requests/'+obj['id']+'/decisions',headers=reviewer,json={
            'version':obj['version'],'action':'partial','amount_cents':2500,'reason':'Reviewed once','idempotency_key':'shared-api-decision'})
        assert response.status_code==200
        dashboard=client.get('/api/shadow-policies').json()
        assert dashboard['reviewed_requests']==1 and dashboard['versions'][0]['metrics']['overpayment_cents']==3500
