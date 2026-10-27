from copy import deepcopy
from refundops.analysis_pipeline import EvidencePipeline
from refundops.domain import fingerprint, pending_evidence
from refundops.policy_management import compare_backtest
from conftest import raw,csv_text,small_policy


class Extractor:
    key='test-key-not-a-provider-credential'
    model='fixture/model'
    def __init__(self):self.calls=[];self.revision=1
    def manifest(self):return {'model':self.model,'revision':self.revision}
    def extract(self,data,criteria):
        assert not {'decision','decided_by','decided_at','review_minutes','outcome_note'} & data.keys()
        self.calls.append((deepcopy(data),deepcopy(criteria)))
        return {**pending_evidence(data),'method':'live','complete':True,'issues':[],
                'model_manifest':fingerprint(self.manifest()),'criteria_hash':fingerprint(criteria)}


def setup(store):
    batch=store.import_preview(csv_text(raw(request_id='H1',decision='rejected',outcome_note='FUTURE SECRET',review_minutes='17')),'history.csv','history')
    store.import_commit(batch['id'])
    llm=Extractor();pipeline=EvidencePipeline(store,llm);store.history_evidence=pipeline.history
    return llm,pipeline,pipeline.history.records()[0]


def test_saved_extraction_survives_restart_without_calls_and_labels_do_not_leak(store):
    llm,p,data=setup(store)
    p.history.process(data,[])
    assert len(llm.calls)==1
    assert p.history.summary()['ready']
    restarted=EvidencePipeline(store,llm)
    restarted.history.process(data,[])
    assert len(llm.calls)==1
    assert restarted.history.evidence(data,[])['method']=='live'
    data['outcome_note']='CHANGED FUTURE'
    restarted.history.process(data,[])
    assert len(llm.calls)==1
    assert not store.requests()  # history is never imported into the review queue


def test_changed_input_question_or_manifest_requires_new_evidence(store):
    llm,p,data=setup(store);p.history.process(data,[])
    changed={**data,'customer_note':'The parcel arrived late'}
    p.history.process(changed,[])
    p.history.process(changed,[{'id':'x','question':'Did it arrive?','sources':['customer_note']}])
    llm.revision=2;p.history.process(changed,[])
    assert len(llm.calls)==4
    assert len({x[1][0]['id'] if x[1] else 'base' for x in llm.calls})==2


def test_queued_replay_waits_then_persists_full_live_results(store):
    llm,p,data=setup(store)
    candidate=store.save_draft(small_policy(store.policy()['data'],7500))
    ex=store.create_experiment(candidate['data'],policy_id=candidate['id'])
    pending=p.history.request_replay(ex['id'])
    assert pending['preparing']
    assert store.experiment(ex['id'])['backtest'] is None
    assert compare_backtest(store,[candidate['id']])['preparing']
    p.history.process(data,[]);p.history.finish_replays()
    saved=store.experiment(ex['id'])['backtest']
    assert saved['decision_report']['quality']['complete_evidence']==1
    assert saved['decision_report']['metadata']['evidence_mode']=='Full live extraction'
    comparison=compare_backtest(store,[candidate['id']])
    assert comparison['analysis']['ready']
    assert comparison['versions'][0]['decision_report']['quality']['complete_evidence']==1
    assert 'FUTURE SECRET' not in str(comparison['requests'][0]['candidates'])


def test_incomplete_response_never_becomes_completed(store):
    llm,p,data=setup(store)
    llm.extract=lambda *_:{'complete':False}
    p.history.process(data,[])
    s=p.history.summary()
    assert not s['ready'] and s['failed']==1
