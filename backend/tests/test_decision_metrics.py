from copy import deepcopy
import json
import pytest
from refundops.decision_metrics import build_report, historical_reference, historical_rows, shadow_reports
from refundops.domain import initial_policy, normalize
from refundops.financial import ReleaseSettings, financial_report
from refundops.policy_management import compare_backtest, compare_shadow
from conftest import raw, csv_text, small_policy


def row(rid='R1', old='review', new='auto_approve', amount=4000, allowed=4000, customer=None, before=True, **changes):
    def ev(action):
        return {'action':action,'queue':'fraud' if action=='fraud' else 'review', 'reason_code':'policy_rule',
                'proposed_amount_cents':amount if action=='auto_approve' else None,'trace':[],'resolution':{},'rule_id':None}
    value={'id':rid,'data':normalize(raw(request_id=rid,customer_id=customer or rid,amount_usd=str(amount/100))),
           'baseline':ev(old),'candidate':ev(new),'evidence':{'complete':True,'method':'reviewed','facts':{}},
           'cohort':'prospective','label':{'allowed_cents':allowed,'captured_before_review':before,'critical':False,'source':'human_decision','minutes':0},
           'conflict':False}
    value.update(changes)
    return value


def report(rows, settings=None, mode='shadow', **meta):
    p=initial_policy()
    return build_report(rows,p,p,settings,mode=mode,metadata={'scope':'prospective',**meta})


def test_zero_data_is_unknown_not_green():
    r=report([])
    assert r['candidate']['auto_rate'] is None
    assert r['candidate']['error_upper_95'] is None
    assert r['money']['stress_loss_cents'] is None
    assert all(c['status']=='unknown' for c in r['criteria'])
    assert r['money']['measured_roi_cents'] is None


def test_added_reviews_and_shared_ai_do_not_become_fake_savings():
    rows=[row('a'),row('b',old='auto_approve',new='review')]
    r=report(rows)
    assert r['workload']['saved']==r['workload']['added']==8
    assert r['workload']['net_minutes_freed']==0
    assert r['money']['labor_delta_cents']==0
    assert r['money']['shared_ai_cost_cents']==4
    assert r['money']['extra_ai_cost_cents']==0
    assert r['money']['operating_margin_cents']==0
    assert r['workload']['recorded_saved']==0  # operational placeholder minutes=0 is not measured time


def test_paired_excess_uses_union_including_removed_automation():
    r=report([row('new',allowed=3000),row('returned',old='auto_approve',new='review',allowed=0)])
    assert r['candidate']['overpayment_cents']==1000
    assert r['baseline']['overpayment_cents']==4000
    assert r['safety']['paired_excess_delta_cents']==-3000
    assert r['safety']['paired_auto_reference_count']==2


def test_late_unknown_and_missing_capture_labels_never_qualify():
    rows=[row('late',before=False),row('unknown',allowed=None),row('unspecified')]
    del rows[-1]['label']['captured_before_review']
    r=report(rows)
    assert r['candidate']['reviewed_auto']==0
    assert r['candidate']['unreviewed_cents']==12000
    assert r['candidate']['error_upper_95'] is None
    assert r['money']['net_against_correct_review_cents'] is None


def test_customer_dependence_and_partial_group_exclusion():
    rows=[row('a',customer='same'),row('b',customer='same'),row('c',allowed=None),row('d',customer='partial'),row('e',customer='partial',allowed=None)]
    r=report(rows)
    assert r['candidate']['reviewed_auto']==3
    assert r['candidate']['reviewed_customer_groups']==1
    assert r['candidate']['error_upper_95']==pytest.approx(.95)


def test_thirty_zero_error_groups_still_have_nonzero_upper_risk():
    r=report([row(str(i)) for i in range(30)])
    assert r['candidate']['error_upper_95']==pytest.approx(1-.05**(1/30))
    assert r['candidate']['error_upper_95']>0.09
    assert r['money']['stress_loss_cents']>90000


def test_historical_auto_and_unknown_partial_are_not_correctness_labels():
    history=[normalize(raw(request_id='a',decision='approved',decided_by='auto')),
             normalize(raw(request_id='b',decision='partial',decided_by='human',outcome_note='shipping only')),
             normalize(raw(request_id='c',decision='partial',decided_by='human',amount_usd='78',outcome_note='30% issued'))]
    assert historical_reference(history[1])['allowed_cents'] is None
    assert historical_reference(history[2])['allowed_cents']==2340
    r=build_report(historical_rows(history,initial_policy(),initial_policy()),initial_policy(),initial_policy(),mode='backtest')
    assert r['quality']['reference_count']==1
    assert r['candidate']['error_upper_95'] is None
    assert r['quality']['unknown_outcomes']==1
    assert r['safety']['chargeback_probability'] is None


def test_adverse_outcomes_are_diagnostic_not_prevented_losses():
    r=report([row('bad',old='auto_approve',new='review',outcomes=[{'type':'chargeback'}])])
    assert r['safety']['known_chargebacks']==1
    assert r['safety']['chargebacks_sent_to_review']==1
    assert r['safety']['chargeback_fee_only_cents']==2500
    assert r['safety']['chargeback_loss_cents'] is None
    assert r['money']['measured_roi_cents'] is None
    assert r['quality']['outcome_notes']==1


def test_every_segment_dimension_preserves_denominators():
    rows=[row('RF-1001'),row('RF-2001',amount=11000,allowed=9000),row('c',new='fraud')]
    r=report(rows)
    for dimension in {s['dimension'] for s in r['segments']}:
        group=[s for s in r['segments'] if s['dimension']==dimension]
        assert sum(s['total'] for s in group)==3
        assert sum(s['candidate_auto'] for s in group)==2
        assert sum(s['overpayment_cents'] for s in group)==2000
    assert {s['value'] for s in r['segments'] if s['dimension']=='source_channel'}=={'Web form','Support desk','Other / unknown'}


def observation(r,cohort='prospective'):
    return {'request_id':r['id'],'snapshot':{'external_id':r['id'],'data':r['data'],'evidence':r['evidence'],'conflict':False},
            'baseline':r['baseline'],'candidate':r['candidate'],'label':r['label'],'cohort':cohort}


def test_scopes_are_disjoint_and_backlog_never_qualifies():
    obs=[observation(row('old'),'backlog'),observation(row('new'))]
    reports=shadow_reports(obs,initial_policy(),initial_policy(),ReleaseSettings().model_dump())
    assert [reports[k]['quality']['total'] for k in ('prospective','backlog','all')]==[1,1,2]
    assert reports['prospective']['metadata']['qualification_eligible']
    assert not reports['backlog']['metadata']['qualification_eligible']
    assert not reports['all']['metadata']['qualification_eligible']
    compared=shadow_reports(obs,initial_policy(),initial_policy(),ReleaseSettings().model_dump(),{'comparison_only':True})
    assert not compared['prospective']['metadata']['qualification_eligible']


def test_legacy_financial_scenario_also_counts_added_work_and_excludes_late_labels():
    settings=ReleaseSettings().model_dump()
    r=financial_report([observation(row('new',before=False)),observation(row('returned',old='auto_approve',new='review'))],settings)
    assert r['scenario_labor_savings_cents']==0
    assert r['scenario_net_on_observed_cases_cents'] is None


def test_stored_replay_is_frozen_and_comparison_is_side_effect_free(store):
    h=store.import_preview(csv_text(raw(request_id='H1',decision='approved',decided_by='human',review_minutes='5')),'h.csv','history')
    store.import_commit(h['id'])
    p=store.save_draft(small_policy(store.policy()['data'],7500))
    check=store.create_experiment(p['data'],policy_id=p['id'])
    replay=store.backtest_experiment(check['id'])
    assert replay['decision_report']['quality']['total']==1
    before=store.experiment(check['id'])['backtest']
    compared=compare_backtest(store,[p['id']])
    assert compared['versions'][0]['decision_report']['quality']['total']==1
    assert store.experiment(check['id'])['backtest']==before
    with store.tx() as c:
        data=json.loads(c.execute('SELECT data FROM history').fetchone()[0]);data['outcome_note']='chargeback'
        c.execute('UPDATE history SET data=?',(json.dumps(data),))
    assert store.experiment(check['id'])['backtest']==before
    assert compare_backtest(store,[p['id']])['versions'][0]['decision_report']['safety']['known_chargebacks']==1


def test_shadow_comparison_uses_common_cohort_when_versions_start_apart(store):
    def start():
        p=store.save_draft(small_policy(store.policy()['data'],7500))
        ex=store.create_experiment(p['data'],policy_id=p['id']);store.backtest_experiment(ex['id']);store.start_experiment(ex['id'])
        return p
    def incoming(rid):
        batch=store.import_preview(csv_text(raw(request_id=rid,customer_id=rid)),rid+'.csv','pending');store.import_commit(batch['id'])
    a=start();incoming('between');b=start();incoming('after')
    result=compare_shadow(store,[a['id'],b['id']])
    for v in result['versions']:
        reports=v['decision_reports']
        assert reports['prospective']['quality']['total']==1
        assert reports['backlog']['quality']['total']==1
        assert reports['prospective']['cases'][0]['id']=='after'
        assert not reports['prospective']['metadata']['qualification_eligible']
    assert result['current_decision_reports']['prospective']['quality']['total']==1
