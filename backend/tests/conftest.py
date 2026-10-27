import csv
import io
import os
from tempfile import TemporaryDirectory
from copy import deepcopy
from pathlib import Path
import pytest
os.environ['REFUNDOPS_AUTO_ANALYZE'] = '0'
from refundops.domain import COLUMNS, normalize
from refundops.storage import Store, dump, now
from refundops.domain import initial_policy, fingerprint
from refundops.financial import ReleaseSettings

ROOT=Path(__file__).resolve().parents[2]
# Keep import-time app state isolated, with a short OS-managed path on Windows.
# Use a fresh owned temp root: an old pytest-of-user directory can belong to another
# Windows execution identity. Respect an explicit caller override.
_api_module_temp = TemporaryDirectory(prefix="rf-tests-")
os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", _api_module_temp.name)
os.environ["REFUNDOPS_DB"] = str(Path(_api_module_temp.name) / "module.sqlite3")

def raw(**changes):
    value=dict.fromkeys(COLUMNS,"")
    value.update(request_id="TEST-1",customer_id="C1",requested_at="2026-09-06",amount_usd="40",tenure_months="24",prior_refunds_12m="0",days_since_delivery="5",fraud_flag="no",stated_reason="wrong_size",category="apparel",payment_method="card",decision="pending")
    value.update({k:str(v) for k,v in changes.items()})
    return value
def csv_text(*rows):
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=COLUMNS);writer.writeheader();writer.writerows(rows);return stream.getvalue()

def small_policy(policy=None, cap=5000):
    """Explicit, visible rule for tests that exercise automatic payment boundaries."""
    policy=deepcopy(policy if policy is not None else initial_policy())
    policy['automation_enabled']=True
    policy['rules']=[r for r in policy['rules'] if r['id']!='test-small-refund']
    policy['rules'].append({
        'id':'test-small-refund','name':'Small established-customer refund','priority':100,
        'conditions':[
            {'field':'amount_cents','op':'lte','value':cap},
            {'field':'tenure_months','op':'gte','value':12},
            {'field':'prior_refunds_12m','op':'lte','value':0},
            {'field':'fraud_flag','op':'eq','value':False},
            {'field':'stated_reason','op':'in','value':['wrong_size','changed_mind','arrived_damaged']},
        ],'match':'all','action':'auto_approve','enabled':True,
        'reason_code':'small_established_customer','reason':'Explicit fixture rule',
    })
    return policy

@pytest.fixture
def store(tmp_path):
    # Established-release fixture for existing ledger/risk regression tests.
    # Fresh onboarding and mandatory qualification are tested separately with raw Store.
    store=Store(tmp_path/"test.sqlite3")
    with store.tx() as c:
        pid=store.policy(c)['id'];p=small_policy()
        c.execute('UPDATE policies SET data=?,hash=? WHERE id=?',(dump(p),fingerprint(p),pid))
        c.execute('INSERT INTO release_limits VALUES(?,?,?)',(pid,dump(ReleaseSettings().model_dump()),now()))
    return store
@pytest.fixture
def seeded(store):store.seed(ROOT/"data");return store
@pytest.fixture
def one(store):
    batch=store.import_preview(csv_text(raw()),"test.csv","pending");store.import_commit(batch["id"])
    return store,store.request("TEST-1")


def model_evidence(facts=None):
    """Authored model-response fixture, never inferred from the request text."""
    return {"facts": facts or {}, "summary": "Authored response for a test scenario",
            "method": "live", "complete": True, "issues": [],
            "criteria_hash": fingerprint([]), "fixture": True}


def complete_model_fixture(store, obj, facts=None):
    """Explicitly deliver a completed model response before testing later workflow stages."""
    evidence=model_evidence(facts)
    evidence['model_manifest']=fingerprint(store.manifest().get('ai',{}))
    return store.update_evidence(obj['id'], evidence, obj['version'])


def shadow_reference_fixture(store, eid, oid, allowed_cents, critical, note, actor, semantic_checks=None, minutes=0.0):
    from refundops.storage import Conflict, dump, now
    if not note.strip() or not actor.strip():
        raise ValueError("Record the reviewer and the evidence supporting this assessment.")
    with store.tx() as c:
        ex = store.experiment(eid, c)
        if ex["status"] != "shadow":
            raise Conflict("Only a running trial accepts adjudication.")
        store.check_experiment_environment(ex, c)
        obs = next((o for o in store.observation_list(eid, c) if o["id"] == oid), None)
        if not obs:
            raise Conflict("Observation was superseded or is not part of this experiment. Refresh the trial.")
        maximum = obs["snapshot"]["data"].get("amount_cents")
        if allowed_cents is not None and (type(allowed_cents) is not int or allowed_cents < 0 or maximum is None or allowed_cents > maximum):
            raise ValueError("Allowed refund must be between zero and the request amount, or unknown.")
        checks = semantic_checks or {}
        if not set(checks) <= {x["id"] for x in ex["policy"]["criteria"]} or any(v not in ("yes", "no", "unknown") for v in checks.values()):
            raise ValueError("Use the experiment's semantic questions and yes/no/unknown values.")
        label = {"allowed_cents": allowed_cents, "critical": critical, "note": note, "actor": actor,
                 "semantic_checks": checks, "minutes": minutes}
        c.execute("INSERT INTO adjudications(observation_id,data,created_at) VALUES(?,?,?)", (oid, dump(label), now()))
        # One additional assessment is reused by every policy on the same inputs.
        shared = {**label, 'source': 'shared_assessment', 'scoped_semantic_checks': {
            fingerprint(q): checks[q['id']] for q in ex['policy']['criteria'] if q['id'] in checks}}
        store.record_shared_review(c, {'id': obs['request_id'], 'data': obs['snapshot']['data'],
            'evidence': obs['snapshot']['baseline_evidence'], 'conflict': obs['snapshot']['conflict']}, shared)
        store.audit(c, eid, "shadow_adjudicated", {"observation_id": oid, **label}, actor)
    return store.experiment_report(eid)
