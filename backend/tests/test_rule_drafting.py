import copy
import json
import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from refundops.main import create_app
from refundops.domain import initial_policy
from refundops.llm import ProviderError
from refundops.rule_proposal import RuleProposal, propose_rule
from test_api_ai import provider, success


def new_rule():
    return {'id':'llm-id','name':'Review larger refunds','priority':500,
            'conditions':[{'field':'amount_cents','op':'gt','value':45000}],
            'match':'all','action':'review','reason_code':'high_value',
            'reason':'Refunds above $450 need a reviewer.','enabled':True}


def test_single_rule_uses_real_provider_boundary_without_writes(store,monkeypatch):
    sent=[]
    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200,json=success({'rule':new_rule()}))
    llm=provider(store,monkeypatch,handler)
    policy=initial_policy();before=copy.deepcopy(policy);versions=store.policies()
    result=propose_rule(llm,'Review above $450',policy)
    assert result['rule']['conditions'][0]['value']==45000
    assert result['rule']['id']!='llm-id' and not result['issues']
    assert policy==before and store.policies()==versions
    payload=json.loads(sent[0]['messages'][1]['content'])
    assert set(payload)=={'description','fields','reasons','existing_rules','semantic_criteria'}
    assert store.metrics()['refund_count']==0


@pytest.mark.parametrize('bad_field',['outcome_note','decision','facts.semantic.invented','api_key'])
def test_generated_unsupported_fields_are_not_addable(store,monkeypatch,bad_field):
    rule=new_rule();rule['conditions']=[{'field':bad_field,'op':'eq','value':'yes'}]
    llm=provider(store,monkeypatch,lambda _:httpx.Response(200,json=success({'rule':rule})))
    result=propose_rule(llm,'A request',initial_policy())
    assert result['rule'] is None and result['issues']


def test_contract_always_requires_a_rule():
    schema=RuleProposal.model_json_schema()
    assert set(schema['properties'])=={'rule'} and schema['required']==['rule']


@pytest.mark.parametrize('response',[{'clarification':'What amount is high value?'},{'rule':None},
                                     {'rule':new_rule(),'clarification':'What amount is high value?'}])
def test_questions_instead_of_a_rule_are_rejected(store,monkeypatch,response):
    llm=provider(store,monkeypatch,lambda _:httpx.Response(200,json=success(response)))
    with pytest.raises(ProviderError):
        propose_rule(llm,'Review large requests',initial_policy())


@pytest.mark.parametrize('action',['information','hold'])
def test_legacy_proposal_routes_and_unknown_reason_are_normalized(store,monkeypatch,action):
    rule={**new_rule(),'action':action,'reason_code':'invented_reason','reason':''}
    llm=provider(store,monkeypatch,lambda _:httpx.Response(200,json=success({'rule':rule})))
    result=propose_rule(llm,'Review above $450',initial_policy())
    assert not result['issues']
    assert result['rule']['action']=='review' and result['rule']['reason_code']=='policy_rule'


def test_general_reason_is_not_overridden_by_a_rule_identifier():
    from refundops.catalog import explain,rule_reasons
    from refundops.domain import evaluate,normalize
    from conftest import raw
    policy=initial_policy();policy['rules'][0]['reason_code']='policy_rule'
    request=normalize(raw(amount_usd='350',stated_reason='wrong_size',customer_note='',support_note=''))
    evidence={'facts':{},'complete':True}
    evaluation=explain(evaluate(request,evidence,policy),request,evidence)
    assert evaluation['rule_id']=='amount-limit' and evaluation['reason_label']=='General'
    assert not {'analysis_incomplete','setup_required'} & rule_reasons().keys()


def test_proposal_api_permissions_and_provider_failure(tmp_path,monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY','')
    app=create_app(tmp_path/'rules.sqlite3',seed=False,auto_analyze=False)
    with TestClient(app) as c:
        body={'instruction':'Review above $450','policy':initial_policy()}
        assert c.post('/api/policies/propose-rule',json=body,headers={'X-Demo-Role':'reviewer'}).status_code==403
        c.headers['X-Demo-Role']='manager'
        assert c.post('/api/policies/propose-rule',json=body).status_code==422
        assert c.post('/api/policies/propose-rule',json={**body,'instruction':' '}).status_code==422
        assert len(app.state.store.policies())==1
