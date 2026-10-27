"""Saved real extraction retains its original identity; it is never a fake provider."""
import json
import pytest

from refundops.analysis_pipeline import EvidencePipeline
from refundops.domain import FACTS
from refundops.providers import AIProvider
from conftest import csv_text, raw


@pytest.fixture
def recorded(one, monkeypatch):
    for name in ('AI_PROVIDER','OPENAI_API_KEY','OPENROUTER_API_KEY','OPENAI_MODEL','OPENROUTER_MODEL'):
        monkeypatch.setenv(name, '')
    store, obj = one
    original = AIProvider(store)
    original.configure(provider='openrouter',key='sk-or-recorded-fixture-not-real',model='openai/gpt-6.1-sol')
    def response(*args, **kwargs):
        value={'facts':[],'summary':'Authored response used to exercise persistence.', 'assessed_facts':sorted(FACTS)}
        kwargs['validator'](value)
        return value
    monkeypatch.setattr(original,'call',response)
    pipeline=EvidencePipeline(store,original)
    pipeline.process(obj,[])
    batch=store.import_preview(csv_text(raw(request_id='H-SAVED')), 'history.csv', 'history')
    store.import_commit(batch['id'])
    pipeline.history.process(pipeline.history.records()[0],[])
    provenance={'provider':'openrouter','model_manifest':original.manifest()}
    with store.tx() as c:
        c.execute("INSERT INTO state VALUES('demo_provenance',?)",(json.dumps(provenance),))
    saved=AIProvider(store)
    monkeypatch.setattr(saved,'sdk',lambda **_:pytest.fail('Saved analysis cannot call a provider'))
    return store,obj,saved,provenance


def test_clean_openai_default_uses_exact_saved_router_evidence_without_key(recorded):
    store,obj,model,provenance=recorded
    status=model.status()
    assert status['provider']=='openai' and status['model']=='gpt-6.1-sol'
    assert not status['configured'] and status['analysis_mode']=='saved_demo'
    assert status['saved_analysis_provider']=='openrouter'
    assert status['saved_analysis_model']=='openai/gpt-6.1-sol'
    assert model.manifest()==provenance['model_manifest']
    pipeline=EvidencePipeline(store,model)
    store.runtime_manifest=lambda:{'ai':model.manifest()}
    store.runtime_analysis_ready=pipeline.execution_ready
    assert pipeline.status(store.request(obj['id']))['status']=='completed'
    assert pipeline.history.summary()['completed']==1
    pipeline.run_once()
    assert store.request(obj['id'])['decision'] is not None
    assert store.metrics()['ai']['calls']==0


def test_new_or_edited_inputs_have_no_saved_analysis(recorded):
    store,obj,model,_=recorded
    obj=store.request(obj['id'])
    changed=store.correct(obj['id'],obj['version'],{'support_note':'New source detail'},'Verified edit','Reviewer')
    batch=store.import_preview(csv_text(raw(request_id='NEW-SAVED')), 'new.csv', 'pending')
    store.import_commit(batch['id'])
    pipeline=EvidencePipeline(store,model)
    store.runtime_analysis_ready=pipeline.execution_ready
    pipeline.run_once()
    for request_id in (changed['id'],'NEW-SAVED'):
        current=store.request(request_id)
        assert pipeline.status(current)['status']=='unavailable'
        assert not current['decision'] and not current['evidence']['complete']


@pytest.mark.parametrize('field',['implementation','prompt_version','schema','fact_definitions'])
def test_saved_demo_rejects_changed_extraction_identity(recorded,field):
    store,_,model,provenance=recorded
    provenance['model_manifest'][field]='stale'
    with store.tx() as c:
        c.execute("UPDATE state SET value=? WHERE key='demo_provenance'",(json.dumps(provenance),))
    model = AIProvider(store)
    assert model.status()['analysis_mode']=='unavailable'
    assert model.manifest()!=provenance['model_manifest']


def test_explicit_provider_configuration_ends_saved_demo_mode(recorded):
    _,_,model,_=recorded
    model.configure(provider='openai',model='gpt-6.1-sol')
    assert model.status()['analysis_mode']=='unavailable'
    model.configure(key='sk-proj-new-provider-fixture-key',provider='openai')
    assert model.status()['analysis_mode']=='live'
    assert model.manifest()['provider']=='openai'
    model.disconnect()
    assert model.status()['analysis_mode']=='unavailable'


def test_saved_manifest_does_not_open_connections_inside_exclusive_transaction(recorded,monkeypatch):
    store,_,model,provenance=recorded
    with store.connect() as connection:
        connection.execute('BEGIN EXCLUSIVE')
        monkeypatch.setattr(store,'connect',lambda:pytest.fail('Manifest must not open a nested connection'))
        assert model.manifest()==provenance['model_manifest']
        assert model.status()['analysis_mode']=='saved_demo'
        connection.rollback()
