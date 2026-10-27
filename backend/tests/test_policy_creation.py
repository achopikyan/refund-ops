from fastapi.testclient import TestClient
from refundops.main import create_app
from refundops.domain import initial_policy


def test_scratch_and_copy_keep_distinct_lineage_and_do_not_change_current(tmp_path):
    app=create_app(tmp_path/'creation.sqlite3',seed=False,auto_analyze=False)
    store=app.state.store
    original=store.policy()
    with TestClient(app,headers={'X-Demo-Role':'manager'}) as client:
        blank={**initial_policy(),'rules':[],'criteria':[],'small_customer_enabled':False}
        response=client.post('/api/policies/drafts?from_scratch=true',json=blank)
        assert response.status_code==200,response.text
        scratch=response.json()
        assert scratch['parent_id'] is None and scratch['data']['rules']==[]
        assert scratch['source'] is None and scratch['status']=='draft'
        copied=client.post('/api/policies/drafts?parent_id='+scratch['id'],json=scratch['data']).json()
        assert copied['parent_id']==scratch['id']
        assert copied['version']>scratch['version']
        assert client.post('/api/policies/drafts?from_scratch=true&parent_id='+original['id'],json=blank).status_code==422
        assert store.policy()==original
        assert client.post('/api/policies/drafts?from_scratch=true',json=blank,headers={'X-Demo-Role':'reviewer'}).status_code==403


def test_edit_saves_same_version_and_rejects_stale_or_locked_updates(tmp_path):
    app=create_app(tmp_path/'editing.sqlite3',seed=False,auto_analyze=False)
    store=app.state.store
    current=store.policy()
    draft=store.save_draft(initial_policy())
    revised={**draft['data'],'change_mind_days':20}
    with TestClient(app,headers={'X-Demo-Role':'manager'}) as c:
        url='/api/policies/'+draft['id']+'/draft'
        body={'policy':revised,'expected_policy':draft['data']}
        assert c.put(url,json=body,headers={'X-Demo-Role':'reviewer'}).status_code==403
        updated=c.put(url,json=body)
        assert updated.status_code==200,updated.text
        assert updated.json()['id']==draft['id'] and updated.json()['version']==draft['version']
        assert updated.json()['parent_id']==draft['parent_id']
        assert len(store.policies())==2 and store.policy()==current

        assert c.put(url,json=body).status_code==409
        assert c.put('/api/policies/'+current['id']+'/draft',json={'policy':revised,'expected_policy':current['data']}).status_code==409
        check=store.create_experiment(revised,policy_id=draft['id'])
        revised2={**revised,'change_mind_days':25}
        assert c.put(url,json={'policy':revised2,'expected_policy':revised}).status_code==200
        assert store.experiment(check['id'])['policy']==revised2
        store.backtest_experiment(check['id'])
        assert c.put(url,json={'policy':revised,'expected_policy':revised2}).status_code==409
        store.stop_experiment(check['id'],'Done observing')
        assert c.put(url,json={'policy':revised,'expected_policy':revised2}).status_code==409
        assert len(store.policies())==2 and store.policy()==current


def test_legacy_descriptions_are_ignored_without_losing_policy_rules(tmp_path):
    import json
    from refundops.domain import Policy, fingerprint
    app=create_app(tmp_path/'legacy-metadata.sqlite3',seed=False,auto_analyze=False)
    store=app.state.store
    draft=store.save_draft(initial_policy())
    legacy={**draft['data'],'description':'Retired demo description'}
    with store.tx() as c:
        c.execute('UPDATE policies SET data=?,hash=? WHERE id=?',(json.dumps(legacy),fingerprint(legacy),draft['id']))
    assert 'description' not in Policy.model_json_schema()['properties']
    assert Policy.model_validate(legacy).model_dump()==draft['data']
    with TestClient(app,headers={'X-Demo-Role':'manager'}) as c:
        for path in ['/api/policies','/api/policy-versions']:
            result=c.get(path).json()
            rows=result if isinstance(result,list) else result['versions']
            restored=next(p for p in rows if p['id']==draft['id'])
            assert 'description' not in restored['data']
            assert restored['data']['rules']==draft['data']['rules']
        result=c.put('/api/policies/'+draft['id']+'/draft',json={'policy':legacy,'expected_policy':legacy})
        assert result.status_code==200,result.text
        assert 'description' not in result.json()['data']
        assert result.json()['id']==draft['id'] and result.json()['version']==draft['version']


def test_policy_limits_are_saved_frozen_and_cannot_be_overridden_in_backtest(tmp_path):
    from refundops.financial import ExecutionLimits
    app=create_app(tmp_path/'policy-limits.sqlite3',seed=False,auto_analyze=False)
    p={**initial_policy(),'execution_limits':{**ExecutionLimits().model_dump(),'max_single_cents':8500,'daily_cents':25000}}
    with TestClient(app,headers={'X-Demo-Role':'manager'}) as c:
        saved=c.post('/api/policies/drafts',json=p).json()
        invalid=c.post('/api/trials',json={'policy_id':saved['id'],'policy':p,'settings':{'max_single_cents':9999}})
        assert invalid.status_code==422 and 'Execution limits belong' in invalid.text
        response=c.post('/api/trials',json={'policy_id':saved['id'],'policy':p})
        assert response.status_code==200,response.text
        check=response.json()
        assert check['settings']['max_single_cents']==8500 and check['settings']['daily_cents']==25000
        updated={**p,'execution_limits':{**p['execution_limits'],'release_count':12}}
        response=c.put('/api/policies/'+saved['id']+'/draft',json={'policy':updated,'expected_policy':p})
        assert response.status_code==200,response.text
        assert c.get('/api/trials/'+check['id']).json()['experiment']['settings']['release_count']==12
        c.post('/api/trials/'+check['id']+'/backtest')
        assert c.put('/api/policies/'+saved['id']+'/draft',json={'policy':p,'expected_policy':updated}).status_code==409
        library=c.get('/api/policy-versions').json()
        version=next(v for v in library['versions'] if v['id']==saved['id'])
        assert version['execution_limits']==updated['execution_limits']
        assert len(app.state.store.policies())==2


def test_old_versions_show_recorded_limits_without_rewriting_policy(store):
    from refundops.policy_management import policy_library
    p=initial_policy();p.pop('execution_limits',None)
    saved=store.save_draft(p)
    ex=store.create_experiment(p,{'max_single_cents':7000,'daily_cents':17500},saved['id'])
    version=next(v for v in policy_library(store)['versions'] if v['id']==saved['id'])
    assert version['execution_limits']['max_single_cents']==7000
    assert version['execution_limits']['daily_cents']==17500
    assert version['data']['execution_limits'] is None
    assert store.experiment(ex['id'])['settings']['max_single_cents']==7000


def test_global_cost_defaults_do_not_rewrite_existing_checks(store):
    original=store.cost_assumptions()
    first=store.create_experiment(initial_policy())
    updated={**original,'hourly_cost_cents':4500,'review_minutes':6.0}
    store.update_cost_assumptions(updated,original)
    second=store.create_experiment(initial_policy())
    assert store.experiment(first['id'])['settings']['hourly_cost_cents']==3000
    assert second['settings']['hourly_cost_cents']==4500 and second['settings']['review_minutes']==6
    from refundops.storage import Conflict
    import pytest
    with pytest.raises(Conflict):store.update_cost_assumptions(original,original)


def test_shadow_requirements_can_change_after_replay_but_lock_at_start(store):
    from refundops.financial import ShadowRequirements
    from refundops.storage import Conflict
    import pytest
    ex=store.create_experiment(initial_policy());store.backtest_experiment(ex['id'])
    before=store.experiment(ex['id']);expected={key:before['settings'][key] for key in ShadowRequirements.model_fields}
    values={**expected,'min_shadow_hours':48.0,'min_prospective_auto':50}
    store.update_shadow_requirements(ex['id'],values,expected)
    assert store.experiment(ex['id'])['backtest']==before['backtest']
    assert store.experiment_report(ex['id'])['observations']==[]
    with pytest.raises(Conflict):store.update_shadow_requirements(ex['id'],expected,expected)
    store.start_experiment(ex['id'])
    with pytest.raises(Conflict):store.update_shadow_requirements(ex['id'],expected,values)
    assert store.experiment(ex['id'])['settings']['min_prospective_auto']==50
