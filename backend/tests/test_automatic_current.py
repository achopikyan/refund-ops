from copy import deepcopy
from refundops.analysis_pipeline import EvidencePipeline
from refundops.current_performance import current_performance
from refundops.domain import fingerprint, validate_evidence
from refundops.storage import Store, dump
from conftest import csv_text, raw, small_policy


class QualifiedFixture:
    key='test-only'
    calls=0
    def manifest(self):return {'model':'fixed-fixture'}
    def extract(self,data,criteria):
        self.calls+=1
        return {**validate_evidence(data,{'summary':'Fixture','facts':[]},'live',criteria),
                'model_manifest':fingerprint(self.manifest())}


def test_current_without_release_processes_saved_evidence_and_skips_only_blocked_case(tmp_path):
    store=Store(tmp_path/'automatic.sqlite3')
    p=small_policy(cap=7500)
    p['execution_limits']={'max_single_cents':5000,'daily_cents':50000,
        'customer_daily_cents':20000,'release_cents':100000,'release_count':100}
    with store.tx() as c:
        c.execute('UPDATE policies SET data=?,hash=? WHERE id=?',(dump(p),fingerprint(p),store.policy(c)['id']))
    batch=store.import_preview(csv_text(raw(request_id='CAP',amount_usd='60'),raw(request_id='OK',amount_usd='30')),'in.csv','pending')
    store.import_commit(batch['id'])
    llm=QualifiedFixture();pipeline=EvidencePipeline(store,llm)
    store.runtime_analysis_ready=pipeline.execution_ready
    # Even the old manual trigger cannot use unanalysed, empty-note inputs.
    assert store.apply_automation()['applied']==[]
    pipeline.run_once();pipeline.run_once()
    assert llm.calls==2
    assert store.request('OK')['ledger']['amount_cents']==3000
    blocked=store.request('CAP')
    assert blocked['decision'] is None and blocked['evaluation']['action']=='review'
    assert blocked['evaluation']['reason_code']=='execution_check'
    assert blocked['evaluation']['resolution']['required_check']=='execution_check'
    assert store.state()['mode']=='simulate'
    assert store.release_budget()['settings']['max_single_cents']==5000
    assert store.release_budget()['source']=='policy_settings'
    snapshot=current_performance(store)
    assert snapshot['queue']['execution_blocked']==1
    assert snapshot['decisions']['automatic']==snapshot['decisions']['payment_count']==1
    assert snapshot['operations']['daily'][0]['paid_cents']==3000
    # Saved extraction and idempotent payments survive process restart.
    restarted=Store(store.path);again=EvidencePipeline(restarted,llm)
    restarted.runtime_analysis_ready=again.execution_ready
    again.run_once()
    assert llm.calls==2 and restarted.metrics()['refund_count']==1


def test_archived_performance_never_shows_current_queue(one):
    store,obj=one;previous=store.policy()
    store.decide(obj['id'],obj['version'],'approved',4000,'Checked','Reviewer','old-performance')
    new=store.save_draft(deepcopy(previous['data']))
    with store.tx() as c:
        c.execute("UPDATE policies SET status='archived' WHERE id=?",(previous['id'],))
        c.execute("UPDATE policies SET status='active' WHERE id=?",(new['id'],))
        c.execute("UPDATE state SET value=? WHERE key='active_policy'",(new['id'],))
    batch=store.import_preview(csv_text(raw(request_id='NEW')),'new.csv','pending');store.import_commit(batch['id'])
    old=current_performance(store,previous['id']);current=current_performance(store,new['id'])
    assert not old['policy']['is_current'] and old['queue']['open']==0
    assert old['decisions']['paid_cents']==4000 and old['budget']['policy_id']==previous['id']
    assert current['policy']['is_current'] and current['queue']['open']==1
    assert current['decisions']['paid_cents']==0


def test_update_checks_with_pending_history_preserves_version_and_old_results(store):
    saved=store.save_draft(store.policy()['data'])
    old=store.create_experiment(saved['data'],policy_id=saved['id'])
    store.backtest_experiment(old['id'])
    snapshot=store.experiment(old['id'])['backtest']
    store.runtime_manifest=lambda:{'model':'new-fixture'}
    calls=[]
    class PendingHistory:
        def request_replay(self,eid):calls.append(eid);return {'preparing':True}
    store.history_evidence=PendingHistory()
    store.refresh_changed_checks()
    store.refresh_changed_checks()
    assert len(calls)==1
    result=store.experiment_report(calls[0])
    assert len(store.policies())==2
    assert result['experiment']['source_policy_id']==saved['id']
    assert result['experiment']['status']=='draft' and not result['observations']
    assert calls==[result['experiment']['id']]
    assert store.experiment(old['id'])['backtest']==snapshot
    assert store.experiment(old['id'])['status']=='superseded'
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM audit WHERE type='checks_restarted' AND json_extract(detail,'$.automatic')=1").fetchone()[0]==1


def test_current_cannot_start_shadow_even_without_model_exam(store):
    from refundops.storage import Conflict
    import pytest
    current = store.policy()
    experiment = store.create_experiment(current['data'], policy_id=current['id'])
    store.backtest_experiment(experiment['id'])
    with pytest.raises(Conflict, match='Current.*cannot run in Shadow'):
        store.start_experiment(experiment['id'])
    assert store.experiment(experiment['id'])['status'] == 'backtested'
