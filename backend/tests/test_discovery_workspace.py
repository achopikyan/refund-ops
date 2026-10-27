from copy import deepcopy
import json
import pytest
from fastapi.testclient import TestClient
from refundops.domain import initial_policy
from refundops.main import create_app
from refundops.mining import covered_by, discover
from refundops.storage import Store, Conflict
from conftest import ROOT, raw, csv_text


@pytest.fixture
def discovery_store(tmp_path):
    store=Store(tmp_path/'discovery.sqlite3');store.seed(ROOT/'data')
    return store


def test_discovery_produces_multiple_candidates_without_changing_active_or_saving_policy(discovery_store):
    s=discovery_store;active=s.policy();versions=s.policies()
    report=s.mine_rules()
    assert len(report['candidates'])>1
    assert s.policy()==active and s.policies()==versions
    assert report['base_id']==active['id'] and report['active_id']==active['id']
    assert all(not any(covered_by(x['rule'],r) for r in active['data']['rules']) for x in report['candidates'])


def test_discovery_excludes_semantic_duplicates_and_narrower_covered_rules(discovery_store):
    s=discovery_store;report=s.mine_rules()
    original=deepcopy(report['candidates'][0]['rule'])
    existing=deepcopy(original);existing.update(id='renamed-existing',name='Completely different display name')
    existing['conditions'].reverse()
    assert covered_by(original,existing)
    broader=deepcopy(existing)
    for c in broader['conditions']:
        if c['field']=='amount_cents': c['value']=100000
        if c['field']=='tenure_months': c['value']=0
        if c['field']=='prior_refunds_12m': c['value']=100
    assert covered_by(original,broader)
    restrictive=deepcopy(broader);restrictive['action']='review'
    assert not covered_by(original,restrictive)
    narrower=deepcopy(existing)
    next(c for c in narrower['conditions'] if c['field']=='amount_cents')['value']=1
    assert not covered_by(original,narrower)
    policy=deepcopy(s.policy()['data']);policy['rules'].append(existing)
    draft=s.save_draft(policy)
    repeated=s.mine_rules(base_id=draft['id'])
    assert repeated['excluded_existing']>0
    assert original['id'] not in [x['rule']['id'] for x in repeated['candidates']]
    assert all(not covered_by(x['rule'],existing) for x in repeated['candidates'])


def test_selected_candidates_become_editable_traceable_draft_not_active(discovery_store):
    s=discovery_store;active=s.policy();report=s.mine_rules();selected=[];seen=set()
    for candidate in report['candidates']:
        reason=next(c['value'] for c in candidate['rule']['conditions'] if c['field']=='stated_reason')
        if reason not in seen: selected.append(candidate['id']);seen.add(reason)
    assert len(selected)>1
    draft=s.draft_from_candidates(report['id'],selected)
    assert draft['parent_id']==active['id'] and draft['status']=='draft'
    assert len(draft['data']['rules'])==len(active['data']['rules'])+len(selected)
    assert s.draft_source(draft['id'])['selected_candidate_ids']==selected
    edited=deepcopy(draft['data']);edited['rules'][-1]['conditions'][1]['value']=1234
    saved=s.save_draft(edited,parent_id=draft['id'])
    assert s.draft_source(saved['id'])['selected_candidate_ids']==selected
    assert s.policy()==active and s.metrics()['refund_count']==0
    assert next(x for x in s.policies() if x['id']==draft['id'])['data']!=saved['data']


def test_stale_history_and_invalid_selection_do_not_save_drafts(discovery_store):
    s=discovery_store;report=s.mine_rules();key=report['candidates'][0]['id'];before=len(s.policies())
    for selection in [[key,key],['invented-candidate']]:
        with pytest.raises(ValueError):s.draft_from_candidates(report['id'],selection)
    batch=s.import_preview(csv_text(raw(request_id='NEW-HISTORY',decision='approved')),'new.csv','history');s.import_commit(batch['id'])
    with pytest.raises(Conflict,match='History changed'):s.draft_from_candidates(report['id'],[key])
    assert len(s.policies())==before


def test_changed_active_version_requires_fresh_discovery(discovery_store):
    s=discovery_store;report=s.mine_rules();draft=s.save_draft(initial_policy())
    # Model a release transition independently of the release-gate tests.
    with s.tx() as c:
        c.execute("UPDATE policies SET status='archived' WHERE status='active'")
        c.execute("UPDATE policies SET status='active' WHERE id=?",(draft['id'],))
        c.execute("UPDATE state SET value=? WHERE key='active_policy'",(draft['id'],))
    with pytest.raises(Conflict,match='Current policy changed'):
        s.draft_from_candidates(report['id'],[report['candidates'][0]['id']])


def test_discovery_selection_api_is_manager_only_and_rejects_empty_selection(tmp_path):
    with TestClient(create_app(tmp_path/'api.sqlite3')) as client:
        manager={'X-Demo-Role':'manager'};reviewer={'X-Demo-Role':'reviewer'}
        report=client.post('/api/rule-discovery',json={},headers=manager).json()
        url='/api/rule-discovery/'+report['id']+'/draft'
        payload={'candidate_ids':[report['candidates'][0]['id']]}
        assert client.post(url,json=payload,headers=reviewer).status_code==403
        assert client.post(url,json={'candidate_ids':[]},headers=manager).status_code==422
        response=client.post(url,json=payload,headers=manager)
        assert response.status_code==200 and response.json()['status']=='draft'


def test_composed_version_saves_exact_edits_once_with_candidate_provenance(discovery_store):
    s=discovery_store;active=s.policy();before=len(s.policies());report=s.mine_rules()
    candidate=report['candidates'][0]
    policy=deepcopy(active['data']);policy['name']='My chosen rules';policy['automation_enabled']=True
    chosen=deepcopy(candidate['rule']);chosen['conditions'][1]['value']=1234
    chosen['reason']='A custom explanation after reviewing the hypothesis.'
    policy['rules'].append(chosen)
    policy['rules'][0]['conditions'][0]['value']=25000
    saved=s.draft_from_candidates(report['id'],[candidate['id']],policy)
    assert len(s.policies())==before+1 and s.policy()==active
    assert saved['data']['name']=='My chosen rules'
    assert saved['data']['rules'][-1]['conditions'][1]['value']==1234
    assert saved['data']['rules'][0]['conditions'][0]['value']==25000
    assert len(saved['data']['rules'])==len(policy['rules'])
    source=s.draft_source(saved['id'])
    assert source['selected_candidate_ids']==[candidate['id']]
    assert source['candidates'][0]['rule']['conditions'][1]['value']!=1234


def test_omitted_candidate_cannot_be_claimed_as_included(discovery_store):
    s=discovery_store;report=s.mine_rules();before=len(s.policies())
    with pytest.raises(ValueError,match='must be included'):
        s.draft_from_candidates(report['id'],[report['candidates'][0]['id']],s.policy()['data'])
    assert len(s.policies())==before


def test_composer_api_accepts_final_policy_and_keeps_active_unchanged(tmp_path):
    with TestClient(create_app(tmp_path/'compose-api.sqlite3')) as client:
        headers={'X-Demo-Role':'manager'}
        before=client.get('/api/policies',headers=headers).json()
        report=client.post('/api/rule-discovery',json={},headers=headers).json()
        candidate=report['candidates'][0];policy=deepcopy(before[0]['data'])
        policy.update(name='Explicitly saved composed version',automation_enabled=True)
        policy['rules'].append(candidate['rule'])
        response=client.post('/api/rule-discovery/'+report['id']+'/draft',headers=headers,json={'candidate_ids':[candidate['id']],'policy':policy})
        assert response.status_code==200
        assert response.json()['data']['name']==policy['name']
        after=client.get('/api/policies',headers=headers).json()
        assert len(after)==len(before)+1
        assert next(p for p in after if p['status']=='active')==before[0]
