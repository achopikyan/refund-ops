"""Prepare or apply a source-only workspace, preserving a backup before replacement."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def apply_stage(staged,target):
    target=target.resolve(); root=ROOT.resolve()
    if not target.is_relative_to(root/'var') or target==staged.resolve():
        raise ValueError('Reset target must be an operational database inside this workspace var directory.')
    # Only this known local app instance is relevant, not unrelated Windows processes.
    ports={18474}
    try:ports.update(json.loads((ROOT/'var/launcher-state.json').read_text()).values())
    except (OSError,ValueError):pass
    for port in ports:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health',timeout=.5) as response:health=json.load(response)
        except (OSError,ValueError):continue
        import hashlib
        if health.get('workspace_id')==hashlib.sha256(str(target).encode()).hexdigest()[:16]:
            raise ValueError('Stop this workspace server before applying the prepared reset; no database was replaced.')
    timestamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    backup=ROOT/'var/backups'/('before-source-rebuild-'+timestamp+'.sqlite3')
    backup.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        with sqlite3.connect(target) as source,sqlite3.connect(backup) as dest:source.backup(dest)
    with sqlite3.connect(staged) as source,sqlite3.connect(target) as dest:source.backup(dest)
    with sqlite3.connect(target) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM ledger').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM policies').fetchone()[0] in (2,3)
    return str(backup) if backup.exists() else None



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--staged', type=Path, help='Use an existing prepared database under var')
    args = parser.parse_args()
    if args.staged:
        staged = args.staged.resolve()
        if not staged.is_relative_to(ROOT / 'var') or not staged.is_file():
            raise ValueError('Choose a prepared database under var.')
    else:
        from dotenv import load_dotenv
        from prepare_clean_workspace import prepare
        load_dotenv(ROOT / '.env')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
        staged = ROOT / 'var' / ('source-rebuild-' + stamp + '.sqlite3')
        result = prepare(ROOT / 'var/refundops.sqlite3', staged)
        print(json.dumps(result, indent=2))
    if args.apply:
        backup = apply_stage(staged, ROOT / 'var/refundops.sqlite3')
        print(json.dumps({'applied': str(ROOT / 'var/refundops.sqlite3'), 'backup': backup}, indent=2))


if __name__ == '__main__':
    main()
