"""Explicit model responses for isolated browser regressions, never production imports.

This fixture tests workflow mechanics, not extraction accuracy. It has no network
calls and its fixture endpoint exists only in the separately launched test server.
"""
import os
from pathlib import Path

from refundops.domain import FACTS, fingerprint, validate_evidence


def create_browser_app():
    target = Path(os.environ.get('REFUNDOPS_DB','')).resolve()
    expected_parent = (Path(__file__).resolve().parents[2]/'var').resolve()
    if target.parent != expected_parent or not target.name.startswith(('shared-shadow-e2e-','release-e2e-')):
        raise ValueError('Browser fixtures require a dedicated regression database, never the operational workspace.')
    from refundops.main import create_app
    app = create_app(auto_analyze=False)
    store, llm, pipeline = app.state.store, app.state.llm, app.state.evidence_pipeline
    llm.configure(provider='openai',key='sk-proj-browser-fixture-not-real',model='gpt-6.1-sol')
    store.runtime_analysis_ready = pipeline.execution_ready
    store.history_evidence = pipeline.history

    def extract(data, criteria):
        facts = []
        if data['request_id'] == 'OVERLAP-E2E':
            facts.append({'name':'fraud_confirmed','value':'yes','source':'support_note',
                          'quote':'Fraud team confirmed the card was stolen.','context_fields':[]})
        response = {'facts':facts,'summary':'Explicit model-response fixture for browser regression.',
                    'assessed_facts':sorted(FACTS)}
        evidence = validate_evidence(data,response,'live',criteria)
        evidence.update(model_manifest=fingerprint(llm.manifest()),criteria_hash=fingerprint(criteria))
        return evidence

    llm.extract = extract

    def analyze():
        for data in pipeline.history.records():
            pipeline.history.process(data,[])
        for obj in store.requests():
            pipeline.process(obj,[])
        return {'fixture':True,'requests':len(store.requests())}

    app.post('/__fixtures__/analyze')(analyze)
    analyze()
    return app
