"""SQLite repository. All state-changing operations use explicit transactions."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
import uuid
from pathlib import Path
from.domain import policy_content, initial_policy, fingerprint, pending_evidence, evaluate, parse_csv, validate_policy, normalize, payment_constraint
from.experiments import ExperimentStore, EXPERIMENT_SCHEMA, decision_signature
from.workspace import WorkspaceStore, WORKSPACE_SCHEMA
from.catalog import explain
from.financial import policy_execution_limits

def now():
    return datetime.now(timezone.utc).isoformat()
def uid():
    return uuid.uuid4().hex
def dump(value):
    return json.dumps(value, ensure_ascii = False, separators = (",", ":"))
class Conflict(ValueError):
    pass
class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS imports(id TEXT PRIMARY KEY,hash TEXT NOT NULL,kind TEXT NOT NULL,name TEXT NOT NULL,rows TEXT NOT NULL,committed INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,UNIQUE(hash,kind));
CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,external_id TEXT UNIQUE NOT NULL,data TEXT NOT NULL,versions TEXT NOT NULL,evidence TEXT NOT NULL,evaluation TEXT NOT NULL,status TEXT NOT NULL,queue TEXT NOT NULL,owner TEXT,version INTEGER NOT NULL DEFAULT 1,conflict INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS history(id TEXT PRIMARY KEY,data TEXT NOT NULL,raw TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS policies(id TEXT PRIMARY KEY,name TEXT NOT NULL,data TEXT NOT NULL,hash TEXT NOT NULL,status TEXT NOT NULL,parent_id TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS previews(id TEXT PRIMARY KEY,policy TEXT NOT NULL,base_id TEXT NOT NULL,workspace_fingerprint TEXT NOT NULL,data TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,action TEXT NOT NULL,amount_cents INTEGER,reason TEXT NOT NULL,actor TEXT NOT NULL,policy_id TEXT NOT NULL,request_version INTEGER NOT NULL,idempotency_key TEXT UNIQUE NOT NULL,payload_hash TEXT NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(request_id) REFERENCES requests(id));
CREATE TABLE IF NOT EXISTS ledger(id TEXT PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,decision_id TEXT UNIQUE NOT NULL,amount_cents INTEGER NOT NULL CHECK(amount_cents>0),status TEXT NOT NULL,destination TEXT NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(decision_id) REFERENCES decisions(id));
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,object_id TEXT NOT NULL,type TEXT NOT NULL,actor TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outcomes(id TEXT PRIMARY KEY,request_id TEXT NOT NULL,type TEXT NOT NULL,note TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS llm_calls(id TEXT PRIMARY KEY,purpose TEXT NOT NULL,model TEXT NOT NULL,provider TEXT,usage TEXT NOT NULL,cost REAL,latency REAL NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS llm_cache(key TEXT PRIMARY KEY,data TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS candidate_evidence(criteria_hash TEXT NOT NULL,request_id TEXT NOT NULL,request_version INTEGER NOT NULL,evidence TEXT NOT NULL,PRIMARY KEY(criteria_hash,request_id));
"""
class Store(ExperimentStore, WorkspaceStore):
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents = True, exist_ok = True)
        with self.connect() as c:
            c.executescript(SCHEMA)
            c.executescript(EXPERIMENT_SCHEMA)
            c.executescript(WORKSPACE_SCHEMA)
            from.shadow import SHARED_SHADOW_SCHEMA
            migrate_assignments = not c.execute('SELECT 1 FROM schema_version WHERE version=3').fetchone()
            c.executescript(SHARED_SHADOW_SCHEMA)
            if migrate_assignments:
                c.execute("UPDATE requests SET owner=NULL,status=CASE WHEN status='in_review' THEN 'ready' ELSE status END,version=version+1 WHERE owner IS NOT NULL OR status='in_review'")
            c.execute("""INSERT OR IGNORE INTO automation_spend
                SELECT d.id,d.policy_id,json_extract(r.data,'$.customer_id'),d.amount_cents,d.created_at
                FROM decisions d JOIN requests r ON r.id=d.request_id
                WHERE d.action!='rejected' AND EXISTS(SELECT 1 FROM audit a WHERE a.object_id=r.id
                AND a.type='decision_recorded' AND json_extract(a.detail,'$.automatic')=1)""")
            defaults = {"mode": "simulate", "epoch": "0", "as_of": "2026-09-06"}
            for k, v in defaults.items():
                c.execute("INSERT OR IGNORE INTO state VALUES(?,?)", (k, v))
            # Current always processes eligible approvals. Per-request checks still apply.
            c.execute("UPDATE state SET value='simulate' WHERE key='mode'")
            if not c.execute("SELECT 1 FROM policies").fetchone():
                p = initial_policy()
                pid = uid()
                p.update(name = "Manual review baseline", automation_enabled = False)
                c.execute(
                    "INSERT INTO policies VALUES(?,?,?,?,?,?,?)",
                    (pid, p["name"], dump(p), fingerprint(p), "active", None, now())
                )
                c.execute("INSERT INTO state VALUES('active_policy',?)", (pid,))
            self.migrate_decision_references(c)
    def connect(self):
        c = sqlite3.connect(self.path, timeout = 10, isolation_level = None, factory = ClosingConnection)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=10000")
        return c
    @contextmanager
    def tx(self):
        c = self.connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()
    def state(self, c = None):
        if c is not None:
            return dict(c.execute("SELECT key,value FROM state").fetchall())
        with self.connect() as db:
            return self.state(db)
    def audit(self, c, obj, kind, detail, actor = "system"):
        c.execute(
            "INSERT INTO audit(object_id,type,actor,detail,created_at) VALUES(?,?,?,?,?)",
            (obj, kind, actor, dump(detail), now())
        )
    def policy(self, c = None):
        if c is None:
            with self.connect() as db:
                return self.policy(db)
        row = c.execute(
            "SELECT rowid AS version,* FROM policies WHERE id=?",
            (self.state(c)["active_policy"],)
        ).fetchone()
        data = policy_content(json.loads(row['data']))
        return {** dict(row), "data": data, "execution_limits": policy_execution_limits(c, row['id'], data)}
    def request(self, rid, c = None):
        if c is None:
            with self.connect() as db:
                return self.request(rid, db)
        row = c.execute("SELECT * FROM requests WHERE id=? OR external_id=?", (rid, rid)).fetchone()
        if not row:
            raise KeyError("Request not found")
        obj = dict(row)
        for k in ("data", "versions", "evidence", "evaluation"):
            obj[k] = json.loads(obj[k])
        obj['data'] = self.with_context(obj['data'], c)
        obj["decision"] = dict(d) if (
            d := c.execute("SELECT * FROM decisions WHERE request_id=?", (obj["id"],)).fetchone()
        ) else None
        obj["ledger"] = dict(l) if (
            l := c.execute("SELECT * FROM ledger WHERE request_id=?", (obj["id"],)).fetchone()
        ) else None
        obj['automation_blocker'] = None
        if not obj['decision'] and obj['status'] in ('ready', 'in_review') and obj['evaluation']['action'] == 'auto_approve':
            obj['automation_blocker'] = self.check_release_budget(c, obj, obj['data']['amount_cents'])
            if obj['automation_blocker']:
                obj['evaluation'] = self.execution_review(obj['evaluation'], obj['automation_blocker'])
                obj['queue'] = 'review'
        obj["evaluation"] = explain(obj["evaluation"], obj["data"], obj["evidence"])
        follow = c.execute("SELECT note,closed FROM reopened WHERE request_id=?", (obj["id"],)).fetchone()
        obj["follow_up"] = dict(follow) if follow else None
        obj['execution_state'] = 'paid_simulated' if obj['ledger'] else 'decided' if obj['decision'] else obj['status']
        if not obj['decision'] and obj['evaluation']['action'] == 'auto_approve':
            obj['execution_state'] = 'ready_to_execute' if obj['status'] == 'ready' and self.state(c)['mode'] == 'simulate' and not self.check_release_budget(
                c,
                obj,
                obj['data']['amount_cents']
            ) else 'would_approve'
        return obj
    @staticmethod
    def execution_review(ev, message):
        return {** ev, 'action': 'review', 'queue': 'review', 'reason_code': 'execution_check',
            'explanation': message, 'proposed_amount_cents': 0, 'evaluation_stage': 'execution_check',
            'resolution': {
                ** ev.get('resolution', {}),
                'kind': 'execution_check',
                'summary': message,
                'required_check': 'execution_check'
            },
            'trace': [
                {
                    ** t,
                    ** (
                        {'outcome_role': 'overridden', 'selection_explanation': message} if t.get('outcome_role') == 'selected' else {}
                    )
                } for t in ev.get('trace', [])
            ]}
    def with_context(self, data, c):
        from.source_rebuild import context_issues
        history = [
            json.loads(row[0]) for row in c.execute(
                "SELECT data FROM history WHERE json_extract(data,'$.customer_id')=? AND json_extract(data,'$.requested_at')<?",
                (data.get('customer_id'), data.get('requested_at'))
            )
        ]
        issues = context_issues(data, history)
        return {** {k: v for k, v in data.items() if k != 'context_issues'}, ** ({'context_issues': issues} if issues else {})}
    def correct(self, rid, version, changes, note, actor):
        if not note.strip():
            raise ValueError("Explain the source of the correction.")
        allowed = {
            "requested_at",
            "customer_id",
            "amount_usd",
            "tenure_months",
            "prior_refunds_12m",
            "days_since_delivery",
            "fraud_flag",
            "stated_reason",
            "customer_note",
            "support_note",
            "category",
            "payment_method"
        }
        if not set(changes) <= allowed:
            raise ValueError("Only request-time source fields can be corrected. Request ID is immutable.")
        with self.tx() as c:
            obj = self.request(rid, c)
            self.check_version(obj, version)
            if obj["status"] == "resolved":
                raise Conflict("A resolved request cannot be changed.")
            raw = {
                k: str(v) if v is not None else "" for k,
                v in obj["data"].items() if k not in ("errors", "warnings", "amount_cents")
            }
            raw["fraud_flag"] = "yes" if obj["data"]["fraud_flag"] is True else "no" if obj["data"]["fraud_flag"] is False else ""
            raw.update(changes)
            data = self.with_context(normalize(raw), c)
            e = pending_evidence(data)
            ev = evaluate(data, e, self.policy(c)["data"], bool(obj["conflict"]))
            versions = obj["versions"] + [
                {"raw": raw, "normalized": data, "hash": fingerprint(raw), "line": None, "correction": note}
            ]
            c.execute(
                "UPDATE requests SET data=?,versions=?,evidence=?,evaluation=?,queue=?,version=version+1 WHERE id=?",
                (dump(data), dump(versions), dump(e), dump(ev), ev["queue"], obj["id"])
            )
            self.audit(c, obj["id"], "source_corrected", {"fields": sorted(changes), "reason": note}, actor)
            self.capture_shadow(c, obj["id"])
            return self.request(obj["id"], c)
    def requests(self):
        with self.connect() as c:
            return [
                self.request(r[0], c) for r in c.execute("SELECT id FROM requests ORDER BY created_at,id").fetchall()
            ]
    def check_version(self, obj, version):
        if obj["version"] != version:
            raise Conflict("This request changed. Refresh before acting.")
    def import_preview(self, text, name, kind, date_format = "DMY"):
        rows = parse_csv(text, date_format)
        if kind not in ("pending", "history"):
            raise ValueError("Choose pending or history")
        if kind == "pending" and any(x["normalized"]["decision"] not in ("pending", "") for x in rows):
            raise ValueError("Operational imports must contain pending decisions only.")
        h = fingerprint([text, date_format])
        iid = uid()
        with self.tx() as c:
            old = c.execute("SELECT id FROM imports WHERE hash=? AND kind=?", (h, kind)).fetchone()
            if old:
                return self.import_info(old[0], c)
            c.execute("INSERT INTO imports VALUES(?,?,?,?,?,0,?)", (iid, h, kind, name, dump(rows), now()))
            return self.import_info(iid, c)
    def import_info(self, iid, c = None):
        if c is None:
            with self.connect() as db:
                return self.import_info(iid, db)
        row = c.execute("SELECT * FROM imports WHERE id=?", (iid,)).fetchone()
        if not row:
            raise KeyError("Import not found")
        rows = json.loads(row["rows"])
        seen = {}
        duplicates = 0
        for x in rows:
            key = x["normalized"]["request_id"]
            if key not in seen:
                seen[key] = set()
            if x["hash"] in seen[key]:
                duplicates += 1
            seen[key].add(x["hash"])
        return {"id": iid, "name": row["name"], "kind": row["kind"], "committed": bool(row["committed"]), "row_count": len(rows), "unique_ids": len(seen),
                "exact_duplicates": duplicates, "conflicts": [k for k, v in seen.items() if len(v) > 1],
                "issues": [
                    {
                        "line": x["line"],
                        "id": x["normalized"]["request_id"],
                        "errors": x["normalized"]["errors"],
                        "warnings": x["normalized"]["warnings"]
                    } for x in rows if x["normalized"]["errors"] or x["normalized"]["warnings"]
                ]}
    def import_commit(self, iid):
        with self.tx() as c:
            batch = c.execute("SELECT * FROM imports WHERE id=?", (iid,)).fetchone()
            if not batch:
                raise KeyError("Import not found")
            if batch["committed"]:
                return self.import_info(iid, c)
            p = self.policy(c)["data"]
            for x in json.loads(batch["rows"]):
                d = x["normalized"]
                ext = d["request_id"] or "missing-" + x["hash"][: 12]
                if batch["kind"] == "history":
                    old = c.execute("SELECT raw FROM history WHERE id=?", (ext,)).fetchone()
                    if old and fingerprint(json.loads(old[0])) != x["hash"]:
                        raise ValueError("Conflicting historical versions require reconciliation: " + ext)
                    c.execute("INSERT OR IGNORE INTO history VALUES(?,?,?)", (ext, dump(d), dump(x["raw"])))
                    continue
                old = c.execute("SELECT id FROM requests WHERE external_id=?", (ext,)).fetchone()
                if old:
                    obj = self.request(old[0], c)
                    if any(v["hash"] == x["hash"] for v in obj["versions"]):
                        continue
                    versions = obj["versions"] + [x]
                    ev = evaluate(obj["data"], obj["evidence"], p, True)
                    c.execute(
                        "UPDATE requests SET versions=?,conflict=1,evaluation=?,queue='data',version=version+1 WHERE id=?",
                        (dump(versions), dump(ev), obj["id"])
                    )
                    self.audit(c, obj["id"], "version_conflict", {"new_hash": x["hash"]})
                else:
                    d = self.with_context(d, c)
                    rid = uid()
                    e = pending_evidence(d)
                    ev = evaluate(d, e, p)
                    c.execute(
                        "INSERT INTO requests VALUES(?,?,?,?,?,?,?,?,NULL,1,0,?)",
                        (rid, ext, dump(d), dump([x]), dump(e), dump(ev), "ready", ev["queue"], now())
                    )
                    self.audit(c, rid, "imported", {"batch": iid, "source_line": x["line"]})
            c.execute("UPDATE imports SET committed=1 WHERE id=?", (iid,))
            if batch["kind"] == "pending":
                for row in c.execute("SELECT id FROM requests WHERE status!='resolved'").fetchall():
                    self.capture_shadow(c, row[0])
            self.audit(c, iid, "import_committed", self.import_info(iid, c))
            return self.import_info(iid, c)
    def seed(self, data_dir):
        for name, kind in (("history.csv", "history"), ("pending.csv", "pending")):
            info = self.import_preview((Path(data_dir) / name).read_text(encoding = "utf-8-sig"), name, kind)
            self.import_commit(info["id"])
    def refresh_evaluations(self):
        with self.tx() as c:
            p = self.policy(c)["data"]
            for row in c.execute("SELECT id FROM requests WHERE status='ready'").fetchall():
                obj = self.request(row[0], c)
                ev = evaluate(obj["data"], obj["evidence"], p, bool(obj["conflict"]))
                if ev != obj["evaluation"]:
                    c.execute(
                        "UPDATE requests SET evaluation=?,queue=?,version=version+1 WHERE id=?",
                        (dump(ev), ev["queue"], obj["id"])
                    )
                    self.audit(c, obj["id"], "evaluation_refreshed", {"reason": ev["reason_code"]})
    def update_evidence(self, rid, e, expected_version, actor = "system"):
        with self.tx() as c:
            obj = self.request(rid, c)
            self.check_version(obj, expected_version)
            if obj["status"] == "resolved":
                raise Conflict("Resolved requests cannot be re-analysed.")
            # Preserve separately recorded human evidence.
            for name, fact in obj["evidence"].get("facts", {}).items():
                if fact.get("source") == "human":
                    e["facts"][name] = fact
            if obj["evidence"].get("reviewed_by"):
                e.setdefault("reviewed_by", obj["evidence"]["reviewed_by"])
                if obj["evidence"].get("staff_review_note"):
                    e.setdefault("staff_review_note", obj["evidence"]["staff_review_note"])
            ev = evaluate(obj["data"], e, self.policy(c)["data"], bool(obj["conflict"]))
            c.execute(
                "UPDATE requests SET evidence=?,evaluation=?,queue=?,version=version+1 WHERE id=?",
                (dump(e), dump(ev), ev["queue"], obj["id"])
            )
            self.audit(
                c,
                obj["id"],
                "evidence_updated",
                {"method": e["method"], "complete": e["complete"], "reason": ev["reason_code"]},
                actor
            )
            self.capture_shadow(c, obj["id"])
            return self.request(obj["id"], c)
    def review_evidence(self, rid, version, facts, note, actor):
        if not note.strip():
            raise ValueError("Record what you checked.")
        obj = self.request(rid)
        e = obj["evidence"]
        from.domain import FACTS, BOOLEAN_FACTS, REASONS
        for name, value in facts.items():
            if name not in FACTS:
                raise ValueError("Unsupported fact")
            if name in BOOLEAN_FACTS and value not in ("yes", "no", "unknown"):
                raise ValueError("Invalid evidence value")
            if name == "effective_reason" and value not in REASONS:
                raise ValueError("Invalid reason")
            e["facts"][name] = {"name": name, "value": value, "source": "human", "quote": note}
        e["reviewed_by"] = actor
        e["staff_review_note"] = note
        return self.update_evidence(rid, e, version, actor)
    def workflow(self, rid, version, action, actor, note = ""):
        mapping = {"information": "waiting_for_customer", "fraud": "waiting_for_fraud", "resume": "ready", "hold": "on_hold"}
        if action not in mapping:
            raise ValueError("Unsupported workflow action")
        if action in ("information", "fraud", "hold", "resume") and not note.strip():
            raise ValueError("A reason is required.")
        with self.tx() as c:
            obj = self.request(rid, c)
            self.check_version(obj, version)
            if obj["status"] == "resolved":
                raise Conflict("Request is already resolved.")
            if action == "resume" and obj["status"].startswith("waiting"):
                waiting = c.execute(
                    "SELECT MAX(id) FROM audit WHERE object_id=? AND type IN ('information','fraud')",
                    (obj["id"],)
                ).fetchone()[0] or 0
                if not c.execute(
                    "SELECT 1 FROM audit WHERE object_id=? AND id>? AND type IN ('evidence_updated','source_corrected')",
                    (obj["id"], waiting)
                ).fetchone():
                    raise Conflict("Record and verify the new evidence before resuming this request.")
            status = mapping[action]
            queue = "hold" if action == "hold" else "fraud" if action == "fraud" else "information" if action == "information" else obj["evaluation"]["queue"]
            c.execute(
                "UPDATE requests SET status=?,queue=?,owner=NULL,version=version+1 WHERE id=?",
                (status, queue, obj["id"])
            )
            self.audit(c, obj["id"], action, {"note": note}, actor)
            return self.request(obj["id"], c)
    def resolve(self, rid, version, index, note, actor):
        if not note.strip():
            raise ValueError("Explain which version you accepted.")
        with self.tx() as c:
            obj = self.request(rid, c)
            self.check_version(obj, version)
            if obj["status"] == "resolved":
                raise Conflict("A settled request cannot authorize another refund.")
            if not 0 <= index < len(obj["versions"]):
                raise ValueError("Unknown version")
            d = obj["versions"][index]["normalized"]
            e = pending_evidence(d)
            ev = evaluate(d, e, self.policy(c)["data"])
            c.execute(
                "UPDATE requests SET data=?,evidence=?,evaluation=?,conflict=0,queue=?,version=version+1 WHERE id=?",
                (dump(d), dump(e), dump(ev), ev["queue"], obj["id"])
            )
            self.audit(c, obj["id"], "conflict_resolved", {"selected": index, "note": note}, actor)
            self.capture_shadow(c, obj["id"])
            return self.request(obj["id"], c)
    def decide(self, rid, version, action, amount, reason, actor, key, automatic = False):
        if action not in ("approved", "rejected", "partial"):
            raise ValueError("Unsupported decision")
        if not reason.strip():
            raise ValueError("A decision reason is required.")
        payload = fingerprint([rid, version, action, amount, reason, actor, automatic])
        with self.tx() as c:
            existing = c.execute("SELECT * FROM decisions WHERE idempotency_key=?", (key,)).fetchone()
            if existing:
                if existing["payload_hash"] != payload:
                    raise Conflict("Idempotency key was used for a different operation.")
                return self.request(existing["request_id"], c)
            obj = self.request(rid, c)
            self.check_version(obj, version)
            if obj["status"] == "resolved":
                raise Conflict("This request has already been decided.")
            p = self.policy(c)
            state = self.state(c)
            ev = evaluate(obj["data"], obj["evidence"], p["data"], bool(obj["conflict"]))
            if obj["status"] in ("on_hold", "waiting_for_customer", "waiting_for_fraud"):
                raise Conflict("Verify the evidence and resume the request before making a decision.")
            if ev["action"] == "hold":
                raise Conflict("This request is held by the active policy. Change and qualify the policy before deciding.")
            if automatic and (obj["status"] != "ready" or ev["action"] != "auto_approve"):
                raise Conflict("Automatic execution is no longer permitted.")
            maximum = obj["data"].get("amount_cents")
            if action != "rejected":
                if obj["conflict"] or obj["data"]["errors"]:
                    raise Conflict("Resolve data errors and conflicting versions before paying.")
                if type(amount) is not int or not maximum or amount <= 0 or amount > maximum:
                    raise ValueError("Refund amount must be positive and within the accepted request amount.")
                if action == "approved" and amount != maximum:
                    raise ValueError("Full approval must equal the request amount.")
                if action == "partial" and amount >= maximum:
                    raise ValueError("Partial must be less than the full amount.")
            elif amount not in (None, 0):
                raise ValueError("Rejected requests cannot move money.")
            if constraint := payment_constraint(obj['data'], obj['evidence'], p['data'], action):
                raise Conflict(constraint)
            if automatic:
                blocked = self.check_release_budget(c, obj, amount)
                if blocked:
                    raise Conflict(blocked + ". This request remains available for manual review.")
            self.capture_shadow(c, obj["id"])
            did = uid()
            c.execute(
                "INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (did, obj["id"], action, amount, reason, actor, p["id"], version, key, payload, now())
            )
            if action != "rejected":
                c.execute(
                    "INSERT INTO ledger VALUES(?,?,?,?,?,?,?)",
                    (uid(), obj["id"], did, amount, "simulated_succeeded", "original_payment_only", now())
                )
                if automatic:
                    c.execute(
                        "INSERT INTO automation_spend VALUES(?,?,?,?,?)",
                        (did, p["id"], obj["data"]["customer_id"], amount, now())
                    )
            c.execute(
                "UPDATE requests SET status='resolved',version=version+1,evaluation=? WHERE id=?",
                (dump(ev), obj["id"])
            )
            c.execute("INSERT INTO decision_context VALUES(?,?)", (did, dump(ev)))
            if not automatic:
                self.record_decision_reference(c, obj, did, action, amount, reason, actor)
            self.audit(
                c,
                obj["id"],
                "decision_recorded",
                {
                    "action": action,
                    "amount_cents": amount,
                    "reason": reason,
                    "policy_id": p["id"],
                    "rule_id": ev.get("rule_id"),
                    "automatic": automatic
                },
                actor
            )
            return self.request(obj["id"], c)
    def apply_automation(self, request_ids = None):
        applied = []
        skipped = []
        for obj in self.requests():
            if request_ids is not None and obj['id'] not in request_ids:
                continue
            if obj["status"] != "ready":
                continue
            try:
                current = self.policy()["data"]
                ev = evaluate(obj["data"], obj["evidence"], current, bool(obj["conflict"]))
                if ev["action"] == "auto_approve":
                    self.decide(
                        obj["id"],
                        obj["version"],
                        "approved",
                        obj["data"]["amount_cents"],
                        ev["explanation"],
                        "automation",
                        "auto-" + obj["id"],
                        True
                    )
                    applied.append(obj["external_id"])
            except Conflict as ex:
                skipped.append({"id": obj["external_id"], "reason": str(ex)})
        return {"applied": applied, "skipped": skipped}
    def mode(self, mode):
        if mode != 'simulate':
            raise ValueError('Current automatic execution is always on. Change the policy rules or limits instead.')
        return self.state()
    def workspace_fingerprint(self, c):
        rows = c.execute("SELECT id,version,status FROM requests ORDER BY id").fetchall()
        history = c.execute("SELECT id,data FROM history ORDER BY id").fetchall()
        return fingerprint([self.state(c), [list(x) for x in rows], [list(x) for x in history]])
    def prepare_candidate(self, policy, rid, evidence, version):
        with self.tx() as c:
            obj = self.request(rid, c)
            self.check_version(obj, version)
            for name, fact in obj["evidence"].get("facts", {}).items():
                if fact.get("source") == "human":
                    evidence["facts"][name] = fact
            evidence["criteria_hash"] = fingerprint(policy["criteria"])
            c.execute(
                "INSERT OR REPLACE INTO candidate_evidence VALUES(?,?,?,?)",
                (fingerprint(policy["criteria"]), obj["id"], version, dump(evidence))
            )
            self.capture_shadow(c, obj["id"])
    def candidate(self, c, obj, policy):
        row = c.execute(
            "SELECT evidence FROM candidate_evidence WHERE criteria_hash=? AND request_id=? AND request_version=?",
            (fingerprint(policy["criteria"]), obj["id"], obj["version"])
        ).fetchone()
        return json.loads(row[0]) if row else obj["evidence"]
    def preview(self, data):
        p, issues = validate_policy(data)
        if issues:
            raise ValueError("; ".join(issues))
        with self.tx() as c:
            current = self.policy(c)
            changes = []
            prepared = {}
            counts = {
                "old_auto": 0,
                "new_auto": 0,
                "old_amount": 0,
                "new_amount": 0,
                "new_review": 0,
                "new_fraud": 0,
                "new_information": 0,
                "new_hold": 0
            }
            for row in c.execute("SELECT id FROM requests WHERE status='ready'").fetchall():
                obj = self.request(row[0], c)
                candidate = self.candidate(c, obj, p)
                prepared[obj["id"]] = candidate
                old = evaluate(obj["data"], obj["evidence"], current["data"], bool(obj["conflict"]))
                new = evaluate(obj["data"], candidate, p, bool(obj["conflict"]))
                if new["action"] != "auto_approve":
                    counts["new_" + new["action"]] += 1
                for label, ev in (("old", old), ("new", new)):
                    if ev["action"] == "auto_approve":
                        counts[label + "_auto"] += 1
                        counts[label + "_amount"] += obj["data"]["amount_cents"]
                if decision_signature(old) != decision_signature(new):
                    changes.append(
                        {
                            "id": obj["external_id"],
                            "amount_cents": obj["data"]["amount_cents"],
                            "old": old,
                            "new": new
                        }
                    )
            historical = []
            for row in c.execute("SELECT * FROM history").fetchall():
                r = json.loads(row["data"])
                e = pending_evidence(r)
                old = evaluate(r, e, current["data"])
                new = evaluate(r, e, p)
                if decision_signature(old) != decision_signature(new):
                    historical.append(
                        {
                            "id": row["id"],
                            "old": old["action"],
                            "new": new["action"],
                            "observed_decision": r["decision"],
                            "outcome": r["outcome_note"],
                            "evidence_mode": "pending model analysis"
                        }
                    )
            pid = uid()
            wf = self.workspace_fingerprint(c)
            report = {"id": pid, "counts": counts, "changes": changes, "historical_changes": historical, "eligible": len(c.execute("SELECT id FROM requests WHERE status='ready'").fetchall()), "excluded": len(c.execute("SELECT id FROM requests WHERE status!='ready'").fetchall()),
                    "limitations": [
                        "Missing model extraction stays incomplete. Future outcome fields never enter evaluation.",
                        "Only ready requests are eligible. A preview does not execute refunds."
                    ], "policy": p, "prepared_evidence": prepared}
            c.execute("INSERT INTO previews VALUES(?,?,?,?,?,?)", (pid, dump(p), current["id"], wf, dump(report), now()))
            return report
    def activate(self, preview_id, reason):
        raise Conflict("Direct activation is disabled. Save a policy version, run backtest and prospective Shadow, then pass its release gates.")
    def policies(self):
        with self.connect() as c:
            return [{** dict(r), "data": policy_content(json.loads(r["data"])),
                     "execution_limits": policy_execution_limits(c, r['id'], json.loads(r['data']))}
                    for r in c.execute("SELECT rowid AS version,* FROM policies ORDER BY rowid DESC").fetchall()]
    def audit_list(self, obj = None):
        with self.connect() as c:
            rows = c.execute(
                "SELECT * FROM audit " + ("WHERE object_id=? "if obj else "") + "ORDER BY id DESC LIMIT 300",
                (obj,) if obj else ()
            ).fetchall()
            return [{** dict(x), "detail": json.loads(x["detail"])} for x in rows]
    def metrics(self):
        requests = self.requests()
        with self.connect() as c:
            history = [json.loads(x[0]) for x in c.execute("SELECT data FROM history")]
            manual = [x for x in history if x["decided_by"] != "auto"]
            calls = [dict(x) for x in c.execute("SELECT * FROM llm_calls")]
            total_cost = sum(x["cost"] for x in calls if x["cost"] is not None)
            ledger = [dict(x) for x in c.execute("SELECT * FROM ledger")]
            outcomes = {r[0]: r[1] for r in c.execute("SELECT type,COUNT(*) FROM outcomes GROUP BY type")}
            decisions = [dict(x) for x in c.execute("SELECT * FROM decisions")]
            latency = sorted(x["latency"] for x in calls)
        return {"requests": len(requests), "resolved": sum(x["status"] == "resolved" for x in requests), "ready_auto": sum(x["status"] == "ready" and x["evaluation"]["action"] == "auto_approve" for x in requests),
            "review": sum(x["status"] != "resolved" and x["evaluation"]["action"] != "auto_approve" for x in requests), "conflicts": sum(bool(x["conflict"]) for x in requests),
            "refund_cents": sum(x["amount_cents"] for x in ledger), "refund_count": len(ledger),
            "baseline": {
                "requests": len(history),
                "auto": sum(x["decided_by"] == "auto"for x in history),
                "manual": len(manual),
                "manual_approved": sum(x["decision"] == "approved"for x in manual),
                "review_minutes": sum(float(x["review_minutes"]or 0)for x in manual),
                "chargebacks": sum("chargeback"in x["outcome_note"].lower()for x in history),
                "unknown_outcomes": sum(not x["outcome_note"]for x in history)
            },
            "ai": {
                "calls": len(calls),
                "cost_usd": total_cost,
                "unknown_cost_calls": sum(x["cost"]is None for x in calls),
                "failures": sum(x["status"] != "ok"for x in calls),
                "p95_latency_seconds": latency[min(len(latency) - 1, int(len(latency) * .95))] if latency else None
            },
            "quality": {
                "outcomes": outcomes,
                "decisions": len(decisions),
                "automatic_decisions": sum(x["actor"] == "automation"for x in decisions),
                "waiting": sum(x["status"].startswith("waiting")for x in requests)
            },
            "state": self.state(), "policy": self.policy()["name"]}

