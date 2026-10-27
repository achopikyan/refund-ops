"""Source-specific acceptance plus unseen boundary and safety regressions."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from fastapi.testclient import TestClient
from refundops.source_rebuild import load_sources,infer_legacy,build_policies,populate,context_issues
from refundops.domain import normalize,validate_policy,validate_evidence,evaluate,pending_evidence,payment_constraint,PolicyChecks,FACTS
from refundops.catalog import evidence_questions,catalog,rule_reasons
from refundops.llm import evidence_input
from refundops.storage import Store,Conflict
from conftest import ROOT,raw,csv_text
from source_expectations import pending_fixture, audit_sources


@pytest.fixture(scope='module')
def source():
    s=load_sources(ROOT/'data');inferred=infer_legacy(s['history']['rows']);v1,v2=build_policies(inferred)
    return s,inferred,v1,v2,pending_fixture(s)


def test_reconstruction_is_reproducible_without_pending_or_outcomes(source):
    s,i,*_=source
    assert (i['amount_below_cents'],i['minimum_tenure_months'],i['maximum_prior_refunds'])==(5500,9,0)
    assert i['training']['correct']==178 and i['training']['total']==179
    assert i['later_customer_disjoint']['correct']==60
    changed=deepcopy(s['history']['rows'])
    for r in changed:r.update(outcome_note='fabricated future',decision='rejected',review_minutes='999')
    assert infer_legacy(changed)==i


def test_every_pending_case_has_an_explicit_policy_acceptance_result(source):
    s,i,v1,v2,f=source;a=audit_sources(s,v1,v2,i,f)
    assert a['pending_acceptance']['passed']==a['pending_acceptance']['total']==20
    cases={c['id']:c for c in a['pending_acceptance']['cases']}
    assert cases['RF-1074']['v1_action']==cases['RF-1075']['v1_action']=='auto_approve'
    assert cases['RF-1074']['v2_action']==cases['RF-1075']['v2_action']=='review'
    assert cases['RF-1069']['v2_action']==cases['RF-2182']['v2_action']=='auto_approve'
    assert cases['RF-2183']['v2_reason']=='conflicting_versions'


def test_both_versions_use_ordinary_settings_and_can_start_checks(source,tmp_path):
    s,i,v1,v2,f=source;store=Store(tmp_path/'seed.sqlite3')
    report=audit_sources(s,v1,v2,i,f);ids=populate(store,s,v1,v2,report);store.seed(ROOT/'data')
    assert len(store.policies())==2 and store.policy()['version']==2
    assert all('evaluation_mode' not in p['data'] for p in store.policies())
    assert v1['checks']['evidence_analysis'] is False and all(v2['checks'].values())
    ex=store.create_experiment(v1,policy_id=ids[0]);store.backtest_experiment(ex['id'])
    assert store.experiment(ex['id'])['status']=='backtested'
    store.start_experiment(ex['id'])
    assert store.experiment(ex['id'])['status']=='shadow'
    assert store.metrics()['refund_count']==0 and all(r['decision'] is None and r['data']['decision']=='pending' for r in store.requests())


def test_prepared_database_contains_no_fake_evidence_or_outcomes(source,tmp_path):
    s,i,v1,v2,f=source;store=Store(tmp_path/'fresh.sqlite3');populate(store,s,v1,v2,audit_sources(s,v1,v2,i,f));store.seed(ROOT/'data')
    assert len(store.requests())==20 and store.state()['mode']=='simulate'
    assert store.request('RF-2183')['conflict'] and len(store.request('RF-2183')['versions'])==2
    for r in store.requests():assert r['evidence']['method'] is None and r['evidence']['facts']=={} and not r['evidence']['complete'] and not r['decision'] and not r['ledger']
    with store.connect() as c:
        for table in ('ledger','decisions','outcomes','observations','release_limits','llm_cache'):
            assert c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0


def test_future_request_fields_are_never_llm_input(source):
    s,_,_,_,_=source;r=deepcopy(s['pending']['rows'][0])
    r.update(decision='approved',decided_by='LEAK',outcome_note='SECRET FUTURE',review_minutes='900',predictions='SHADOW',audit='INTERNAL')
    payload,_=evidence_input(r)
    assert set(payload)=={'requested_at','amount_cents','category','payment_method','tenure_months','prior_refunds_12m','days_since_delivery','fraud_flag','stated_reason','customer_note','support_note'}
    assert not any(value in json.dumps(payload) for value in ('LEAK','SECRET FUTURE','SHADOW','INTERNAL'))


def test_context_references_are_resolved_from_request_and_reject_future_fields():
    r=normalize(raw(stated_reason='arrived_damaged',customer_note='it is fine',days_since_delivery='22'))
    out={'summary':'Conflict','facts':[{'name':'reason_conflict','value':'yes','source':'customer_note','quote':'it is fine','context_fields':['stated_reason','days_since_delivery']}]}
    e=validate_evidence(r,out,'live')
    assert e['facts']['reason_conflict']['context']=={'stated_reason':'arrived_damaged','days_since_delivery':22}
    out['facts'][0]['context_fields']=['outcome_note']
    assert not validate_evidence(r,out,'live')['complete']


def test_catalog_covers_every_predefined_fact_and_new_evidence(source):
    assert set(q['id'] for q in evidence_questions())==FACTS
    assert len(FACTS)==21
    assert {'damage_origin','partial_damage','no_product_damage','batch_defect','carrier_incident'}<=rule_reasons().keys()
    fields=catalog(FACTS)
    assert fields['category']['values']==['apparel','home','electronics']
    assert len(fields['facts.effective_reason']['values'])==6


@pytest.mark.parametrize('conditions',[
    [{'field':'amount_cents','op':'gt','value':30000},{'field':'amount_cents','op':'lte','value':5000}],
    [{'field':'category','op':'eq','value':'home'},{'field':'category','op':'eq','value':'apparel'}],
    [{'field':'category','op':'in','value':['home']},{'field':'category','op':'ne','value':'home'}],
    [{'field':'facts.photo','op':'eq','value':'maybe'}],
    [{'field':'category','op':'eq','value':'nonsense'}],
    [{'field':'amount_cents','op':'in','value':['100']}],
    [{'field':'amount_cents','op':'in','value':[]}],
    [{'field':'outcome_note','op':'eq','value':'chargeback'}],
])
def test_invalid_and_impossible_conditions_are_rejected(source,conditions):
    p=deepcopy(source[3]);p['rules'][0]['conditions']=conditions
    assert validate_policy(p)[1]


def test_or_conditions_are_not_mistaken_for_impossible_and(source):
    p=deepcopy(source[3]);p['rules'][0].update(match='any',conditions=[{'field':'category','op':'eq','value':'home'},{'field':'category','op':'eq','value':'apparel'}])
    assert not validate_policy(p)[1]


def test_customer_context_uses_only_earlier_requests(source):
    s=source[0];r=next(r for r in s['pending']['rows'] if r['request_id']=='RF-1077')
    assert context_issues(r,s['history']['rows'])
    future={**r,'requested_at':'2027-01-01','tenure_months':90}
    assert not context_issues(r,[future])


@pytest.mark.parametrize('fact,reason',[('partial_damage','partial_damage'),('no_product_damage','no_product_damage'),('customer_damage','damage_origin'),('cosmetic','partial_judgment')])
def test_new_business_checks_cannot_be_bypassed_by_a_broad_approve(source,fact,reason):
    r=normalize(raw(stated_reason='arrived_damaged',amount_usd='40'))
    e={'facts':{fact:{'value':'yes'}},'complete':True}
    assert evaluate(r,e,source[3])['reason_code']==reason


def test_photo_not_video_and_required_checks_apply_at_payment(source):
    p=source[3];r=normalize(raw(stated_reason='arrived_damaged',amount_usd='140',support_note='video received - flicker visible'))
    e=validate_evidence(r,{'summary':'Authored video-only model response','facts':[{'name':'video','value':'yes','source':'support_note','quote':'video received'}]},'live')
    assert e['facts']['video']['value']=='yes' and e['facts'].get('photo',{}).get('value')!='yes'
    assert evaluate(r,e,p)['reason_code']=='photo_required'
    assert 'photo' in payment_constraint(r,e,p,'approved')
    r=normalize(raw(stated_reason='changed_mind',days_since_delivery='15'))
    assert payment_constraint(r,pending_evidence(r),p,'approved')
    assert not payment_constraint(r,pending_evidence(r),p,'rejected')


@pytest.mark.parametrize('amount,expected', [('150','auto_approve'),('150.01','review'),('210','review')])
def test_photo_alone_has_a_visible_bounded_automation_limit(source,amount,expected):
    request=normalize(raw(stated_reason='arrived_damaged',category='home',amount_usd=amount))
    evidence={'method':'live','complete':True,'facts':{'photo':{'value':'yes'}}}
    result=evaluate(request,evidence,source[3])
    assert result['action']==expected
    if expected=='auto_approve':assert result['rule_id']=='verified-damage'


@pytest.mark.parametrize('fact,reason',[('customer_damage','damage_origin'),('no_product_damage','no_product_damage')])
def test_photo_cannot_override_confirmed_customer_damage_or_intact_product(source,fact,reason):
    request=normalize(raw(stated_reason='arrived_damaged',category='apparel',amount_usd='120'))
    evidence={'method':'live','complete':True,'facts':{'photo':{'value':'yes'},fact:{'value':'yes'}}}
    result=evaluate(request,evidence,source[3])
    assert result['action']=='review' and result['reason_code']==reason


def test_rf2082_is_not_automated_even_when_photo_is_present(source):
    request=next(r for r in source[0]['history']['rows'] if r['request_id']=='RF-2082')
    # Authored model-response facts exercise policy handling, never production inference.
    for facts in ({'photo':{'value':'yes'}}, {'photo':{'value':'yes'},'customer_damage':{'value':'yes'}}):
        result=evaluate(request,{'method':'live','complete':True,'facts':facts},source[3])
        assert result['action']=='review' and result['reason_code']=='damage_origin'


def test_broader_candidate_keeps_damage_exposure_as_visible_rule_tradeoff(source):
    from refundops.source_rebuild import broader_candidate
    v2=source[3]
    v3=broader_candidate(v2)
    request=normalize(raw(stated_reason='arrived_damaged',category='electronics',amount_usd='210'))
    evidence={'method':'live','complete':True,'facts':{'photo':{'value':'yes'}}}
    assert evaluate(request,evidence,v2)['action']=='review'
    assert evaluate(request,evidence,v3)['action']=='auto_approve'
    rule=next(rule for rule in v3['rules'] if rule['id']=='verified-damage')
    assert '$300' in rule['name']
    assert next(c for c in rule['conditions'] if c['field']=='amount_cents')['value']==30000
    assert not any(c['field']=='category' for c in rule['conditions'])
    # Explicit adverse findings remain blocked by visible policy-wide checks.
    evidence['facts']['customer_damage']={'value':'yes'}
    assert evaluate(request,evidence,v3)['action']=='review'


def test_confirmed_fraud_uses_full_refund_without_return_photo(source):
    r=normalize(raw(stated_reason='arrived_damaged',amount_usd='120',fraud_flag=''))
    e={'complete':True,'facts':{'fraud_confirmed':{'value':'yes'}}}
    assert evaluate(r,e,source[3])['action']=='auto_approve'
    assert not payment_constraint(r,e,source[3],'approved')
    assert payment_constraint(r,e,source[3],'partial')


def test_delivery_proof_is_not_downgraded_to_late_delivery(source):
    r=normalize(raw(stated_reason='never_arrived',amount_usd='1150'))
    e={'complete':True,'facts':{'proof_delivery':{'value':'yes'},'delivered':{'value':'yes'}}}
    assert evaluate(r,e,source[3])['reason_code']=='delivery_proof'


def test_live_prompt_has_explicit_definitions_and_complete_coverage_requirement(store,monkeypatch):
    from refundops.llm import EvidenceExtractor,ProviderError
    llm=EvidenceExtractor(store)
    seen={}
    def call(purpose,system,payload,schema,**kwargs):
        seen.update(system=system,payload=payload)
        value={'facts':[],'summary':'No supported findings','assessed_facts':sorted(FACTS)}
        kwargs['validator'](value)
        return value
    monkeypatch.setattr(llm,'call',call)
    result=llm.extract(normalize(raw()),[])
    assert set(result['assessed_facts'])==FACTS
    assert set(seen['payload']['predefined_questions'])==FACTS
    assert 'AFTER delivery' in seen['system']
    assert 'billing' in seen['payload']['predefined_questions']['address_mismatch']
    assert 'Carrier tracking' in seen['payload']['predefined_questions']['delivered']
    def incomplete(purpose,system,payload,schema,**kwargs):
        kwargs['validator']({'facts':[],'summary':'Partial inspection','assessed_facts':['photo']})
    monkeypatch.setattr(llm,'call',incomplete)
    with pytest.raises(ProviderError,match='every predefined'):llm.extract(normalize(raw()),[])


def test_new_file_launch_uses_v2_and_only_new_pending(tmp_path,monkeypatch):
    from refundops.main import create_app
    incoming=tmp_path/'incoming.csv';incoming.write_text(csv_text(raw(request_id='RF-NEW')),encoding='utf-8')
    monkeypatch.setenv('REFUNDOPS_SOURCE_POLICIES','1');monkeypatch.setenv('REFUNDOPS_PENDING_CSV',str(incoming))
    app=create_app(tmp_path/'import.sqlite3',auto_analyze=False)
    with TestClient(app):
        s=app.state.store
        assert s.policy()['version']==2 and len(s.policies())==3
        assert [r['external_id'] for r in s.requests()]==['RF-NEW']
        assert s.metrics()['refund_count']==0


def test_history_electronics_damage_stays_review_even_if_model_misses_origin(source):
    # RF-2082: photo availability alone must not authorize this ambiguous damage claim.
    s,_,_,v2,_=source
    row=next(r for r in s['history']['rows'] if r['request_id']=='RF-2082')
    from conftest import model_evidence
    evidence=model_evidence({'photo':{'value':'yes','source':'support_note','quote':'Authored test assumption: photo confirmed'}})
    result=evaluate(row,evidence,v2)
    assert result['action']=='review'
    assert result['rule_id']=='electronics-damage-review'
