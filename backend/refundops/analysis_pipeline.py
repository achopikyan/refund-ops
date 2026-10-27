"""Persist evidence, then process Current approvals through atomic payment checks."""
import json
import logging
import threading
import time
from .domain import fingerprint
from .analysis_errors import public_failure, PROVIDER_WIDE

SCHEMA = """
CREATE TABLE IF NOT EXISTS request_analysis (
 request_id TEXT NOT NULL, input_key TEXT NOT NULL, status TEXT NOT NULL,
 evidence TEXT, error TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
 retry_at REAL NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
 PRIMARY KEY(request_id,input_key)
);
"""


class EvidencePipeline:
    IDLE_INTERVAL = 30
    ERROR_RETRY_INTERVAL = 2

    def __init__(self, store, llm):
        self.store, self.llm = store, llm
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self._wake_lock = threading.Lock()
        self.thread = None
        self.provider_issue = None
        self._next_scan_at = 0
        with store.connect() as c:
            c.executescript(SCHEMA)
            c.execute("UPDATE request_analysis SET status='pending',retry_at=0 WHERE status='running'")
        from .history_evidence import HistoricalEvidence
        self.history=HistoricalEvidence(self)

    def key(self, obj, criteria):
        # Only request-time input, not decisions, previous predictions or outcomes.
        from .llm import EVIDENCE_FIELDS
        # Identifiers affect local redaction, so changing one invalidates the result.
        # They stay in this local hash and never enter the provider payload.
        return fingerprint([{k: obj['data'].get(k) for k in (*EVIDENCE_FIELDS, 'customer_id', 'request_id')}, criteria, self.llm.manifest()])

    def execution_ready(self, c, obj, policy):
        key=self.key(obj,policy['criteria'])
        return obj['evidence'].get('analysis_key')==key and bool(c.execute(
            "SELECT 1 FROM request_analysis WHERE request_id=? AND input_key=? AND status='completed'",
            (obj['id'],key)).fetchone())

    def status(self, obj, criteria=None):
        criteria = self.store.policy()['data']['criteria'] if criteria is None else criteria
        with self.store.connect() as c:
            row = c.execute('SELECT * FROM request_analysis WHERE request_id=? AND input_key=?',
                            (obj['id'], self.key(obj, criteria))).fetchone()
        if row:
            result = {k: row[k] for k in ('status', 'error', 'updated_at', 'attempts')}
            if row['evidence'] and row['status'] == 'completed':
                result['evidence'] = json.loads(row['evidence'])
                return result
            failure = self.failure(row['error'])
            result.update(error=failure['message'], error_code=failure['code'])
            if failure.get('diagnostics'): result['diagnostics'] = failure['diagnostics']
            retrying = row['status'] == 'failed' and (row['attempts'] < 3 or failure['code'] in PROVIDER_WIDE)
            result.update(retrying=retrying, retry_at=row['retry_at'] if retrying else None)
            if self.provider_issue and row['status'] != 'running' and (row['status'] != 'failed' or failure['code'] in PROVIDER_WIDE):
                result.update(status='blocked', error=self.provider_issue['message'], error_code=self.provider_issue['code'], retrying=True, retry_at=self.provider_issue['retry_at'])
            return result
        if self.provider_issue:
            return {'status':'blocked','error':self.provider_issue['message'],'error_code':self.provider_issue['code'],
                    'retrying':True,'retry_at':self.provider_issue['retry_at'],'attempts':0}
        return {'status': 'pending' if self.llm.key else 'unavailable',
                'error': '' if self.llm.key else 'Automatic analysis is unavailable. The Refund Operations Manager can configure the AI connection.', 'attempts': 0}

    @staticmethod
    def failure(error):
        try:
            value = json.loads(error)
            if isinstance(value, dict) and 'code' in value and 'message' in value: return value
        except (ValueError, TypeError): pass
        return {'code':'unknown', 'message':error or ''}

    def save(self, rid, key, status, evidence=None, error='', attempts=0, retry_at=0):
        from .storage import now, dump
        with self.store.tx() as c:
            c.execute('INSERT OR REPLACE INTO request_analysis VALUES(?,?,?,?,?,?,?,?)',
                      (rid, key, status, dump(evidence) if evidence else None, dump(error) if isinstance(error,dict) else error, attempts, retry_at, now()))

    def process(self, obj, criteria, current=True):
        from .storage import Conflict
        obj = self.store.request(obj['id'])
        if current and self.store.policy()['data']['criteria'] != criteria: return
        key = self.key(obj, criteria)
        with self.store.connect() as c:
            row = c.execute('SELECT * FROM request_analysis WHERE request_id=? AND input_key=?', (obj['id'], key)).fetchone()
        if row and row['status'] == 'completed':
            # Reapply cached extraction after unrelated request fields change; no extra LLM call.
            evidence = json.loads(row['evidence'])
            if obj['status'] == 'resolved' or current and obj['evidence'].get('analysis_key') == key:
                return
            self.save(obj['id'],key,'completed',evidence=evidence,attempts=row['attempts'])
            if not current:
                with self.store.connect() as c:
                    if c.execute('SELECT 1 FROM candidate_evidence WHERE criteria_hash=? AND request_id=? AND request_version=?', (fingerprint(criteria), obj['id'], obj['version'])).fetchone(): return
        else:
            if self.provider_issue and self.provider_issue['retry_at'] > time.time(): return
            provider_failure = row and self.failure(row['error'])['code'] in PROVIDER_WIDE
            if not self.llm.key or row and ((row['attempts'] >= 3 and not provider_failure) or row['retry_at'] > time.time()):
                return
            attempts = (row['attempts'] if row else 0) + 1
            self.save(obj['id'], key, 'running', attempts=attempts)
            try:
                evidence = self.llm.extract(obj['data'], criteria)
            except Exception as ex:
                # Provider details/credentials never enter reviewer-facing errors.
                failure = public_failure(ex)
                retry_at = time.time() + (60 if failure['code'] in PROVIDER_WIDE else 60 * attempts)
                self.provider_issue = {**failure, 'retry_at':retry_at} if failure['code'] in PROVIDER_WIDE else None
                self.save(obj['id'], key, 'failed', error=failure, attempts=attempts, retry_at=retry_at)
                return
            if self.provider_issue:
                self.retry_failed()
            evidence['analysis_key'] = key
            self.save(obj['id'], key, 'completed', evidence=evidence, attempts=attempts)
        fresh = self.store.request(obj['id'])
        if self.key(fresh, criteria) != key:
            return  # Notes changed while the provider was processing the old input.
        try:
            if current:
                if fresh['status'] != 'resolved' and self.store.policy()['data']['criteria'] == criteria:
                    self.store.update_evidence(fresh['id'], evidence, fresh['version'])
            elif fresh['status'] != 'resolved':
                self.store.prepare_candidate({'criteria': criteria}, fresh['id'], evidence, fresh['version'])
        except Conflict:
            pass  # Next pass uses cached extraction against the latest revision.

    def candidate_criteria(self):
        """Saved drafts and fresh checks prepare evidence without starting Shadow."""
        with self.store.connect() as c:
            # A draft without any checks is editable. Once checked, its latest check
            # determines whether evidence preparation is still applicable.
            policies = [json.loads(r[0]) for r in c.execute("""SELECT data FROM policies p
                WHERE status='draft' AND NOT EXISTS
                (SELECT 1 FROM trial_sources s WHERE s.policy_id=p.id)""")]
            for row in c.execute("SELECT id FROM experiments WHERE status IN ('draft','backtested','shadow')").fetchall():
                ex = self.store.experiment(row[0], c)
                if ex['base_id'] == self.store.policy(c)['id'] and ex['manifest'] == self.store.manifest():
                    policies.append(ex['policy'])
        seen = {fingerprint(self.store.policy()['data']['criteria'])}
        result = []
        for policy in policies:
            extra = policy['criteria']
            if fingerprint(extra) in seen: continue
            seen.add(fingerprint(extra))
            result.append(extra)
        return result

    def summary(self, criteria):
        counts = dict.fromkeys(('completed','running','pending','failed','blocked','unavailable'), 0)
        for obj in self.store.requests():
            if obj['status'] == 'resolved': continue
            counts[self.status(obj, criteria)['status']] += 1
        return {'total':sum(counts.values()), **counts}

    def run_once(self):
        self.store.refresh_changed_checks()
        criteria = self.store.policy()['data']['criteria']
        extra = self.candidate_criteria()
        rows = self.store.requests()
        for obj in sorted(rows, key=lambda r: r['status'] == 'resolved'):
            if self.stop_event.is_set(): return
            self.process(obj, criteria)
            # Prepare every distinct question set for the same fresh request.
            # Results stay in the candidate cache, isolated from the reviewer.
            for questions in extra:
                if self.stop_event.is_set(): return
                self.process(obj, questions, current=False)
        if not self.stop_event.is_set():
            # Decisions re-evaluate Current and check limits inside the payment transaction.
            # Also runs for cached evidence and startup; no manual execution switch.
            with self.store.connect() as c:
                policy=self.store.policy(c)['data']
                ready=[obj['id'] for obj in self.store.requests() if self.execution_ready(c,obj,policy)]
            self.store.apply_automation(ready)

    def notify(self):
        self.notify_current()
        self.history.wake_event.set()

    def notify_current(self):
        with self._wake_lock:
            self.wake_event.set()

    def background_cycle(self):
        """Process changes promptly, with a bounded heartbeat for time-based checks."""
        with self._wake_lock:
            changed = self.wake_event.is_set()
            self.wake_event.clear()  # Notifications during work remain set for the next pass.
        now = time.monotonic()
        if changed or now >= self._next_scan_at:
            self.run_once()
            self._next_scan_at = time.monotonic() + self.IDLE_INTERVAL
        # The heartbeat also catches external writes, retry deadlines and a new UTC day.
        return max(0, self._next_scan_at - time.monotonic())

    def start(self):
        def run():
            while not self.stop_event.is_set():
                try: delay = self.background_cycle()
                except Exception:
                    logging.getLogger(__name__).warning('Automatic evidence or execution cycle interrupted; saved work will resume')
                    delay = self.ERROR_RETRY_INTERVAL
                self.wake_event.wait(delay)
        self.thread = threading.Thread(target=run, name='automatic-evidence', daemon=True)
        self.thread.start()
        self.history.start()

    def stop(self):
        self.stop_event.set()
        self.wake_event.set()
        self.history.wake_event.set()
        if self.thread: self.thread.join(timeout=35)
        self.history.stop()

    def retry_failed(self):
        self.provider_issue = None
        with self.store.tx() as c:
            c.execute("UPDATE request_analysis SET attempts=0,retry_at=0,status='pending' WHERE status='failed'")
        self.notify()
