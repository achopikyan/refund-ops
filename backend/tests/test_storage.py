from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import pytest
from conftest import raw,csv_text,ROOT,small_policy,complete_model_fixture
from refundops.storage import Store,Conflict
from refundops.domain import pending_evidence,fingerprint

def approve(store,obj,key="test-idempotency"):
    return store.decide(obj["id"],obj["version"],"approved",obj["data"]["amount_cents"],"Checked source records","Alex",key)
def test_dataset_counts(seeded):
    m=seeded.metrics();assert m["requests"]==20 and m["conflicts"]==1
    assert m["baseline"]=={"requests":248,"auto":111,"manual":137,"manual_approved":104,"review_minutes":1119.0,"chargebacks":8,"unknown_outcomes":214}
def test_import_is_idempotent(seeded):
    seeded.seed(ROOT/"data");assert len(seeded.requests())==20
def test_pending_conflicting_versions(seeded):
    obj=seeded.request("RF-2183");assert obj["conflict"] and len(obj["versions"])==2
    with pytest.raises(Conflict):approve(seeded,obj)
    obj=seeded.resolve(obj["id"],obj["version"],1,"Confirmed amount with order record","Alex")
    assert obj["data"]["amount_cents"]==5200 and not obj["conflict"]
    assert approve(seeded,obj)["ledger"]["amount_cents"]==5200
def test_double_click_returns_same_decision(one):
    store,obj=one;a=approve(store,obj);b=approve(store,obj)
    assert a["decision"]["id"]==b["decision"]["id"] and store.metrics()["refund_count"]==1
def test_reused_idempotency_with_different_payload_rejected(one):
    store,obj=one;approve(store,obj)
    with pytest.raises(Conflict):store.decide(obj["id"],1,"rejected",None,"Changed mind","Alex","test-idempotency")
def test_stale_review(one):
    store,obj=one;store.workflow(obj["id"],1,"hold","Alex","Waiting for verification")
    with pytest.raises(Conflict):approve(store,obj)
def test_two_concurrent_reviewers_one_payment(one):
    store,obj=one
    def submit(key):
        try:approve(store,obj,key);return True
        except Conflict:return False
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(submit,["one-attempt","two-attempt"]))
    assert sum(results)==1 and store.metrics()["refund_count"]==1
def test_partial_and_rejected(one):
    store,obj=one
    with pytest.raises(ValueError):store.decide(obj["id"],1,"partial",4000,"reason","Alex","attempt1")
    result=store.decide(obj["id"],1,"partial",1500,"Cosmetic issue confirmed","Alex","attempt2")
    assert result["ledger"]["amount_cents"]==1500
def test_rejection_never_moves_money(one):
    store,obj=one;store.decide(obj["id"],1,"rejected",None,"Outside window","Alex","reject-attempt")
    assert store.metrics()["refund_count"]==0
def test_automatic_execution_and_repeated_cycles(one):
    store,obj=one;obj=complete_model_fixture(store,obj)
    store.mode("simulate");assert len(store.apply_automation()["applied"])==1
    assert not store.apply_automation()["applied"]
    assert store.metrics()["refund_count"]==1
def test_held_excluded_from_automation(one):
    store,obj=one;store.mode("simulate");store.workflow(obj["id"],1,"hold","Alex","Waiting for verification")
    assert not store.apply_automation()["applied"]
def test_preview_is_read_only_and_fresh(one):
    store,obj=one;obj=complete_model_fixture(store,obj);before=store.request(obj["id"]);p=small_policy(store.policy()["data"],3000)
    preview=store.preview(p);assert preview["counts"]["old_auto"]==1 and preview["counts"]["new_auto"]==0
    assert store.request(obj["id"])==before
    with pytest.raises(Conflict,match="Direct activation"):store.activate(preview["id"],"Lower exposure")
    assert store.request(obj["id"])==before
    assert store.metrics()["refund_count"]==0
def test_stale_preview_cannot_activate(one):
    store,obj=one;preview=store.preview(store.policy()["data"]);store.workflow(obj["id"],1,"hold","Alex","Waiting for verification")
    with pytest.raises(Conflict,match="Direct activation"):store.activate(preview["id"],"Change")
def test_global_pause_switch_is_not_available(one):
    store,obj=one;preview=store.preview(store.policy()["data"])
    with pytest.raises(ValueError,match="always on"):store.mode("paused")
    with pytest.raises(Conflict):store.activate(preview["id"],"Change")
def test_candidate_analysis_does_not_mutate_queue(one):
    store,obj=one;p=store.policy()["data"];p["criteria"]=[{"id":"region","question":"Is this Southfield?","sources":["customer_note"]}]
    e=deepcopy(obj["evidence"]);e["facts"]["semantic.region"]={"value":"yes","source":"customer_note","quote":"Southfield"}
    store.prepare_candidate(p,obj["id"],e,obj["version"])
    assert store.request(obj["id"])==obj
    preview=store.preview(p)
    assert preview["prepared_evidence"][obj["id"]]["facts"]["semantic.region"]["value"]=="yes"
    assert store.request(obj["id"])==obj
def test_restore_creates_trial_without_activating(one):
    store,obj=one;old=store.policy();p=small_policy(old["data"],3000)
    trial=store.create_experiment(p)
    restored=store.create_experiment(old["data"])
    assert trial["id"]!=restored["id"] and restored["policy"]==old["data"]
    assert store.policy()["id"]==old["id"] and len(store.policies())==1

def test_persistence(one):
    store,obj=one;approve(store,obj);other=Store(store.path)
    assert other.request(obj["id"])["status"]=="resolved" and other.metrics()["refund_count"]==1
def test_history_never_operational(seeded):
    assert not any(x["external_id"]=="RF-2139" for x in seeded.requests())
def test_information_and_resume(one):
    store,obj=one;x=store.workflow(obj["id"],1,"information","Alex","Please supply a photo")
    assert x["status"]=="waiting_for_customer"
    with pytest.raises(Conflict,match="verify"):
        store.workflow(obj["id"],x["version"],"resume","Alex","Reply received")
    x=store.review_evidence(obj['id'],x['version'],{'photo':'yes'},'Verified the received photo','Alex')
    assert store.workflow(obj["id"],x["version"],"resume","Alex","New facts verified")["status"]=="ready"
def test_source_correction_preserves_old_version(one):
    store,obj=one;x=store.correct(obj["id"],1,{"amount_usd":"12.50"},"Checked original receipt","Alex")
    assert x["data"]["amount_cents"]==1250 and len(x["versions"])==2
    assert x["versions"][0]["raw"]["amount_usd"]=="40"
    with pytest.raises(ValueError):store.correct(obj["id"],2,{"outcome_note":"future info"},"reason","Alex")
