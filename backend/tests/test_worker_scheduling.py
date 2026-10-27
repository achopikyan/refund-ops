"""Background scheduling must stay responsive without idle full-queue polling."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

from refundops.analysis_pipeline import EvidencePipeline
from refundops.domain import pending_evidence
from conftest import csv_text, raw


class Extractor:
    key = 'fixture-only'
    model = 'fixture/model'

    def __init__(self):
        self.calls = 0

    def manifest(self):
        return {'model': self.model}

    def extract(self, data, criteria):
        self.calls += 1
        return {**pending_evidence(data), 'method': 'live', 'complete': True,
                'issues': []}


def scheduled(store, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr('refundops.analysis_pipeline.time.monotonic', lambda: clock[0])
    monkeypatch.setattr('refundops.analysis_pipeline.time.time', lambda: clock[0])
    return EvidencePipeline(store, Extractor()), clock


def test_idle_ticks_skip_queue_scans_but_heartbeat_rechecks_execution(one, monkeypatch):
    store, _ = one
    pipeline, clock = scheduled(store, monkeypatch)
    scans = Mock(wraps=store.requests)
    execute = Mock(wraps=store.apply_automation)
    monkeypatch.setattr(store, 'requests', scans)
    monkeypatch.setattr(store, 'apply_automation', execute)
    assert pipeline.background_cycle() == 30
    first_scans = scans.call_count
    assert first_scans > 0 and execute.call_count == 1
    for second in range(2, 30, 2):
        clock[0] = 1000 + second
        pipeline.background_cycle()
    assert scans.call_count == first_scans
    assert execute.call_count == 1
    clock[0] = 1030
    pipeline.background_cycle()
    assert scans.call_count > first_scans
    # Unchanged requests are reconsidered after time-based budget/retry boundaries.
    assert execute.call_count == 2 and pipeline.llm.calls == 1


def test_notify_rechecks_edited_input_immediately_and_wakes_history(one, monkeypatch):
    store, obj = one
    obj = store.correct(obj['id'], obj['version'], {'tenure_months':'0'}, 'New customer fixture', 'Reviewer')
    pipeline, clock = scheduled(store, monkeypatch)
    pipeline.background_cycle()
    fresh = store.request(obj['id'])
    store.correct(fresh['id'], fresh['version'], {'support_note': 'Updated source note'}, 'Verified', 'Reviewer')
    clock[0] += 1
    pipeline.notify()
    assert pipeline.history.wake_event.is_set()
    pipeline.background_cycle()
    assert pipeline.llm.calls == 2
    assert pipeline.status(store.request(obj['id']))['status'] == 'completed'


def test_worker_never_creates_or_runs_a_model_exam(one, monkeypatch):
    store, _ = one
    pipeline, clock = scheduled(store, monkeypatch)
    assert not hasattr(pipeline.llm, 'acceptance')
    assert pipeline.background_cycle() == 30
    clock[0] += 2
    assert pipeline.background_cycle() == 28
    assert pipeline.llm.calls == 1


def test_provider_retry_deadline_is_revisited_within_heartbeat(one, monkeypatch):
    from refundops.llm import ProviderError
    store, _ = one
    pipeline, clock = scheduled(store, monkeypatch)
    pipeline.llm.extract = Mock(side_effect=ProviderError('fixture failure', 'rate_limit'))
    pipeline.background_cycle()
    assert pipeline.llm.extract.call_count == 1
    clock[0] += 30
    pipeline.background_cycle()
    assert pipeline.llm.extract.call_count == 1
    clock[0] += 30
    pipeline.background_cycle()
    assert pipeline.llm.extract.call_count == 2


def test_history_completion_wakes_current_but_cached_pass_stays_quiet(store, monkeypatch):
    batch = store.import_preview(csv_text(raw(request_id='H-SCHEDULE')), 'history.csv', 'history')
    store.import_commit(batch['id'])
    pipeline, _ = scheduled(store, monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pipeline.history.run_once(pool)
        assert pipeline.wake_event.is_set() and pipeline.llm.calls == 1
        pipeline.wake_event.clear()
        pipeline.history.run_once(pool)
        assert not pipeline.wake_event.is_set() and pipeline.llm.calls == 1


def test_history_idle_wait_is_bounded_and_interruptible(store, monkeypatch):
    pipeline, _ = scheduled(store, monkeypatch)
    waits = []
    run = Mock()
    monkeypatch.setattr(pipeline.history, 'run_once', run)

    def wait(timeout):
        waits.append(timeout)
        pipeline.stop_event.set()

    monkeypatch.setattr(pipeline.history.wake_event, 'wait', wait)
    pipeline.history.start()
    pipeline.history.thread.join(timeout=2)
    assert not pipeline.history.thread.is_alive()
    assert run.call_count == 1 and waits == [30]
