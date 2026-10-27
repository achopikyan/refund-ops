"""Persistent historical extraction, isolated from outcomes and the live request queue."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
from .domain import fingerprint
from .analysis_errors import public_failure, PROVIDER_WIDE


class HistoricalEvidence:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.store, self.llm = pipeline.store, pipeline.llm
        self.thread = None
        self.wake_event = threading.Event()
        with self.store.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS historical_replays(experiment_id TEXT PRIMARY KEY,status TEXT NOT NULL,error TEXT NOT NULL DEFAULT \'\')')

    def records(self):
        with self.store.connect() as c:
            return [json.loads(r[0]) for r in c.execute('SELECT data FROM history ORDER BY id')]

    @staticmethod
    def obj(data):
        from .experiments import request_input
        return {'id':'history:'+data['request_id'], 'data':request_input(data)}

    def questions(self):
        with self.store.connect() as c:
            policies=[json.loads(r[0]) for r in c.execute('SELECT data FROM policies')]
        distinct={fingerprint(p['criteria']):p['criteria'] for p in policies}
        return list(distinct.values()) or [[]]

    def summary(self, questions=None, records=None):
        rows=self.records() if records is None else records
        questions=self.questions() if questions is None else questions
        questions=list({fingerprint(q):q for q in questions}.values())
        counts=dict.fromkeys(('completed','running','pending','failed','blocked','unavailable'),0)
        failures=[]; complete_records=0
        with self.store.connect() as c:
            cached={(r['request_id'],r['input_key']):r for r in c.execute("SELECT * FROM request_analysis WHERE request_id LIKE 'history:%'")}
        for data in rows:
            done=True
            for criteria in questions:
                obj=self.obj(data); key=self.pipeline.key(obj,criteria)
                saved=cached.get((obj['id'],key))
                status=saved['status'] if saved else 'pending' if self.llm.key else 'unavailable'
                if status=='completed' and not json.loads(saved['evidence'] or '{}').get('complete'): status='failed'
                counts[status]+=1
                done=done and status=='completed'
                if status=='failed':
                    failure=self.pipeline.failure(saved['error'])
                    failures.append({'id':data['request_id'],'message':failure['message'],'code':failure['code'],
                                     'attempts':saved['attempts'],'retry_at':saved['retry_at']})
            complete_records+=bool(done)
        return {'total':sum(counts.values()),'requests':len(rows),'complete_requests':complete_records,'question_sets':len(questions),
                **counts,'ready':complete_records==len(rows),'model':self.llm.manifest()['model'],'manifest':self.llm.manifest(),
                'failures':failures,'provider_issue':self.pipeline.provider_issue}

    def evidence(self, data, criteria, c=None):
        if c is None:
            with self.store.connect() as db:return self.evidence(data,criteria,db)
        obj=self.obj(data);key=self.pipeline.key(obj,criteria)
        saved=c.execute("SELECT evidence FROM request_analysis WHERE request_id=? AND input_key=? AND status='completed'",(obj['id'],key)).fetchone()
        if not saved:
            from .storage import Conflict
            raise Conflict('Historical evidence is still being prepared. Progress is saved automatically; wait for all requests to complete.')
        evidence=json.loads(saved[0])
        if not evidence.get('complete'):
            from .storage import Conflict
            raise Conflict('Historical extraction needs attention before replay.')
        return evidence

    def process(self, data, criteria):
        p=self.pipeline
        if p.stop_event.is_set() or not self.llm.key:return
        if p.provider_issue and p.provider_issue['retry_at']>time.time():return
        obj=self.obj(data);key=p.key(obj,criteria)
        with self.store.connect() as c:
            saved=c.execute('SELECT * FROM request_analysis WHERE request_id=? AND input_key=?',(obj['id'],key)).fetchone()
        if saved and saved['status']=='completed':return
        if saved and (saved['retry_at']>time.time() or saved['attempts']>=3 and p.failure(saved['error'])['code'] not in PROVIDER_WIDE):return
        attempts=(saved['attempts'] if saved else 0)+1
        p.save(obj['id'],key,'running',attempts=attempts)
        try:
            # Drop all post-decision fields BEFORE the adapter boundary, not merely in its prompt.
            evidence=self.llm.extract(obj['data'],criteria)
            if self.pipeline.key(obj,criteria)!=key:return
            if not evidence.get('complete'):
                from .llm import ProviderError
                raise ProviderError('Historical evidence did not pass completeness validation.','invalid_response')
            evidence['analysis_key']=key
            p.save(obj['id'],key,'completed',evidence=evidence,attempts=attempts)
            if p.provider_issue and p.provider_issue['retry_at']<=time.time():p.provider_issue=None
            return True
        except Exception as ex:
            failure=public_failure(ex); retry_at=time.time()+60*min(attempts,3)
            if failure['code'] in PROVIDER_WIDE:p.provider_issue={**failure,'retry_at':retry_at}
            p.save(obj['id'],key,'failed',error=failure,attempts=attempts,retry_at=retry_at)
            return True

    def request_replay(self,eid):
        ex=self.store.experiment(eid)
        summary=self.summary([ex['baseline']['criteria'],ex['policy']['criteria']])
        if summary['ready']:return self.store.backtest_experiment(eid)
        with self.store.connect() as c:
            c.execute("INSERT OR REPLACE INTO historical_replays VALUES(?,'pending','')",(eid,))
        self.pipeline.notify()
        return {'preparing':True,'analysis':summary}

    def finish_replays(self):
        with self.store.connect() as c:
            queued=[r[0] for r in c.execute("SELECT experiment_id FROM historical_replays WHERE status='pending'")]
        changed = False
        for eid in queued:
            ex=self.store.experiment(eid)
            if not self.summary([ex['baseline']['criteria'],ex['policy']['criteria']])['ready']:continue
            try:
                self.store.backtest_experiment(eid)
                status,error='completed',''
            except (ValueError,KeyError) as exc:status,error='failed',str(exc)
            with self.store.connect() as c:c.execute('UPDATE historical_replays SET status=?,error=? WHERE experiment_id=?',(status,error,eid))
            changed = True
        return changed

    def run_once(self, pool):
        changed = False
        for criteria in self.questions():
            # Bounded batches let shutdown and provider backoff stop scheduling promptly.
            records = self.records()
            for start in range(0, len(records), 4):
                if self.pipeline.stop_event.is_set(): return
                futures = [pool.submit(self.process, data, criteria) for data in records[start:start+4]]
                for future in futures:
                    changed = bool(future.result()) or changed
        changed = self.finish_replays() or changed
        if changed:
            # A replay or extraction completion may unlock checks used by Current.
            self.pipeline.notify_current()

    def start(self):
        def run():
            with ThreadPoolExecutor(max_workers=4,thread_name_prefix='history-evidence') as pool:
                while not self.pipeline.stop_event.is_set():
                    self.wake_event.clear()
                    self.run_once(pool)
                    self.wake_event.wait(self.pipeline.IDLE_INTERVAL)
        def resilient_run():
            import logging
            while not self.pipeline.stop_event.is_set():
                try:run()
                except Exception:
                    logging.getLogger(__name__).warning('Historical evidence cycle interrupted; saved progress will resume')
                    self.pipeline.stop_event.wait(3)
        self.thread=threading.Thread(target=resilient_run,name='historical-evidence',daemon=True)
        self.thread.start()

    def stop(self):
        if self.thread:self.thread.join(timeout=35)
