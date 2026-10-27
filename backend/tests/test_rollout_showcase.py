import importlib.util
import json
from pathlib import Path
import pytest
from refundops.storage import dump,Conflict
from refundops.domain import fingerprint,pending_evidence
from refundops.policy_management import compare_shadow,rollback_preview,rollback_version

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('showcase',ROOT/'backend/tests/scenario_fixtures.py')
showcase=importlib.util.module_from_spec(spec);spec.loader.exec_module(showcase)


def test_all_stages_expose_tradeoff_and_preserve_financial_controls(store):
    from refundops.source_rebuild import load_sources, infer_legacy, build_policies
    sources=load_sources(ROOT/'data')
    v1,v2=build_policies(infer_legacy(sources['history']['rows']))
    v2,v3=showcase.candidates(v2)
    base=store.policy()
    with store.tx() as c:c.execute('UPDATE policies SET data=?,hash=? WHERE id=?',(dump(v1),fingerprint(v1),base['id']))
    checks=[]
    for p in (v2,v3):
        saved=store.save_draft(p,parent_id=base['id'])
        ex=store.create_experiment(saved['data'],{'min_shadow_hours':0.,'projection_cases':30},policy_id=saved['id'])
        store.backtest_experiment(ex['id']);store.start_experiment(ex['id']);checks.append((saved,ex))
    rows,refs=showcase.fixture();batch=store.import_preview(showcase.csv_content(rows),'synthetic.csv','pending');store.import_commit(batch['id'])
    for ref in refs:
        obj=store.request(ref['request_id'])
        # Deterministic author-reviewed fixture evidence, explicitly not a live model claim.
        e={**pending_evidence(obj['data']),'method':'reviewed','complete':True,'reviewed_by':'Fixture author'}
        store.update_evidence(obj['id'],e,obj['version'])
        obj=store.request(obj['id'])
        store.decide(obj['id'],obj['version'],ref['action'],None if ref['action']=='rejected' else ref['amount_cents'],ref['reason'],'Synthetic reviewer',ref['request_id'])
    a,b=[store.experiment_report(ex['id']) for _,ex in checks]
    assert a['financial']['candidate_auto']==50
    assert b['financial']['candidate_auto']==70
    assert a['financial']['candidate_overpayment_cents']==0
    assert b['financial']['candidate_overpayment_cents']==157500
    assert a['gate']['passed'] and not b['gate']['passed']
    assert a['decision_reports']['prospective']['workload']['net_minutes_freed']==320
    assert b['decision_reports']['prospective']['workload']['net_minutes_freed']==480
    comparison=compare_shadow(store,[p['id'] for p,_ in checks])
    assert comparison['compared_requests']==70
    assert [v['decision_reports']['prospective']['quality']['total'] for v in comparison['versions']]==[70,70]
    with pytest.raises(Conflict,match='Release blocked'):store.promote_experiment(checks[1][1]['id'],'Synthetic counterexample')
    # End-to-end activation and rollback are exercised only in this isolated fixture DB.
    ledger_before=store.metrics()['refund_count']
    store.promote_experiment(checks[0][1]['id'],'Synthetic workflow exercise; not operational validation')
    assert store.policy()['id']==checks[0][0]['id'] and store.state()['mode']=='simulate'
    preview=rollback_preview(store,base['id'])
    rollback_version(store,base['id'],preview['id'],'Synthetic rollback exercise')
    assert store.policy()['id']==base['id']
    assert store.metrics()['refund_count']==ledger_before
    assert store.state()['mode']=='simulate'
