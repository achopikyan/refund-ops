"""The committed template is copied once; local work is never overwritten."""
import hashlib
import json
import sqlite3
from pathlib import Path

from refundops.bootstrap import install_demo_snapshot

ROOT = Path(__file__).resolve().parents[2]


def test_bundled_demo_contains_only_source_work_and_recorded_live_evidence(tmp_path):
    target = tmp_path / 'local.sqlite3'
    template = ROOT / 'data/demo/refundops.sqlite3'
    before = hashlib.sha256(template.read_bytes()).hexdigest()
    assert install_demo_snapshot(target, ROOT / 'data')
    with sqlite3.connect(target) as db:
        assert db.execute('SELECT COUNT(*) FROM requests').fetchone()[0] == 20
        assert db.execute('SELECT COUNT(*) FROM history').fetchone()[0] == 248
        assert db.execute("SELECT COUNT(*) FROM requests WHERE json_extract(evidence,'$.method')='live' AND json_extract(evidence,'$.complete')=1").fetchone()[0] == 20
        assert db.execute('SELECT rowid FROM policies WHERE status="active"').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM policies WHERE status="draft"').fetchone()[0] == 2
        for table in ('decisions', 'ledger', 'outcomes', 'experiments', 'observations', 'llm_calls'):
            assert db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] == 0
        provenance = json.loads(db.execute("SELECT value FROM state WHERE key='demo_provenance'").fetchone()[0])
        assert (provenance['pending'], provenance['history']) == (20, 248)
        db.execute("INSERT OR REPLACE INTO state VALUES('local_work','keep')")
    assert not install_demo_snapshot(target, ROOT / 'data')
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT value FROM state WHERE key='local_work'").fetchone()[0] == 'keep'
    assert hashlib.sha256(template.read_bytes()).hexdigest() == before


def test_changed_sources_do_not_get_replaced_by_demo(tmp_path):
    data = tmp_path / 'data'
    (data / 'demo').mkdir(parents=True)
    (data / 'demo/refundops.sqlite3').write_bytes((ROOT / 'data/demo/refundops.sqlite3').read_bytes())
    (data / 'pending.csv').write_text('a changed input', encoding='utf-8')
    target = tmp_path / 'local.sqlite3'
    assert not install_demo_snapshot(target, data)
    assert not target.exists()


def test_bundled_live_cache_matches_current_extractor_without_network(tmp_path, monkeypatch):
    from refundops.storage import Store
    from refundops.providers import AIProvider
    from refundops.analysis_pipeline import EvidencePipeline
    monkeypatch.setenv('AI_PROVIDER', 'openrouter')
    monkeypatch.setenv('OPENROUTER_MODEL', 'openai/gpt-6.1-sol')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'sk-or-fixture-only-not-a-real-key')
    target = tmp_path / 'cached.sqlite3'
    assert install_demo_snapshot(target, ROOT / 'data')
    store = Store(target)
    model = AIProvider(store)
    def no_network(*args, **kwargs):
        raise AssertionError('The bundled source analysis must not make a provider call')
    monkeypatch.setattr(model, 'sdk', no_network)
    pipeline = EvidencePipeline(store, model)
    assert pipeline.history.summary()['completed'] == 248
    assert all(pipeline.status(r)['status'] == 'completed' for r in store.requests())


def test_fresh_no_key_demo_keeps_openai_selection_and_runs_saved_shadow(tmp_path,monkeypatch):
    from refundops.main import create_app
    for name in ('AI_PROVIDER','OPENAI_API_KEY','OPENROUTER_API_KEY','OPENAI_MODEL','OPENROUTER_MODEL'):
        monkeypatch.setenv(name,'')
    target=tmp_path/'no-key-demo.sqlite3'
    assert install_demo_snapshot(target, ROOT/'data')
    app=create_app(target,auto_analyze=True)
    store,model,pipeline=app.state.store,app.state.llm,app.state.evidence_pipeline
    def unexpected_call(*args,**kwargs):
        raise AssertionError('Unchanged demo records must not invoke a provider')
    monkeypatch.setattr(model,'sdk',unexpected_call)
    monkeypatch.setattr(model,'extract',unexpected_call)
    assert model.status()['provider']=='openai'
    assert model.status()['analysis_mode']=='saved_demo'
    assert pipeline.history.summary()['completed']==248
    pipeline.run_once()
    paid={r['external_id'] for r in store.requests() if r['decision']}
    assert paid=={'RF-1069','RF-1074','RF-1075','RF-2196','RF-2198','RF-2200'}
    assert store.metrics()['ai']['calls']==0
    candidate=next(p for p in store.policies() if p['version']==2)
    experiment=store.create_experiment(candidate['data'],policy_id=candidate['id'])
    pipeline.history.request_replay(experiment['id'])
    assert store.experiment(experiment['id'])['status']=='backtested'
    store.start_experiment(experiment['id'])
    assert store.experiment(experiment['id'])['status']=='shadow'
    assert model.status()['saved_analysis_provider']=='openrouter'
    store.runtime_analysis_ready = pipeline.execution_ready
    store.runtime_manifest = lambda: {'ai': model.manifest()}
    pipeline.run_once()
    assert len(store.requests()) == 20
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM llm_calls').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM ledger').fetchone()[0] == 6
    pipeline.run_once()
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM ledger').fetchone()[0] == 6
