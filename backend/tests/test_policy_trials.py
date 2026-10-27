from conftest import shadow_reference_fixture
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import sqlite3
import pytest
from conftest import raw, csv_text, small_policy, complete_model_fixture
from refundops.domain import initial_policy, fingerprint
from refundops.financial import error_upper, financial_report, ReleaseSettings
from refundops.storage import Store, Conflict, SCHEMA, dump, now
from refundops.mining import discover


def add(store, name="NEW-1", amount="60", customer=None, **kwargs):
    batch=store.import_preview(csv_text(raw(request_id=name,customer_id=customer or name,amount_usd=amount,**kwargs)),name+".csv","pending")
    store.import_commit(batch["id"])
    return complete_model_fixture(store,store.request(name))


def trial(store, **settings):
    p=small_policy(store.policy()["data"],7500)
    # Deliberately permissive fixture to exercise promotion with a tiny synthetic cohort.
    # Production defaults remain 30 cases, five changed cases and 24 hours.
    config={"min_prospective_auto":1,"min_changed_cases":1,"min_shadow_hours":0.0,
            "max_error_bps":10000,"max_projected_loss_cents":10000000,**settings}
    ex=store.create_experiment(p,config)
    store.backtest_experiment(ex["id"]);store.start_experiment(ex["id"])
    return ex


def assess_all(store,eid,amount=6000,critical=False):
    for o in store.experiment_report(eid)["observations"]:
        shadow_reference_fixture(store,eid,o["id"],amount,critical,"Checked the supplied evidence independently","Reviewer")


def test_exact_upper_bound_and_unknown():
    assert error_upper(0,0) is None
    assert error_upper(0,100)==pytest.approx(.02951305,abs=1e-7)
    assert error_upper(1,10)==pytest.approx(.3941633,abs=1e-6)
    assert error_upper(10,10)==1


def test_migration_preserves_legacy_workspace(tmp_path):
    path=tmp_path/"old.sqlite3"
    with sqlite3.connect(path) as c:c.executescript(SCHEMA)
    store=Store(path);obj=add(store,amount="40")
    store.decide(obj["id"],obj["version"],"approved",4000,"Verified","Reviewer","migration-key")
    other=Store(path)
    assert other.metrics()["refund_count"]==1
    with other.connect() as c:
        assert {r[0] for r in c.execute("SELECT version FROM schema_version")}=={1,2,3}


def test_backtest_required_and_direct_activation_forbidden(store):
    ex=store.create_experiment(store.policy()["data"])
    with pytest.raises(Conflict,match="historical"):store.start_experiment(ex["id"])
    with pytest.raises(Conflict,match="Direct activation"):store.activate("anything","bypass")


def test_shadow_isolated_and_backlog_never_qualifies(store):
    obj=add(store);before=deepcopy(store.request(obj["id"]));policy=store.policy()
    ex=trial(store)
    assert store.request(obj["id"])==before and store.policy()==policy
    assess_all(store,ex["id"])
    report=store.experiment_report(ex["id"])
    assert report["financial"]["backlog"]==1 and report["financial"]["prospective"]==0
    assert not report["gate"]["passed"] and store.metrics()["refund_count"]==0


def test_import_captures_prospective_and_deduplicates(store):
    ex=trial(store);obj=add(store)
    for _ in range(3):store.capture_experiment(ex["id"])
    report=store.experiment_report(ex["id"])
    assert len(report["observations"])==1
    obs=report["observations"][0]
    assert obs["baseline"]["action"]=="review" and obs["candidate"]["action"]=="auto_approve"
    assert obs["cohort"]=="prospective" and store.request(obj["id"])["evaluation"]["action"]=="review"
    assert store.metrics()["refund_count"]==0


def test_source_change_invalidates_labels_and_same_input_does_not_inflate(store):
    ex=trial(store);obj=add(store);assess_all(store,ex["id"])
    old=store.experiment_report(ex["id"])["observations"][0]
    obj=store.correct(obj["id"],obj["version"],{"amount_usd":"65"},"Receipt correction","Reviewer")
    current=store.experiment_report(ex["id"])
    assert current["financial"]["prospective"]==1 and current["financial"]["reviewed_auto"]==0
    with pytest.raises(Conflict,match="superseded"):shadow_reference_fixture(store,ex["id"],old["id"],6000,False,"Old input","Reviewer")
    # A return to a previous identical input chooses that immutable observation as head.
    store.correct(obj["id"],obj["version"],{"amount_usd":"60"},"Restore verified receipt","Reviewer")
    assert store.experiment_report(ex["id"])["financial"]["prospective"]==1


def test_unknown_label_and_large_error_block(store):
    ex=trial(store,max_error_bps=1000);add(store)
    oid=store.experiment_report(ex["id"])["observations"][0]["id"]
    shadow_reference_fixture(store,ex["id"],oid,None,False,"Not enough evidence","Reviewer")
    report=store.experiment_report(ex["id"])
    assert report["financial"]["unreviewed_cents"]==6000 and report["financial"]["error_upper_95"] is None
    shadow_reference_fixture(store,ex["id"],oid,0,False,"Refund not supported","Reviewer")
    report=store.experiment_report(ex["id"])
    assert report["financial"]["candidate_overpayment_cents"]==6000
    assert not report["gate"]["passed"]


def test_partial_allowed_amount_measures_overpayment(store):
    ex=trial(store);add(store);assess_all(store,ex["id"],amount=2500)
    r=store.experiment_report(ex["id"])["financial"]
    assert r["candidate_overpayment_cents"]==3500 and r["baseline_overpayment_same_cases_cents"]==0
    assert r["error_count"]==1


def test_critical_violation_blocks_permissive_settings(store):
    ex=trial(store);add(store);assess_all(store,ex["id"],critical=True)
    assert not store.experiment_report(ex["id"])["gate"]["passed"]
    with pytest.raises(Conflict,match="Critical"):store.promote_experiment(ex["id"],"Try anyway")


def test_atomic_promotion_preserves_old_policy_and_never_pays(store):
    ex=trial(store);obj=add(store);assess_all(store,ex["id"])
    assert store.experiment_report(ex["id"])["gate"]["passed"]
    policy=store.promote_experiment(ex["id"],"Synthetic unit-test release")
    assert policy["parent_id"]==ex["base_id"]
    assert store.state()["mode"]=="simulate" and store.metrics()["refund_count"]==0
    assert store.request(obj["id"])["evaluation"]["action"]=="auto_approve"
    assert store.release_budget()["source"]=="approved_trial"
    with pytest.raises(Conflict):store.promote_experiment(ex["id"],"Duplicate")


def test_model_change_invalidates_trial_and_released_execution(store):
    store.runtime_manifest=lambda:{"ai":{"model":"first"}}
    ex=trial(store);obj=add(store);assess_all(store,ex["id"])
    store.runtime_manifest=lambda:{"ai":{"model":"second"}}
    with pytest.raises(Conflict,match="model"):store.promote_experiment(ex["id"],"Invalid version")
    store.runtime_manifest=lambda:{"ai":{"model":"first"}}
    store.promote_experiment(ex["id"],"Test release")
    store.runtime_manifest=lambda:{"ai":{"model":"third"}}
    store.mode("simulate");result=store.apply_automation()
    assert not result["applied"] and store.state()["mode"]=="simulate"


def test_stopped_trial_no_longer_collects(store):
    ex=trial(store);store.stop_experiment(ex["id"],"Stop to revise")
    add(store)
    assert not store.experiment_report(ex["id"])["observations"]


def test_multiple_shadow_versions_at_a_time(store):
    first=trial(store);other=store.create_experiment(store.policy()["data"]);store.backtest_experiment(other["id"])
    assert store.start_experiment(other["id"])["experiment"]["status"]=="shadow"
    add(store)
    assert len(store.experiment_report(first["id"])["observations"])==1
    assert len(store.experiment_report(other["id"])["observations"])==1


def test_minimum_duration_cannot_be_skipped(store):
    ex=trial(store,min_shadow_hours=24.0);add(store);assess_all(store,ex["id"])
    assert any("duration" in x for x in store.experiment_report(ex["id"])["gate"]["blockers"])


def test_new_semantic_question_needs_independent_assessment(store):
    p=small_policy(store.policy()["data"],7500)
    p["criteria"]=[{"id":"region","question":"Is the region Northfield?","sources":["support_note"]}]
    ex=store.create_experiment(p,{"min_prospective_auto":1,"min_changed_cases":1,"min_shadow_hours":0.0,"max_error_bps":10000,"max_projected_loss_cents":10000000})
    store.backtest_experiment(ex["id"]);store.start_experiment(ex["id"])
    obj=add(store);e=deepcopy(obj["evidence"]);e["facts"]["semantic.region"]={"value":"yes","source":"human","quote":"Verified region"}
    store.prepare_candidate(p,obj["id"],e,obj["version"])
    assess_all(store,ex["id"])
    assert any("semantic" in x for x in store.experiment_report(ex["id"])["gate"]["blockers"])
    obs=store.experiment_report(ex["id"])["observations"][0]
    shadow_reference_fixture(store,ex["id"],obs["id"],6000,False,"Confirmed region independently","Reviewer",{"region":"yes"})
    assert store.experiment_report(ex["id"])["gate"]["passed"]


def test_live_evidence_from_different_model_cannot_release(store):
    ex=trial(store);obj=add(store)
    e=deepcopy(obj["evidence"]);e.update(method="live",complete=True,model_manifest='different-model')
    store.update_evidence(obj["id"],e,obj["version"])
    assess_all(store,ex["id"])
    report=store.experiment_report(ex["id"])
    assert report["observations"][0]["candidate"]["action"]=="auto_approve"
    assert not report["gate"]["passed"] and store.request(obj["id"])["evaluation"]["action"]=="review"
    assert 'AI evidence does not match the frozen model and prompt.' in report['gate']['blockers']


@pytest.mark.parametrize("field,value",[("daily_cents",10000),("release_cents",10000),("release_count",1)])
def test_two_concurrent_payments_cannot_exceed_budget(store,field,value):
    ex=trial(store,**{field:value});a=add(store,"A");b=add(store,"B");assess_all(store,ex["id"])
    store.promote_experiment(ex["id"],"Test concurrency");store.mode("simulate")
    def pay(rid):
        obj=store.request(rid)
        try:return store.decide(obj["id"],obj["version"],"approved",6000,"Rule","automation","budget-"+rid,True)
        except Conflict:return None
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(pay,["A","B"]))
    assert sum(x is not None for x in results)==1
    assert store.metrics()["refund_cents"]==6000 and store.state()["mode"]=="simulate"
    assert store.release_budget()["release_count"]==1


def test_customer_budget_and_manual_review_remain_available(store):
    ex=trial(store,customer_daily_cents=10000);add(store,"A",customer="shared");add(store,"B",customer="shared");assess_all(store,ex["id"])
    store.promote_experiment(ex["id"],"Test customer cap");store.mode("simulate");store.apply_automation()
    assert store.metrics()["refund_count"]==1 and store.state()["mode"]=="simulate"
    pending=next(x for x in store.requests() if x["status"]!="resolved")
    store.decide(pending["id"],pending["version"],"approved",6000,"Independent review","Reviewer","manual-after-pause")
    assert store.metrics()["refund_count"]==2 and store.release_budget()["release_count"]==1


def test_repeated_operation_does_not_spend_twice(store):
    obj=add(store,amount="40");store.mode("simulate")
    args=(obj["id"],obj["version"],"approved",4000,"Rule","automation","repeat-budget",True)
    store.decide(*args);store.decide(*args)
    assert store.release_budget()["release_spent_cents"]==4000


def test_single_payment_cap_is_independent_of_policy(store):
    p=store.policy();p["data"]=small_policy(p["data"],20000)
    with store.tx() as c:c.execute("UPDATE policies SET data=? WHERE id=?",(dump(p["data"]),p["id"]))
    add(store,amount="150");store.mode("simulate");store.apply_automation()
    assert store.metrics()["refund_count"]==0 and store.state()["mode"]=="simulate"


def test_mining_uses_no_outcomes_as_conditions_and_does_not_claim_labels(seeded):
    report=seeded.mine_rules()
    assert report["candidates"] and report["training_count"]+report["later_count"]+report["excluded_repeated_customers"]+report["excluded_invalid"]==248
    assert seeded.metrics()["refund_count"]==0
    for candidate in report["candidates"]:
        assert candidate["status"]=="hypothesis"
        assert not {x["field"] for x in candidate["rule"]["conditions"]}&{"decision","outcome_note","decided_by","review_minutes"}
        assert candidate["training"]["support"]>=5
    assert seeded.latest_mining()["id"]==report["id"]


def test_changing_outcomes_does_not_change_mined_rules_or_rank(seeded):
    with seeded.connect() as c:history=[json.loads(r[0]) for r in c.execute("SELECT data FROM history")]
    one=discover(history,initial_policy())
    changed=deepcopy(history)
    for r in changed:r["outcome_note"]="chargeback";r["decision"]="rejected"
    two=discover(changed,initial_policy())
    assert [r["id"] for r in one["candidates"]]==[r["id"] for r in two["candidates"]]
    assert one["candidates"][0]["training"]["unknown_outcomes"]!=two["candidates"][0]["training"]["unknown_outcomes"]


def test_backtest_input_has_no_future_fields(seeded):
    ex=seeded.create_experiment(seeded.policy()["data"]);result=seeded.backtest_experiment(ex["id"])
    assert result["total"]==248 and result["unknown_outcomes"]==214
    seeded.start_experiment(ex["id"])
    for obs in seeded.experiment_report(ex["id"])["observations"]:
        assert not set(obs["snapshot"]["data"])&{"decision","outcome_note","decided_by","decided_at","review_minutes"}


def test_frozen_settings_are_validated(store):
    with pytest.raises(ValueError):store.create_experiment(store.policy()["data"],{"daily_cents":-1})
    with pytest.raises(ValueError):store.create_experiment(store.policy()["data"],{"max_error_bps":0})


def test_repeated_customers_do_not_inflate_statistical_support(store):
    ex=trial(store,min_prospective_auto=2);add(store,"A",customer="same");add(store,"B",customer="same")
    assess_all(store,ex["id"])
    report=store.experiment_report(ex["id"])
    assert report["financial"]["candidate_auto"]==2
    assert report["financial"]["reviewed_customer_groups"]==1
    assert report["financial"]["error_upper_95"]==pytest.approx(.95)
    assert not report["gate"]["passed"]


def test_daily_budget_resets_but_release_budget_does_not(store,monkeypatch):
    import refundops.storage as storage
    monkeypatch.setattr(storage,"now",lambda:"2026-10-26T12:00:00+00:00")
    ex=trial(store,daily_cents=6000,release_cents=12000);add(store,"A");assess_all(store,ex["id"])
    store.promote_experiment(ex["id"],"Time-bound fixture");store.mode("simulate");store.apply_automation()
    assert store.release_budget()["daily_spent_cents"]==6000
    monkeypatch.setattr(storage,"now",lambda:"2026-10-27T12:00:00+00:00")
    assert store.release_budget()["daily_spent_cents"]==0
    assert store.release_budget()["release_spent_cents"]==6000
    add(store,"B");store.apply_automation()
    assert store.release_budget()["release_spent_cents"]==12000


def test_risk_limit_blocks_even_zero_observed_errors(store):
    ex=trial(store,max_projected_loss_cents=1);add(store);assess_all(store,ex["id"])
    report=store.experiment_report(ex["id"])
    assert report["financial"]["candidate_overpayment_cents"]==0
    assert report["financial"]["projected_loss_upper_cents"]>1
    assert any("loss upper" in x for x in report["gate"]["blockers"])


def test_semantic_fact_uses_only_declared_sources():
    from refundops.domain import validate_evidence,normalize
    data=normalize(raw(customer_note="Northfield",support_note="Other region"))
    evidence=validate_evidence(data,{"summary":"Region","facts":[{"name":"semantic.region","value":"yes","source":"customer_note","quote":"Northfield"}]},"live",[{"id":"region","question":"Northfield?","sources":["support_note"]}])
    assert evidence["issues"] and not evidence["complete"]
