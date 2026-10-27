"""Copy the bundled, source-only demo into a new local workspace once."""
import hashlib
import json
from pathlib import Path
import sqlite3


def install_demo_snapshot(target, data_dir):
    target, data_dir = Path(target), Path(data_dir)
    template = data_dir / 'demo' / 'refundops.sqlite3'
    if target.exists() or not template.is_file():
        return False
    with sqlite3.connect(template.as_uri() + '?mode=ro', uri=True) as source:
        if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('The bundled demo database failed its integrity check.')
        row = source.execute("SELECT value FROM state WHERE key='source_rebuild'").fetchone()
        if not row:
            raise ValueError('The bundled demo has no source provenance.')
        hashes = json.loads(row[0])['hashes']
        # A changed supplied CSV must be imported as it is, never hidden by the demo.
        for name, expected in hashes.items():
            path = data_dir / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                return False
        for table in ('decisions', 'ledger', 'outcomes', 'experiments', 'observations'):
            if source.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]:
                raise ValueError('The bundled demo must not contain operational decisions or checks.')
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(target) as destination:
            source.backup(destination)
    return True
