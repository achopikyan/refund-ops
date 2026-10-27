"""Runtime identity shared by the one-command launcher and server health endpoint."""
import hashlib
from pathlib import Path


def code_revision():
    digest=hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob('*.py')):
        digest.update(path.name.encode());digest.update(path.read_bytes())
    return digest.hexdigest()[:20]
