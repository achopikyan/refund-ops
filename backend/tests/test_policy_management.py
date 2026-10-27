from copy import deepcopy
import json
import pytest
from refundops.domain import initial_policy
from refundops.policy_management import policy_library, compare_backtest, compare_shadow, rollback_preview, rollback_version
from refundops.storage import Store, Conflict
from conftest import raw, csv_text, small_policy, complete_model_fixture, model_evidence


def incoming(store, rid, amount='40'):
    report=store.import_preview(csv_text(raw(request_id=rid,customer_id=rid,amount_usd=amount)),rid+'.csv','pending')
    store.import_commit(report['id'])
    return complete_model_fixture(store,store.request(rid))


def shadow(store, cap=7500):
    p=small_policy(store.policy()['data'],cap)
    saved=store.save_draft(p)
    checks=store.create_experiment(saved['data'],policy_id=saved['id'])
    store.backtest_experiment(checks['id']);store.start_experiment(checks['id'])
    return saved,checks


def release(store, tag, cap=5000):
    p=small_policy(store.policy()['data'],cap)
    saved=store.save_draft(p)
    settings={'min_prospective_auto':1,'min_changed_cases':0,'min_shadow_hours':0,
              'max_error_bps':10000,'max_projected_loss_cents':10000000}
    checks=store.create_experiment(saved['data'],settings,policy_id=saved['id'])
    store.backtest_experiment(checks['id']);store.start_experiment(checks['id'])
    obj=incoming(store,'QUALIFY-'+tag)
    store.decide(obj['id'],obj['version'],'approved',4000,'Synthetic qualification review','Reviewer','qualify-'+tag)
    assert store.experiment_report(checks['id'])['gate']['passed']
    store.promote_experiment(checks['id'],'Synthetic test release '+tag)
    return saved,checks


@pytest.fixture
def released(tmp_path):
    store=Store(tmp_path/'managed.sqlite3')
    a,checks_a=release(store,'A')
    auto=incoming(store,'AUTO-A')
    store.mode('simulate')
    store.decide(auto['id'],auto['version'],'approved',4000,'Automatic fixture','automation','automatic-A',True)
    b,checks_b=release(store,'B',7500)
    return store,a,b,checks_a,checks_b


def tables(store,*names):
    with store.connect() as c:
        return {name:[tuple(row) for row in c.execute('SELECT * FROM '+name+' ORDER BY rowid')] for name in names}


def test_library_lists_distinct_lifecycle_stages_and_numbered_release_history(released):
    store,a,b,checks_a,checks_b=released
    draft=store.save_draft(deepcopy(b['data']))
    running,running_checks=shadow(store,6500)
    stopped,stop_checks=shadow(store,6000)
    store.stop_experiment(stop_checks['id'],'Stopped test')
    library=policy_library(store);versions={v['id']:v for v in library['versions']}
    assert library['current_id']==b['id']
    assert versions[b['id']]['stage']=='current' and versions[b['id']]['readiness']['passed']
    assert versions[a['id']]['stage']=='archived' and versions[a['id']]['can_rollback']
    assert versions[draft['id']]['stage']=='draft' and not versions[draft['id']]['can_rollback']
    assert versions[running['id']]['stage']=='shadow' and versions[running['id']]['checks_id']==running_checks['id']
    assert not versions[running['id']]['readiness']['passed']
    assert versions[stopped['id']]['stage']=='stopped'
    assert library['history'][0]['to_version']==b['version']
    assert library['history'][0]['from_version']==a['version']


def test_backtest_comparison_uses_same_rows_no_labels_no_mutations(store):
    historical=store.import_preview(csv_text(raw(request_id='H1',decision='approved',outcome_note='chargeback later'),
                                             raw(request_id='H2',amount_usd='60',decision='rejected',outcome_note='')),'h.csv','history')
    store.import_commit(historical['id'])
    from types import SimpleNamespace
    store.history_evidence=SimpleNamespace(summary=lambda *args,**kwargs:{'ready':True}, evidence=lambda *args:model_evidence())
    a=store.save_draft(small_policy(store.policy()['data'],7500))
    b=store.save_draft(small_policy(store.policy()['data'],3000))
    before=tables(store,'requests','decisions','ledger','policies','experiments','audit','previews')
    report=compare_backtest(store,[a['id'],b['id']])
    assert tables(store,*before)==before
    assert report['compared_requests']==2 and report['excluded_requests']==0
    assert report['current']['summary']['total']==2
    assert [v['summary']['total'] for v in report['versions']]==[2,2]
    assert [v['summary']['auto_count'] for v in report['versions']]==[2,0]
    assert set(report['requests'][0]['candidates'])=={a['id'],b['id']}
    assert report['requests'][1]['outcome_note'] is None
    for row in report['requests']:
        assert 'chargeback' not in json.dumps([row['current'],row['candidates']])
    with store.tx() as c:
        for row in c.execute('SELECT id,data FROM history').fetchall():
            data=json.loads(row['data']);data.update(decision='partial',outcome_note='FUTURE SECRET',decided_at='2099-01-01',review_minutes=999)
            c.execute('UPDATE history SET data=? WHERE id=?',(json.dumps(data),row['id']))
    changed=compare_backtest(store,[a['id'],b['id']])
    assert report['data_fingerprint']!=changed['data_fingerprint']
    for old,new in zip(report['requests'],changed['requests']):
        assert old['current']==new['current'] and old['candidates']==new['candidates']


def test_comparison_selection_limits_and_deduplication(store):
    saved=[store.save_draft(deepcopy(store.policy()['data'])) for _ in range(6)]
    with pytest.raises(ValueError,match='five'):compare_backtest(store,[p['id'] for p in saved])
    with pytest.raises(KeyError):compare_backtest(store,['missing'])
    with pytest.raises(ValueError):compare_shadow(store,'not-a-list')
    result=compare_backtest(store,[store.policy()['id'],saved[0]['id'],saved[0]['id']])
    assert len(result['versions'])==1


def test_shadow_subset_filters_before_shared_intersection(store):
    a,ca=shadow(store);b,cb=shadow(store,4000)
    obj=incoming(store,'SHARED')
    with store.tx() as c:c.execute('DELETE FROM observation_heads WHERE experiment_id=?',(cb['id'],))
    assert store.shadow_dashboard()['compared_requests']==0
    selected=store.shadow_dashboard([a['id']])
    assert selected['compared_requests']==1 and len(selected['versions'])==1
    report=compare_shadow(store,[a['id']])
    assert report['compared_requests']==1
    assert report['versions'][0]['checks_id']==ca['id']
    assert set(report['requests'][0]['candidates'])=={a['id']}
    assert report['current']['summary']['total']==report['versions'][0]['summary']['total']==1
    assert report['requests'][0]['request_id']==obj['id']


def test_shadow_unavailable_versions_never_receive_invented_observations(store):
    active=store.policy()['id']
    running,checks=shadow(store)
    draft=store.save_draft(deepcopy(running['data']))
    stopped,stop_checks=shadow(store)
    store.stop_experiment(stop_checks['id'],'Stopped')
    incoming(store,'EXAMPLE')
    store.runtime_manifest=lambda:{'ai':{'model':'changed'}}
    report=compare_shadow(store,[running['id'],draft['id'],stopped['id']])
    assert report['current']['policy_id']==active
    assert all(not v['available'] and v['summary'] is None and v['reason'] for v in report['versions'])
    assert all(row['candidates']=={} for row in report['requests'])


def test_rollback_rejects_drafts_and_unbound_generic_preview(released):
    store,a,b,_,_=released
    draft=store.save_draft(deepcopy(a['data']))
    with pytest.raises(Conflict,match='archived'):rollback_preview(store,draft['id'])
    with pytest.raises(Conflict,match='archived'):rollback_version(store,draft['id'],'anything','Not allowed')
    generic=store.preview(a['data'])
    with pytest.raises(Conflict,match='exact archived'):rollback_version(store,a['id'],generic['id'],'Invalid preview')
    assert store.policy()['id']==b['id']


def test_rollback_preview_rejects_changed_request_or_new_candidate_evidence(released):
    store,a,b,_,_=released
    obj=incoming(store,'PENDING','60')
    preview=rollback_preview(store,a['id'])
    store.correct(obj['id'],obj['version'],{'amount_usd':'65'},'Verified amount','Reviewer')
    with pytest.raises(Conflict,match='stale'):rollback_version(store,a['id'],preview['id'],'Changed workspace')
    preview=rollback_preview(store,a['id']);obj=store.request(obj['id'])
    evidence=deepcopy(obj['evidence']);evidence['summary']='New prepared evidence'
    store.prepare_candidate(a['data'],obj['id'],evidence,obj['version'])
    with pytest.raises(Conflict,match='evidence changed'):rollback_version(store,a['id'],preview['id'],'Changed evidence')
    assert store.policy()['id']==b['id']


def test_successful_rollback_restores_same_version_preserves_money_and_automatic_processing(released):
    store,a,b,checks_a,checks_b=released
    ready=incoming(store,'READY','60')
    held=incoming(store,'HELD','60')
    store.workflow(held['id'],held['version'],'hold','Reviewer','Awaiting investigation')
    held=store.request(held['id'])
    settled={r['id']:r for r in store.requests() if r['status']=='resolved'}
    immutable=tables(store,'decisions','ledger','automation_spend','release_limits')
    count=len(store.policies());epoch=int(store.state()['epoch'])
    preview=rollback_preview(store,a['id'])
    assert preview['target']['version']==a['version'] and preview['current']['version']==b['version']
    assert preview['eligible']==1 and preview['counts']['new_auto']==0
    assert 'prepared_evidence' not in preview and preview['warnings']
    result=rollback_version(store,a['id'],preview['id'],'Restore the previous conservative boundary')
    assert result['current']['id']==a['id'] and result['current']['version']==a['version']
    assert len(store.policies())==count and result['updated_requests']==1
    assert store.state()['mode']=='simulate' and int(store.state()['epoch'])==epoch+1
    assert tables(store,*immutable)==immutable
    assert all(store.request(rid)==obj for rid,obj in settled.items())
    assert store.request(held['id'])==held
    changed=store.request(ready['id'])
    assert changed['version']==ready['version']+1 and changed['evaluation']['action']=='review'
    assert store.release_budget()['release_spent_cents']==4000
    assert store.experiment(checks_a['id'])['status']=='active'
    assert store.experiment(checks_b['id'])['status']=='superseded'
    history=policy_library(store)['history'][0]
    assert history['type']=='policy_rolled_back' and history['from_version']==b['version'] and history['to_version']==a['version']
    assert history['preview_id']==preview['id'] and history['reason']=='Restore the previous conservative boundary'


def test_never_qualified_baseline_rolls_back_for_manual_routing_only(tmp_path):
    store=Store(tmp_path/'baseline.sqlite3');baseline=store.policy()
    release(store,'B')
    obj=incoming(store,'MANUAL')
    preview=rollback_preview(store,baseline['id'])
    assert not preview['qualification']['passed']
    rollback_version(store,baseline['id'],preview['id'],'Return to manual routing')
    assert store.state()['mode']=='simulate'
    assert store.request(obj['id'])['evaluation']['action']=='review'
    assert not store.apply_automation()['applied']


def test_stale_released_policy_can_restore_routing_but_cannot_execute(released):
    store,a,b,_,_=released
    pending=incoming(store,'OLD-MANIFEST')
    store.runtime_manifest=lambda:{'ai':{'model':'changed'}}
    preview=rollback_preview(store,a['id'])
    assert not preview['qualification']['passed']
    rollback_version(store,a['id'],preview['id'],'Restore routing with automation paused')
    assert store.state()['mode']=='simulate'
    store.mode('simulate')  # Existing execution checks remain the final guard.
    applied=store.apply_automation()
    assert not applied['applied'] and applied['skipped']
    assert store.request(pending['id'])['decision'] is None
    assert store.state()['mode']=='simulate'
