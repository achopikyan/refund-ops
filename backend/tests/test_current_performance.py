from fastapi.testclient import TestClient
from refundops.main import create_app
from refundops.current_performance import current_performance
from refundops.domain import initial_policy
from conftest import csv_text, raw


def test_current_performance_never_attributes_old_version_payments_to_new_current(one):
    store, request = one
    old_id = store.policy()['id']
    store.decide(request['id'],request['version'],'approved',4000,'Checked source','Alex','monitor-payment')
    assert current_performance(store)['decisions']['paid_cents']==4000
    new = store.save_draft(initial_policy())
    # Fixture switches identity directly to isolate monitor attribution from release gates.
    with store.tx() as c:
        c.execute("UPDATE policies SET status='archived' WHERE id=?",(old_id,))
        c.execute("UPDATE policies SET status='active' WHERE id=?",(new['id'],))
        c.execute("UPDATE state SET value=? WHERE key='active_policy'",(new['id'],))
    snapshot = current_performance(store)
    assert snapshot['policy']['id']==new['id']
    assert snapshot['decisions']=={'total':0,'automatic':0,'human':0,'payment_count':0,'paid_cents':0}
    assert snapshot['feedback']==[]
    assert store.metrics()['refund_cents']==4000


def test_waiting_requests_do_not_enter_current_ready_routing(one):
    store, request = one
    store.workflow(request['id'],request['version'],'hold','Alex','Need investigation')
    snapshot=current_performance(store)
    assert snapshot['queue']['open']==snapshot['queue']['waiting']==1
    assert snapshot['queue']['ready']==0
    assert sum(snapshot['queue']['routes'].values())==0


def test_outcomes_are_distinct_cases_and_old_blank_records_stay_unknown(one):
    from refundops.storage import uid,now
    store,request=one
    store.decide(request['id'],request['version'],'approved',4000,'Source checked','automation','human-named-automation')
    # A human-supplied display name must not classify a decision as automatic.
    with store.tx() as c:
        c.execute("UPDATE decisions SET created_at='2020-01-01T00:00:00+00:00'")
    empty=current_performance(store)
    assert empty['decisions']['automatic']==0 and empty['decisions']['human']==1
    assert empty['outcomes']['missing_cases']==1
    assert empty['outcomes']['chargeback_rate'] is None
    with store.tx() as c:
        for _ in range(2):c.execute('INSERT INTO outcomes VALUES(?,?,?,?,?)',(uid(),request['id'],'chargeback','Reported event',now()))
    r=current_performance(store)
    assert r['outcomes']['event_counts']['chargeback']==2
    assert r['outcomes']['case_counts']['chargeback']==1
    assert r['outcomes']['recorded_cases']==1
    assert r['outcomes']['chargeback_loss_cents'] is None
    assert r['operations']['reviewer_active_minutes'] is None


def test_manager_endpoints_and_reviewer_isolation(tmp_path):
    app=create_app(tmp_path/'manager-api.sqlite3',seed=False,auto_analyze=False)
    store=app.state.store
    version=store.save_draft(initial_policy())
    history=store.import_preview(csv_text(raw(request_id='H1',decision='approved',decided_by='reviewer')),'history.csv','history')
    store.import_commit(history['id'])
    with TestClient(app) as client:
        for path in ['/policy-versions','/policy-comparisons/backtest?policy_ids='+version['id'],
                     '/policy-comparisons/shadow?policy_ids='+version['id'],'/current-performance']:
            response=client.get('/api'+path,headers={'X-Demo-Role':'manager'})
            assert response.status_code==200,response.text
            assert client.get('/api'+path,headers={'X-Demo-Role':'reviewer'}).status_code==403
        assert client.post('/api/policies/'+version['id']+'/rollback-preview',headers={'X-Demo-Role':'manager'}).status_code==409
        assert client.post('/api/policies/'+version['id']+'/rollback',json={'preview_id':'missing','reason':'test'},headers={'X-Demo-Role':'reviewer'}).status_code==403
        assert client.get('/api/policy-comparisons/backtest?policy_ids=missing',headers={'X-Demo-Role':'manager'}).status_code==404
