"""Transport-level tests use the official SDK with mocked HTTP, never real keys."""
import json

import httpx2
import pytest
from openai import DefaultHttpx2Client, OpenAI as OfficialOpenAI

from refundops.domain import fingerprint
from refundops.llm import EvidenceExtractor, ProviderError
from refundops.providers import AIProvider
import refundops.providers as providers

SCHEMA = {'type':'object','properties':{'status':{'type':'string'}},'required':['status'],'additionalProperties':False}
OPENAI_KEY = 'sk-proj-unit-test-only-no-secret'
ROUTER_KEY = 'sk-or-unit-test-only-no-secret'


@pytest.fixture
def provider(store, monkeypatch):
    for name in ('AI_PROVIDER','OPENAI_API_KEY','OPENROUTER_API_KEY','OPENAI_MODEL','OPENROUTER_MODEL'):
        # Empty values prevent a later main.py import from reloading local .env keys.
        monkeypatch.setenv(name, '')
    return AIProvider(store)


def mock_sdk(monkeypatch, handler):
    def factory(**kwargs):
        kwargs['http_client'].close()
        kwargs['http_client'] = DefaultHttpx2Client(transport=httpx2.MockTransport(handler), follow_redirects=False)
        return OfficialOpenAI(**kwargs)
    monkeypatch.setattr(providers, 'OpenAI', factory)


def completion(request, *, cost=None, refusal=None, finish='stop'):
    body = json.loads(request.content)
    usage = {'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}
    if cost is not None:
        usage['cost'] = cost
    return httpx2.Response(200, json={'id':'completion-'+body['model'],'object':'chat.completion','created':1,
        'model':body['model'],'choices':[{'index':0,'finish_reason':finish,
        'message':{'role':'assistant','content':'{"status":"ok"}', 'refusal':refusal}}], 'usage':usage})


def test_clean_install_defaults_to_direct_openai(provider):
    assert provider.provider == 'openai' and provider.model == 'gpt-6.1-sol'
    assert provider.status()['base_url'] == 'https://api.openai.com/v1'
    assert provider.manifest()['provider'] == 'openai'
    assert not provider.key
    assert not hasattr(provider, 'acceptance')
    assert not {'qualified', 'validation'} & provider.status().keys()


def test_existing_router_environment_keeps_original_manifest(store,monkeypatch):
    monkeypatch.delenv('AI_PROVIDER',raising=False)
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    monkeypatch.setenv('OPENROUTER_API_KEY',ROUTER_KEY)
    monkeypatch.setenv('OPENROUTER_MODEL','openai/gpt-6.1-sol')
    selected = AIProvider(store)
    assert selected.provider == 'openrouter'
    base = EvidenceExtractor(store)
    base.model = selected.model
    assert selected.manifest() == base.manifest()


@pytest.mark.parametrize('name,key,host,model',[
    ('openai',OPENAI_KEY,'api.openai.com','gpt-6.1-sol'),
    ('openrouter',ROUTER_KEY,'openrouter.ai','openai/gpt-6.1-sol'),
])
def test_official_sdk_sends_correct_provider_specific_request(provider,monkeypatch,name,key,host,model):
    requests = []
    def handler(request):
        requests.append(request)
        return completion(request,cost=.0042 if name=='openrouter' else None)
    mock_sdk(monkeypatch,handler)
    provider.configure(provider=name,key=key)
    assert provider.model == model
    assert provider.call('connection_check','Return ok',{},SCHEMA) == {'status':'ok'}
    request = requests[0]
    assert request.url.host == host
    assert request.url.path == ('/api/v1/chat/completions' if name=='openrouter' else '/v1/chat/completions')
    assert request.headers['authorization'] == 'Bearer '+key
    body = json.loads(request.content)
    assert body['model'] == model and body['response_format']['json_schema']['strict'] is True
    assert body['messages'][1]['content'] == '{}'
    if name=='openrouter':
        assert body['provider'] == {'require_parameters':True,'allow_fallbacks':False}
        assert body['max_tokens'] == 5000 and 'max_completion_tokens' not in body
    else:
        assert body['max_completion_tokens'] == 5000 and body['store'] is False
        assert 'provider' not in body and 'max_tokens' not in body
    with provider.store.connect() as connection:
        recorded = dict(connection.execute('SELECT * FROM llm_calls').fetchone())
    assert recorded['provider'] == name and recorded['model'] == model
    assert recorded['cost'] == (.0042 if name=='openrouter' else None)
    assert json.loads(recorded['usage'])['total_tokens'] == 120
    assert key not in json.dumps(recorded)
    provider.call('connection_check','Return ok',{},SCHEMA)
    assert len(requests) == 1, 'Second call must reuse the validated cache'


def test_router_existing_cache_is_reused_without_network(provider,monkeypatch):
    provider.configure(key=ROUTER_KEY,model='openai/gpt-6.1-sol')
    key=fingerprint([provider.model,provider.PROMPT_VERSION,'Return ok',{},SCHEMA])
    with provider.store.tx() as connection:
        connection.execute('INSERT INTO llm_cache VALUES(?,?,?)',(key,'{"status":"ok"}','2026-10-27'))
    monkeypatch.setattr(provider,'sdk',lambda **_:pytest.fail('Existing cache must not call the provider'))
    assert provider.call('evidence','Return ok',{},SCHEMA)=={'status':'ok'}


def test_provider_switch_changes_identity_and_never_reuses_wrong_credential(provider):
    provider.configure(key=ROUTER_KEY)
    previous = provider.manifest()
    provider.configure(provider='openai')
    assert provider.model=='gpt-6.1-sol' and not provider.key
    assert provider.manifest()!=previous
    with pytest.raises(ValueError,match='selected provider'):
        provider.configure(provider='openai',key=ROUTER_KEY)
    assert not provider.key
    with pytest.raises(ValueError,match='native model'):
        provider.configure(provider='openai',key=OPENAI_KEY,model='openai/gpt-6.1-sol')
    assert not provider.key, 'Invalid configuration must not partially change credentials'


@pytest.mark.parametrize('refusal,finish',[('I cannot comply','stop'),(None,'length')])
def test_refused_or_truncated_outputs_are_not_cached(provider,monkeypatch,refusal,finish):
    provider.configure(key=OPENAI_KEY)
    mock_sdk(monkeypatch,lambda request:completion(request,refusal=refusal,finish=finish))
    with pytest.raises(ProviderError,match='refused or incomplete'):
        provider.call('evidence','Return ok',{},SCHEMA)
    with provider.store.connect() as connection:
        assert connection.execute('SELECT COUNT(*) FROM llm_cache').fetchone()[0]==0
        assert connection.execute('SELECT status FROM llm_calls').fetchone()[0]=='error'


def test_sdk_error_is_sanitized_and_not_retried(provider,monkeypatch):
    provider.configure(key=OPENAI_KEY)
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx2.Response(401,json={'error':{'message':'SECRET SERVER BODY '+OPENAI_KEY,'type':'authentication_error'}})
    mock_sdk(monkeypatch,handler)
    with pytest.raises(ProviderError) as exc:
        provider.check()
    assert exc.value.code=='authentication' and 'SECRET' not in str(exc.value) and OPENAI_KEY not in str(exc.value)
    assert len(calls)==1 and not provider.checked


def test_connection_check_and_model_list_use_official_sdk(provider,monkeypatch):
    provider.configure(key=OPENAI_KEY)
    def handler(request):
        if request.url.path.endswith('/models'):
            return httpx2.Response(200,json={'object':'list','data':[
                {'id':'gpt-6.1-sol','object':'model','created':1,'owned_by':'openai'},
                {'id':'text-embedding-3-small','object':'model','created':1,'owned_by':'openai'}]})
        return completion(request)
    mock_sdk(monkeypatch,handler)
    assert [m['id'] for m in provider.models()]==['gpt-6.1-sol']
    assert provider.check()['checked'] is True


def test_api_provider_switch_does_not_return_credentials(provider,tmp_path):
    from fastapi.testclient import TestClient
    from refundops.main import create_app
    with TestClient(create_app(tmp_path/'provider-api.sqlite3',seed=False,auto_analyze=False),
                    headers={'X-Demo-Role':'manager'}) as client:
        assert client.get('/api/settings/llm').json()['provider']=='openai'
        for name,key,model in [('openrouter',ROUTER_KEY,'openai/gpt-6.1-sol'),('openai',OPENAI_KEY,'gpt-6.1-sol')]:
            result=client.put('/api/settings/llm',json={'provider':name,'key':key,'model':model,'enabled':True})
            assert result.status_code==200
            assert result.json()['provider']==name and result.json()['configured']
            assert key not in result.text
        assert client.put('/api/settings/llm',json={'provider':'unknown'}).status_code==422
        assert client.delete('/api/settings/llm').json()['configured'] is False
