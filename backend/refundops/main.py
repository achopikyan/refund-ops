from __future__ import annotations
import csv
import io
import json
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from.domain import Policy, evaluate
from.storage import Store, Conflict, dump, now, uid
from.llm import ProviderError
from.providers import AIProvider
from.financial import ReleaseSettings, CostAssumptions, ShadowRequirements
from.roles import permitted
from.catalog import catalog, explain, REASONS as ROUTING_REASONS
from.import policy_management
from.current_performance import current_performance
from.domain import FACTS
import hashlib

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
class Input(BaseModel):
    model_config = ConfigDict(extra = "forbid")
class Review(Input):
    version: int
    actor: str = "Alex Morgan"
    action: str
    note: str = ""
class Decision(Input):
    version: int
    actor: str = "Alex Morgan"
    action: Literal["approved", "rejected", "partial"]
    amount_cents: int | None = None
    reason: str
    idempotency_key: str = Field(min_length = 8, max_length = 200)
class Evidence(Input):
    version: int
    actor: str = "Alex Morgan"
    facts: dict[str, str] = {}
    note: str
class Outcome(Input):
    type: Literal['chargeback', 'appeal', 'audit_pass', 'audit_fail']
    note: str = Field(min_length = 1, max_length = 8000)
class Resolve(Input):
    version: int
    index: int
    note: str
    actor: str = "Alex Morgan"
class Correction(Input):
    version: int
    changes: dict[str, str]
    note: str
    actor: str = "Alex Morgan"
class Activate(Input):
    preview_id: str
    reason: str
class Settings(Input):
    key: str | None = None
    model: str | None = None
    enabled: bool | None = None
    provider: Literal['openai', 'openrouter'] | None = None
class Trial(Input):
    policy: Policy
    policy_id: str | None = None
    settings: ReleaseSettings = Field(default_factory = ReleaseSettings)
class TrialReason(Input):
    reason: str = Field(min_length = 1, max_length = 4000)
class CostUpdate(Input):
    values: CostAssumptions
    expected: CostAssumptions
class ShadowUpdate(Input):
    values: ShadowRequirements
    expected: ShadowRequirements
class Adjudication(Input):
    allowed_cents: int | None = Field(default = None, ge = 0, strict = True)
    critical: bool = False
    note: str = Field(min_length = 1, max_length = 8000)
    actor: str = Field(default = "Alex Morgan", min_length = 1, max_length = 200)
    semantic_checks: dict[str, Literal["yes", "no", "unknown"]] = Field(default_factory = dict)
    minutes: float = Field(default = 0, ge = 0, le = 120)
class Mining(Input):
    hourly_cents: int = Field(default = 3000, ge = 0, le = 1000000)
    adverse_bps: int = Field(default = 500, ge = 0, le = 10000)
    min_support: int = Field(default = 5, ge = 2, le = 1000)
    base_id: str | None = None

class CandidateSelection(Input):
    candidate_ids: list[str] = Field(min_length = 1, max_length = 30)
    policy: Policy | None = None
    target_id: str | None = None
    expected_policy: Policy | None = None

class DraftUpdate(Input):
    policy: Policy
    expected_policy: Policy

class RuleInstruction(Input):
    instruction: str = Field(min_length = 1, max_length = 4000)
    policy: Policy

def create_app(db_path = None, seed = True, auto_analyze = None):
    from.runtime import code_revision
    backend_revision = code_revision()
    database = Path(db_path or os.environ.get("REFUNDOPS_DB", str(ROOT / "var/refundops.sqlite3")))
    if seed and db_path is None and os.environ.get('REFUNDOPS_SOURCE_POLICIES') == '1' and not os.environ.get('REFUNDOPS_PENDING_CSV'):
        from.bootstrap import install_demo_snapshot
        install_demo_snapshot(database, ROOT / 'data')
    store = Store(database)
    if seed:
        if os.environ.get('REFUNDOPS_SOURCE_POLICIES') == '1' and not store.requests() and len(store.policies()) == 1 and not store.state().get('source_rebuild'):
            from.source_rebuild import load_sources, infer_legacy, build_policies, broader_candidate, populate
            sources = load_sources(ROOT / 'data')
            inferred = infer_legacy(sources['history']['rows'])
            v1, v2 = build_policies(inferred)
            report = {'legacy_reconstruction': inferred, 'rule_provenance': []}
            populate(store, sources, v1, v2, report, v3 = broader_candidate(v2),
                     current_version = 2 if os.environ.get('REFUNDOPS_PENDING_CSV') else 1)
        alternative = os.environ.get("REFUNDOPS_PENDING_CSV")
        if alternative:
            for path, kind in ((ROOT / "data/history.csv", "history"), (Path(alternative), "pending")):
                info = store.import_preview(path.read_text(encoding = "utf-8-sig"), path.name, kind)
                store.import_commit(info["id"])
        else:
            store.seed(ROOT / "data")
    store.refresh_evaluations()
    llm = AIProvider(store)
    store.runtime_manifest = lambda: {"ai": llm.manifest()}
    from.analysis_pipeline import EvidencePipeline
    pipeline = EvidencePipeline(store, llm)
    auto_analyze = os.environ.get('REFUNDOPS_AUTO_ANALYZE', '1') != '0' if auto_analyze is None else auto_analyze
    if auto_analyze:
        store.history_evidence = pipeline.history
        store.runtime_analysis_ready = pipeline.execution_ready
    @asynccontextmanager
    async def lifespan(app):
        if auto_analyze:
            pipeline.start()
        yield
        pipeline.stop()
    app = FastAPI(title = "Refund Operations", version = "1.1.0", lifespan = lifespan)
    app.state.store = store
    app.state.llm = llm
    app.state.evidence_pipeline = pipeline

    @app.middleware("http")
    async def local_origin(request, call_next):
        origin = request.headers.get("origin")
        if origin:
            try:
                parsed = urlsplit(origin)
                valid = parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost") and parsed.port is not None and not parsed.username
            except ValueError:
                valid = False
            if not valid:
                return JSONResponse({"detail": "Only the local application may access this API."}, 403)
        path = request.url.path
        if path.startswith('/api/') and path != '/api/health':
            role = request.headers.get('X-Demo-Role')
            if role not in ('reviewer', 'manager'):
                return JSONResponse(
                    {"detail": "Choose Reviewer or Refund Operations Manager to enter the demo workspace."},
                    401
                )
            if not permitted(role, request.method, path):
                return JSONResponse({"detail": "This action belongs to the other workspace."}, 403)
        response = await call_next(request)
        if path.startswith('/api/') and request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and 200 <= response.status_code < 300:
            pipeline.notify()
        return response
    @app.exception_handler(Conflict)
    async def conflict(_, ex):
        return JSONResponse({"detail": str(ex), "code": "conflict"}, 409)
    @app.exception_handler(KeyError)
    async def missing(_, ex):
        return JSONResponse({"detail": str(ex).strip("'"), "code": "not_found"}, 404)
    @app.exception_handler(ValueError)
    async def invalid(_, ex):
        if isinstance(ex, ValidationError):
            return JSONResponse(
                {
                    "detail": "Invalid data structure or values.",
                    "errors": [
                        {"loc": list(x["loc"]), "message": x["msg"]} for x in ex.errors(include_input = False)
                    ]
                },
                422
            )
        return JSONResponse({"detail": str(ex), "code": "invalid_operation"}, 422)
    @app.exception_handler(RequestValidationError)
    async def invalid_request(_, ex):
        return JSONResponse(
            {
                "detail": "Check the submitted fields and values.",
                "errors": [{"loc": list(x["loc"]), "message": x["msg"]}for x in ex.errors()]
            },
            422
        )

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "service": "refund-operations",
            "workspace_id": hashlib.sha256(str(store.path.resolve()).encode()).hexdigest()[: 16],
            "version": "1.5.0",
            "backend_revision": backend_revision,
            "process_id": os.getpid(),
            "capabilities": [
                "policy_trials",
                "risk_gates",
                "rule_discovery",
                "release_budgets",
                "policy_workspace_v2",
                "policy_composer",
                "shared_shadow",
                "reviewer_shadow_isolated",
                "automatic_evidence",
                "request_sections",
                "policy_management",
                "policy_from_scratch",
                "editable_policy_drafts",
                "single_rule_ai",
                "policy_metadata_v2",
                "manual_shadow_start",
                "explicit_rules_only",
                "automatic_candidate_evidence",
                "policy_wide_checks",
                "inline_policy_autosave",
                "staged_check_settings",
                "automatic_current",
                "policy_performance",
                "automatic_rechecks"
            ],
            "state": store.state(),
            "ai": llm.status()
        }
    @app.get("/api/requests")
    def requests(status: str | None = None, queue: str | None = None, q: str = ""):
        rows = store.requests()
        if status:
            rows = [x for x in rows if x["status"] == status]
        if queue:
            rows = [x for x in rows if x["queue"] == queue]
        if q:
            rows = [
                x for x in rows if q.lower() in dump(
                    [
                        x["external_id"],
                        x["data"]["customer_id"],
                        x["data"]["customer_note"],
                        x["data"]["support_note"]
                    ]
                ).lower()
            ]
        criteria = store.policy()['data']['criteria']
        return [{** r, 'analysis': pipeline.status(r, criteria)} for r in rows]
    @app.get("/api/requests/{rid}")
    def request(rid: str):
        obj = store.request(rid)
        return {** obj, 'analysis': pipeline.status(obj)}
    @app.get('/api/requests/{rid}/chargeback-risk')
    def chargeback_risk(rid: str):
        from.chargeback_risk import assess_store
        return assess_store(store, rid)
    @app.get('/api/requests/{rid}/policy-evaluation')
    def policy_evaluation(rid: str):
        obj = store.request(rid)
        with store.connect() as c:
            policy = store.policy(c)
            if obj['decision']:
                row = c.execute(
                    'SELECT rowid AS version,* FROM policies WHERE id=?',
                    (obj['decision']['policy_id'],)
                ).fetchone()
                if row:
                    policy = {** dict(row), 'data': json.loads(row['data'])}
        evaluation = evaluate(obj['data'], obj['evidence'], policy['data'], bool(obj['conflict']))
        if obj.get('automation_blocker'):
            evaluation = store.execution_review(evaluation, obj['automation_blocker'])
        return {'policy_id': policy['id'], 'policy_name': policy['name'], 'policy_version': policy.get('version'), 'recorded_decision': bool(obj['decision']),
                'evaluation': explain(evaluation, obj['data'], obj['evidence'])}
    @app.get("/api/requests/{rid}/audit")
    def request_audit(rid: str):
        return store.audit_list(store.request(rid)["id"])
    @app.get("/api/requests/{rid}/history")
    def customer_history(rid: str):
        return store.customer_history(rid)
    @app.post("/api/requests/{rid}/reopen")
    def reopen(rid: str, data: Review):
        return store.reopen(rid, data.version, data.note, data.action == "close")
    @app.get("/api/field-catalog")
    def field_catalog():
        return catalog(FACTS)
    @app.get("/api/reason-catalog")
    def reason_catalog():
        return ROUTING_REASONS
    @app.get('/api/rule-reasons')
    def selectable_rule_reasons():
        from.catalog import rule_reasons
        return rule_reasons()
    @app.get('/api/evidence-questions')
    def standard_evidence_questions():
        from.catalog import evidence_questions
        return evidence_questions()
    @app.get("/api/setup")
    def setup():
        return store.setup_status()
    @app.post("/api/policies/drafts")
    def save_draft(data: Policy, parent_id: str | None = None, from_scratch: bool = False):
        return store.save_draft(data.model_dump(), parent_id = parent_id, from_scratch = from_scratch)
    @app.put('/api/policies/{pid}/draft')
    def update_draft(pid: str, data: DraftUpdate):
        return store.update_draft(pid, data.policy.model_dump(), data.expected_policy.model_dump())
    @app.post('/api/policies/propose-rule')
    def propose_rule(data: RuleInstruction):
        from.rule_proposal import propose_rule
        return propose_rule(llm, data.instruction, data.policy.model_dump())
    @app.get("/api/policies/{pid}/source")
    def draft_source(pid: str):
        return store.draft_source(pid)
    @app.get('/api/shadow-policies')
    def shadow_policies():
        return store.shadow_dashboard()
    @app.post("/api/requests/{rid}/workflow")
    def workflow(rid: str, data: Review):
        return store.workflow(rid, data.version, data.action, data.actor, data.note)
    @app.post("/api/requests/{rid}/decisions")
    def decide(rid: str, data: Decision):
        return store.decide(rid, data.version, data.action, data.amount_cents, data.reason, data.actor, data.idempotency_key)
    @app.post("/api/requests/{rid}/evidence")
    def evidence(rid: str, data: Evidence):
        return store.review_evidence(rid, data.version, data.facts, data.note, data.actor)
    @app.post("/api/requests/{rid}/resolve")
    def resolve(rid: str, data: Resolve):
        return store.resolve(rid, data.version, data.index, data.note, data.actor)
    @app.post("/api/requests/{rid}/correct")
    def correct(rid: str, data: Correction):
        return store.correct(rid, data.version, data.changes, data.note, data.actor)
    @app.post("/api/requests/{rid}/outcomes")
    def outcome(rid: str, payload: Outcome):
        payload = payload.model_dump()
        obj = store.request(rid)
        if obj["status"] != "resolved":
            raise ValueError("Outcomes can be recorded after a decision.")
        if payload.get("type") not in ("chargeback", "appeal", "audit_pass", "audit_fail"):
            raise ValueError("Choose a supported outcome.")
        if not payload.get("note", "").strip():
            raise ValueError("Add an outcome note.")
        with store.tx() as c:
            c.execute("INSERT INTO outcomes VALUES(?,?,?,?,?)", (uid(), obj["id"], payload["type"], payload["note"], now()))
            store.audit(c, obj["id"], "outcome_recorded", payload, "reviewer")
            if payload["type"] == "audit_fail" and c.execute(
                "SELECT 1 FROM automation_spend WHERE decision_id=?",
                (obj["decision"]["id"],)
            ).fetchone():
                store.audit(
                    c,
                    "automation",
                    "automatic_payment_audit_failed",
                    {"request_id": obj["external_id"], "reason": payload["note"]}
                )
        return {"ok": True}
    @app.get("/api/metrics")
    def metrics():
        return store.metrics()
    @app.get("/api/audit")
    def audit():
        return store.audit_list()
    @app.get("/api/policies")
    def policies():
        return store.policies()
    @app.get("/api/trials")
    def trials():
        return store.experiments()
    @app.post("/api/trials")
    def new_trial(data: Trial):
        return store.create_experiment(
            data.policy.model_dump(),
            data.settings.model_dump(exclude_unset = True),
            data.policy_id
        )
    @app.get("/api/trials/{eid}")
    def trial_report(eid: str):
        report = store.experiment_report(eid)
        ex = report['experiment']
        with store.connect() as c:
            queued = c.execute('SELECT status,error FROM historical_replays WHERE experiment_id=?', (eid,)).fetchone()
            replacement = c.execute(
                "SELECT object_id FROM audit WHERE type='checks_restarted' AND json_extract(detail,'$.previous_checks')=? ORDER BY id DESC LIMIT 1",
                (eid,)
            ).fetchone()
        return {** report, 'analysis': pipeline.summary(ex['policy']['criteria']),
                'history_analysis': pipeline.history.summary([ex['baseline']['criteria'], ex['policy']['criteria']]),
                'replacement_checks_id': replacement[0] if replacement else None,
                'replay_job': dict(queued) if queued else None}
    @app.post("/api/trials/{eid}/backtest")
    def trial_backtest(eid: str):
        ex = store.experiment(eid)
        if auto_analyze and ex['status'] in ('draft', 'backtested', 'shadow') and (
            ex['base_id'] != store.policy()['id'] or ex['manifest'] != store.manifest()
        ):
            return store.recheck_experiment(eid, automatic = True)
        return pipeline.history.request_replay(eid) if auto_analyze else store.backtest_experiment(eid)
    @app.get('/api/history-analysis')
    def history_analysis():
        return pipeline.history.summary()
    @app.post("/api/trials/{eid}/start")
    def trial_start(eid: str):
        return store.start_experiment(eid)
    @app.put('/api/trials/{eid}/shadow-settings')
    def shadow_settings(eid: str, data: ShadowUpdate):
        return store.update_shadow_requirements(eid, data.values.model_dump(), data.expected.model_dump())
    @app.post("/api/trials/{eid}/capture")
    def trial_capture(eid: str):
        return store.capture_experiment(eid)
    @app.post('/api/trials/{eid}/recheck')
    def trial_recheck(eid: str):
        return store.recheck_experiment(eid)
    @app.post("/api/trials/{eid}/stop")
    def trial_stop(eid: str, data: TrialReason):
        return store.stop_experiment(eid, data.reason)
    @app.post("/api/trials/{eid}/promote")
    def trial_promote(eid: str, data: TrialReason):
        return store.promote_experiment(eid, data.reason)
    @app.get("/api/rule-discovery")
    def last_discovery():
        return store.latest_mining()
    @app.post("/api/rule-discovery")
    def discover_rules(data: Mining):
        return store.mine_rules(** data.model_dump())
    @app.post('/api/rule-discovery/{run_id}/draft')
    def candidates_to_draft(run_id: str, data: CandidateSelection):
        return store.draft_from_candidates(
            run_id,
            data.candidate_ids,
            data.policy.model_dump() if data.policy else None,
            data.target_id,
            data.expected_policy.model_dump() if data.expected_policy else None
        )
    @app.get("/api/release-budget")
    def release_budget():
        return store.release_budget()
    @app.get('/api/policy-versions')
    def version_library():
        return policy_management.policy_library(store)
    @app.get('/api/policy-comparisons/{mode}')
    def version_comparison(mode: Literal['backtest', 'shadow'], policy_ids: str = ''):
        selected = [pid.strip() for pid in policy_ids.split(',') if pid.strip()]
        return (
            policy_management.compare_backtest if mode == 'backtest' else policy_management.compare_shadow
        )(store, selected)
    @app.get('/api/current-performance')
    def performance():
        return current_performance(store)
    @app.get('/api/policies/{pid}/performance')
    def policy_performance(pid: str):
        return current_performance(store, pid)
    @app.post('/api/policies/{pid}/rollback-preview')
    def rollback_preview(pid: str):
        return policy_management.rollback_preview(store, pid)
    @app.post('/api/policies/{pid}/rollback')
    def rollback(pid: str, data: Activate):
        return policy_management.rollback_version(store, pid, data.preview_id, data.reason)
    @app.post("/api/imports/preview")
    async def preview_import(file: UploadFile = File(...), kind: str = Form("pending"), date_format: str = Form("DMY")):
        raw = await file.read(10 * 1024 * 1024 + 1)
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeError:
            raise ValueError("Use a UTF-8 CSV file.")
        return store.import_preview(text, Path(file.filename or "upload.csv").name, kind, date_format)
    @app.post("/api/imports/{iid}/commit")
    def commit_import(iid: str):
        return store.import_commit(iid)
    @app.get("/api/settings/llm")
    def llm_settings():
        return llm.status()
    @app.get('/api/settings/costs')
    def cost_settings():
        return store.cost_assumptions()
    @app.put('/api/settings/costs')
    def update_cost_settings(data: CostUpdate):
        return store.update_cost_assumptions(data.values.model_dump(), data.expected.model_dump())
    @app.put("/api/settings/llm")
    def llm_config(data: Settings):
        status = llm.configure(data.key, data.model, data.enabled, provider = data.provider)
        pipeline.retry_failed()
        return status
    @app.delete("/api/settings/llm")
    def llm_disconnect():
        return llm.disconnect()
    @app.get("/api/settings/models")
    def llm_models():
        return llm.models()
    @app.post("/api/settings/check")
    def llm_check():
        status = llm.check()
        pipeline.retry_failed()
        return status
    @app.get("/api/exports/decisions")
    def export():
        s = io.StringIO()
        writer = csv.writer(s)
        writer.writerow(["request_id", "status", "decision", "amount_usd", "reason", "policy_id"])
        for obj in store.requests():
            d = obj["decision"]
            values=[obj["external_id"],obj["status"],d["action"] if d else "",f'{d["amount_cents"]/100:.2f}' if d and d["amount_cents"] else "",d["reason"] if d else obj["evaluation"]["explanation"],d["policy_id"] if d else ""]
            writer.writerow(["'" + v if str(v).startswith(("=", "+", "-", "@")) else v for v in values])
        return Response(
            s.getvalue(),
            media_type = "text/csv",
            headers = {"Content-Disposition": 'attachment; filename="refund-decisions.csv"'}
        )
    dist = ROOT / "frontend/dist"
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory = dist / "assets"), name = "assets")
    @app.get("/{path:path}")
    def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "API route not found")
        if (dist / "index.html").exists():
            return FileResponse(dist / "index.html")
        return JSONResponse({"detail": "Build the frontend with npm run build, or use the Vite dev server."}, 503)
    return app
app = create_app()

