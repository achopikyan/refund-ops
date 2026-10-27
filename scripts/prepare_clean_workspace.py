"""Prepare the source-only demo without modifying a running database.

Keeps valid, completed model extraction; discards decisions, payments and checks.
START applies the verified stage after stopping the old server and taking a backup.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from dotenv import load_dotenv
from refundops.source_rebuild import (
    load_sources, infer_legacy, build_policies, broader_candidate,
    populate,
)
from refundops.storage import Store
from refundops.providers import AIProvider
from refundops.analysis_pipeline import EvidencePipeline


def prepare(source_path, staged):
    if staged.exists():
        raise ValueError('Choose a new stage path; existing databases are never overwritten.')
    sources = load_sources(ROOT / 'data')
    inferred = infer_legacy(sources['history']['rows'])
    v1, v2 = build_policies(inferred)
    report = {'rule_provenance': [], 'legacy_reconstruction': inferred}
    store = Store(staged)
    populate(store, sources, v1, v2, report, v3=broader_candidate(v2), current_version=1)
    store.seed(ROOT / 'data')
    pipeline = EvidencePipeline(store, AIProvider(store))
    copied = 0
    if source_path.exists():
        with sqlite3.connect(source_path) as source, store.tx() as target:
            source.row_factory = sqlite3.Row
            old_ids = {r['id']: r['external_id'] for r in source.execute('SELECT id,external_id FROM requests')}
            new_ids = {r['external_id']: r['id'] for r in target.execute('SELECT id,external_id FROM requests')}
            for table in ('llm_cache', 'llm_calls'):
                for row in source.execute('SELECT * FROM ' + table):
                    target.execute('INSERT OR IGNORE INTO ' + table + ' VALUES(' + ','.join('?' for _ in row) + ')', tuple(row))
            if source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo_llm_calls'").fetchone():
                target.execute('CREATE TABLE IF NOT EXISTS demo_llm_calls AS SELECT * FROM llm_calls WHERE 0')
                for row in source.execute('SELECT * FROM demo_llm_calls'):
                    target.execute('INSERT INTO demo_llm_calls VALUES(' + ','.join('?' for _ in row) + ')', tuple(row))
            for row in source.execute("SELECT * FROM request_analysis WHERE status='completed'"):
                values = list(row)
                if not values[0].startswith('history:'):
                    values[0] = new_ids.get(old_ids.get(values[0]))
                    if values[0] is None:
                        continue
                target.execute('INSERT OR IGNORE INTO request_analysis VALUES(?,?,?,?,?,?,?,?)', values)
                copied += 1
        for obj in store.requests():
            saved = pipeline.status(obj)
            if saved['status'] == 'completed':
                store.update_evidence(obj['id'], saved['evidence'], obj['version'])
    store.refresh_evaluations()
    with store.connect() as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        for table in ('decisions', 'ledger', 'outcomes', 'experiments', 'observations'):
            assert db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] == 0
    requests = store.requests()
    expected = {r['request_id'] for r in sources['pending']['rows']}
    assert {r['external_id'] for r in requests} == expected and len(requests) == 20
    assert store.request('RF-2183')['conflict']
    return {
        'staged_database': str(staged.resolve()),
        'sha256': hashlib.sha256(staged.read_bytes()).hexdigest(),
        'requests': len(requests), 'current_version': 1, 'draft_versions': [2, 3],
        'completed_pending_analysis': sum(pipeline.status(r)['status'] == 'completed' for r in requests),
        'history_analysis': pipeline.history.summary(),
        'copied_analysis_records': copied,
    }


def bundle(staged, result):
    """Export a clean template; historical model costs are provenance, not new spend."""
    if result['completed_pending_analysis'] != 20 or result['history_analysis']['completed'] != 248:
        raise ValueError('A bundled demo requires saved live analysis for all 268 source requests.')
    target = ROOT / 'data/demo/refundops.sqlite3'
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(staged) as source, sqlite3.connect(target) as dest:
        source.backup(dest)
        # Keep the measured run inspectable without charging its historical calls
        # against a reviewer's new local reported-cost threshold.
        dest.execute('CREATE TABLE IF NOT EXISTS demo_llm_calls AS SELECT * FROM llm_calls WHERE 0')
        dest.execute('INSERT INTO demo_llm_calls SELECT * FROM llm_calls WHERE id NOT IN (SELECT id FROM demo_llm_calls)')
        dest.execute('DELETE FROM llm_calls')
        metadata = {
            'description': 'Saved live analysis of the supplied source data. No operational decisions are preloaded.',
            'provider': result['history_analysis']['manifest'].get('provider', 'openrouter'),
            'model_manifest': result['history_analysis']['manifest'],
            'pending': 20, 'history': 248,
            'recorded_calls_table': 'demo_llm_calls',
        }
        dest.execute("INSERT OR REPLACE INTO state VALUES('demo_provenance',?)", (json.dumps(metadata),))
        dest.commit()
        dest.execute('VACUUM')
    return str(target)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', action='store_true', help='Also export the clean, analysed demo database for the repository')
    args = parser.parse_args()
    load_dotenv(ROOT / '.env')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    result = prepare(ROOT / 'var/refundops.sqlite3', ROOT / 'var' / f'clean-source-{stamp}.sqlite3')
    if args.bundle:
        result['bundled_database'] = bundle(Path(result['staged_database']), result)
    (ROOT / 'var/source-rebuild-request.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
