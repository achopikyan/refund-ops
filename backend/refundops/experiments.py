"""Policy trials, immutable observations, adjudication and atomic release controls."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from .domain import evaluate, pending_evidence, fingerprint, validate_policy, compare
from .financial import ReleaseSettings, financial_report
from .mining import discover
from .shadow import SharedShadowStore, comparison_metrics

ENGINE_REVISION = fingerprint([(Path(__file__).parent / n).read_text(encoding="utf-8")
                               for n in ("domain.py", "catalog.py", "financial.py", "experiments.py", "shadow.py")])

def decision_signature(ev):
    return tuple(ev.get(k) for k in ('action','rule_id','reason_code','explanation','proposed_amount_cents'))

EXPERIMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments(id TEXT PRIMARY KEY,policy TEXT NOT NULL,base_id TEXT NOT NULL,baseline TEXT NOT NULL,manifest TEXT NOT NULL,settings TEXT NOT NULL,status TEXT NOT NULL,backtest TEXT,initial_ids TEXT,created_at TEXT NOT NULL,started_at TEXT,activated_policy_id TEXT);
CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY,experiment_id TEXT NOT NULL,request_id TEXT NOT NULL,input_hash TEXT NOT NULL,snapshot TEXT NOT NULL,baseline TEXT NOT NULL,candidate TEXT NOT NULL,cohort TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(experiment_id,request_id,input_hash),FOREIGN KEY(experiment_id) REFERENCES experiments(id));
CREATE INDEX IF NOT EXISTS observation_experiment ON observations(experiment_id,request_id);
CREATE TABLE IF NOT EXISTS observation_heads(experiment_id TEXT NOT NULL,request_id TEXT NOT NULL,observation_id TEXT NOT NULL,PRIMARY KEY(experiment_id,request_id),FOREIGN KEY(observation_id) REFERENCES observations(id));
CREATE TABLE IF NOT EXISTS adjudications(seq INTEGER PRIMARY KEY AUTOINCREMENT,observation_id TEXT NOT NULL,data TEXT NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(observation_id) REFERENCES observations(id));
CREATE TABLE IF NOT EXISTS release_limits(policy_id TEXT PRIMARY KEY,settings TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS automation_spend(decision_id TEXT PRIMARY KEY,policy_id TEXT NOT NULL,customer_id TEXT NOT NULL,amount_cents INTEGER NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(decision_id) REFERENCES decisions(id));
CREATE TABLE IF NOT EXISTS mining_runs(id TEXT PRIMARY KEY,report TEXT NOT NULL,created_at TEXT NOT NULL);
INSERT OR IGNORE INTO schema_version VALUES(2);
"""


def request_input(data):
    return {k: v for k, v in data.items() if k not in {"decision", "decided_by", "decided_at", "review_minutes", "outcome_note"}}


def assess(data, evidence, policy, conflict=False):
    return evaluate(request_input(data), deepcopy(evidence), policy, conflict)


class ExperimentStore(SharedShadowStore):
    def cost_assumptions(self, c=None):
        from .financial import CostAssumptions
        if c is None:
            with self.connect() as db:return self.cost_assumptions(db)
        value=self.state(c).get('cost_assumptions')
        return CostAssumptions.model_validate(json.loads(value) if value else {}).model_dump()

    def update_cost_assumptions(self, values, expected):
        from .storage import Conflict, dump
        from .financial import CostAssumptions
        values=CostAssumptions.model_validate(values).model_dump()
        with self.tx() as c:
            old=self.cost_assumptions(c)
            if old!=expected:raise Conflict('Cost assumptions changed elsewhere. Reload Settings before editing.')
            c.execute("INSERT INTO state VALUES('cost_assumptions',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(dump(values),))
            self.audit(c,'cost_assumptions','cost_assumptions_updated',{'before':old,'after':values},'manager')
        return values

    def update_shadow_requirements(self, eid, values, expected):
        from .storage import Conflict, dump
        from .financial import ShadowRequirements
        values=ShadowRequirements.model_validate(values).model_dump()
        with self.tx() as c:
            ex=self.experiment(eid,c)
            if ex['status'] not in ('draft','backtested'):
                raise Conflict('Shadow requirements are locked after Shadow starts.')
            old={key:ex['settings'][key] for key in ShadowRequirements.model_fields}
            if old!=expected:raise Conflict('Shadow requirements changed elsewhere. Reload before editing.')
            config={**ex['settings'],**values}
            c.execute('UPDATE experiments SET settings=? WHERE id=?',(dump(config),eid))
            self.audit(c,eid,'shadow_requirements_updated',{'before':old,'after':values},'manager')
        return values

    def manifest(self):
        value = {"engine": ENGINE_REVISION}
        if getattr(self, "runtime_manifest", None):
            value.update(self.runtime_manifest())
        return value

    def experiment(self, eid, c=None):
        if c is None:
            with self.connect() as db:
                return self.experiment(eid, db)
        row = c.execute("SELECT * FROM experiments WHERE id=?", (eid,)).fetchone()
        if not row:
            raise KeyError("Policy version checks not found")
        obj = dict(row)
        for key in ("policy", "baseline", "manifest", "settings", "backtest", "initial_ids"):
            obj[key] = json.loads(obj[key]) if obj[key] is not None else None
        from .domain import policy_content
        for key in ('policy','baseline'): obj[key] = policy_content(obj[key])
        source=c.execute('SELECT policy_id FROM trial_sources WHERE experiment_id=?',(eid,)).fetchone()
        obj['source_policy_id']=source[0] if source else None
        return obj

    def experiments(self):
        with self.connect() as c:
            return [self.experiment(r[0], c) for r in c.execute("SELECT id FROM experiments ORDER BY created_at DESC")]

    def create_experiment(self, policy, settings=None, policy_id=None):
        from .storage import uid, now, dump
        p, issues = validate_policy(policy)
        if issues:
            raise ValueError("; ".join(issues))
        settings = {**self.cost_assumptions(), **dict(settings or {})}
        if p.get('execution_limits') is not None:
            if any(key in settings and settings[key] != value for key,value in p['execution_limits'].items()):
                raise ValueError('Execution limits belong to the saved policy. Change them in policy Settings before starting checks.')
            settings.update(p['execution_limits'])
        config = ReleaseSettings.model_validate(settings).model_dump()
        with self.tx() as c:
            base = self.policy(c); eid = uid()
            if policy_id:
                if c.execute('SELECT 1 FROM trial_sources WHERE policy_id=?',(policy_id,)).fetchone():
                    from .storage import Conflict
                    raise Conflict('This policy version already has validation results. Open that version or save a new version to change its checks.')
                source=c.execute('SELECT data FROM policies WHERE id=?',(policy_id,)).fetchone()
                if not source or validate_policy(json.loads(source[0]))[0]!=p:
                    raise ValueError('Save this exact policy version before attaching its trial.')
            c.execute("INSERT INTO experiments VALUES(?,?,?,?,?,?,?,NULL,NULL,?,NULL,NULL)",
                      (eid, dump(p), base["id"], dump(base["data"]), dump(self.manifest()), dump(config), "draft", now()))
            if policy_id:c.execute('INSERT INTO trial_sources VALUES(?,?)',(eid,policy_id))
            self.audit(c, eid, "experiment_created", {"policy_hash": fingerprint(p), "base_id": base["id"], "settings": config}, "manager")
            return self.experiment(eid, c)

    def check_experiment_environment(self, ex, c):
        from .storage import Conflict
        if ex["base_id"] != self.policy(c)["id"]:
            raise Conflict("Current changed. Update checks for this same policy version to compare with the new Current.")
        if ex["manifest"] != self.manifest():
            raise Conflict("The model, prompt or analysis implementation changed. Update checks for this same policy version.")

    def backtest_experiment(self, eid):
        from .storage import Conflict, dump
        from .decision_metrics import historical_rows, build_report
        with self.tx() as c:
            ex = self.experiment(eid, c)
            if ex["status"] not in ("draft", "backtested", "shadow"):
                raise Conflict("Historical replay must precede Shadow.")
            self.check_experiment_environment(ex, c)
            rows = [json.loads(r[0]) for r in c.execute("SELECT data FROM history ORDER BY id")]
            cases = []
            coverage={rule['id']:{'rule_id':rule['id'],'name':rule['name'],'matched':0,'won':0,'shadowed':0} for rule in ex['policy']['rules'] if rule['enabled']}
            history_engine=getattr(self,'history_evidence',None)
            evidence_provider=(lambda data,criteria:history_engine.evidence(data,criteria,c)) if history_engine else None
            paired = historical_rows(rows, ex['baseline'], ex['policy'],evidence_provider)
            for data, pair in zip(rows, paired):
                old, new = pair['baseline'], pair['candidate']
                for rule in new['trace']:
                    if rule['matched'] is True:
                        coverage[rule['rule_id']]['matched']+=1
                        winner=new['resolution']['decisive_rule_id']==rule['rule_id']
                        coverage[rule['rule_id']]['won' if winner else 'shadowed']+=1
                cases.append({"id": data["request_id"], "amount_cents": data["amount_cents"], "baseline": old, "candidate": new,
                              "historical_decision": data["decision"], "historical_auto": data["decided_by"] == "auto",
                              "recorded_minutes": float(data["review_minutes"] or 0), "outcome_known": bool(data["outcome_note"]),
                              "known_chargeback": "chargeback" in data["outcome_note"].lower()})
            report = {"total": len(cases), "data_hash": fingerprint(rows), "cases": cases,"rule_coverage":list(coverage.values()),
                      "changed": sum(decision_signature(x["baseline"]) != decision_signature(x["candidate"]) for x in cases),
                      "old_auto": sum(x["baseline"]["action"] == "auto_approve" for x in cases),
                      "new_auto": sum(x["candidate"]["action"] == "auto_approve" for x in cases),
                      "old_amount_cents": sum(x["baseline"].get("proposed_amount_cents") or 0 for x in cases),
                      "new_amount_cents": sum(x["candidate"].get("proposed_amount_cents") or 0 for x in cases),
                      "unknown_outcomes": sum(not x["outcome_known"] for x in cases),
                      "limitations": ["Only saved model extraction supplies semantic facts. Missing extraction stays incomplete.",
                                      "Historical decisions are observations, not ground truth. No measured loss or causal savings.",
                                      "No note timestamps: decision-time availability is uncertain. Future outcomes never enter policy evaluation."]}
            if history_engine:
                report['limitations'][0]='Full validated live extraction, persisted for the exact request inputs, question set and model manifest.'
            report['evidence_fingerprint']=fingerprint([(r['id'],r['evidence'],r['baseline_evidence']) for r in paired])
            report['decision_report'] = build_report(paired, ex['baseline'], ex['policy'], ex['settings'], mode='backtest',
                metadata={'scope':'history', 'data_fingerprint':report['data_hash'], 'manifest':ex['manifest'],
                          'generated_at':datetime.now(timezone.utc).isoformat(), 'evidence_mode':'Full live extraction' if history_engine else 'Awaiting model extraction',
                          'evidence_fingerprint':report['evidence_fingerprint'],
                          'baseline_id':ex['base_id'], 'candidate_id':ex.get('source_policy_id')})
            c.execute("UPDATE experiments SET backtest=? WHERE id=?", (dump(report), eid))
            if ex["status"] != "shadow": c.execute("UPDATE experiments SET status='backtested' WHERE id=?", (eid,))
            self.audit(c, eid, "experiment_backtested", {"total": len(cases), "data_hash": report["data_hash"]}, "manager")
            return report

    def start_experiment(self, eid):
        from .storage import Conflict, dump, now
        with self.tx() as c:
            ex = self.experiment(eid, c)
            current_id = self.policy(c)['id']
            if ex.get('source_policy_id') == current_id or ex.get('activated_policy_id') == current_id:
                raise Conflict('Current is already serving requests and cannot run in Shadow. Create a new version first.')
            if ex["status"] not in ("backtested", "shadow"):
                raise Conflict("Run the historical replay before starting Shadow.")
            self.check_experiment_environment(ex, c)
            rows = [json.loads(r[0]) for r in c.execute("SELECT data FROM history ORDER BY id")]
            if ex["backtest"]["data_hash"] != fingerprint(rows):
                raise Conflict("Historical data changed. Run the replay again.")
            self._start_shared_shadow(c, eid)
        return self.experiment_report(eid)

    def _start_shared_shadow(self, c, eid):
        from .storage import now, dump
        ex = self.experiment(eid, c)
        ids = [r[0] for r in c.execute('SELECT id FROM requests')]
        if ex['status'] != 'shadow':
            c.execute("UPDATE experiments SET status='shadow',started_at=?,initial_ids=? WHERE id=?", (now(), dump(ids), eid))
            self.audit(c, eid, 'shadow_started', {'backlog': len(ids), 'trigger': 'manager_started'}, 'manager')
        for rid in ids:
            self.capture_shadow(c, rid)

    def capture_shadow(self, c, rid):
        from .storage import uid, now, dump
        obj = self.request(rid, c)
        for row in c.execute("SELECT id FROM experiments WHERE status='shadow'").fetchall():
            ex = self.experiment(row[0], c)
            # A stale experiment remains inspectable but cannot collect mixed-version evidence.
            if ex["base_id"] != self.policy(c)["id"] or ex["manifest"] != self.manifest():
                continue
            if obj['status'] == 'resolved' and c.execute(
                'SELECT 1 FROM observation_heads WHERE experiment_id=? AND request_id=?', (ex['id'], obj['id'])).fetchone():
                # Preserve the actual pre-decision prediction, including candidate AI evidence.
                continue
            candidate_evidence = self.candidate(c, obj, ex["policy"])
            snapshot = {"external_id": obj["external_id"], "version": obj["version"], "data": request_input(obj["data"]),
                        "evidence": deepcopy(candidate_evidence), "baseline_evidence": deepcopy(obj["evidence"]), "conflict": bool(obj["conflict"])}
            key = fingerprint([snapshot["data"], snapshot["evidence"], snapshot["baseline_evidence"], snapshot["conflict"]])
            baseline = assess(obj["data"], obj["evidence"], ex["baseline"], bool(obj["conflict"]))
            candidate = assess(obj["data"], candidate_evidence, ex["policy"], bool(obj["conflict"]))
            cohort = "backlog" if obj["id"] in ex["initial_ids"] else "prospective"
            c.execute("INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?,?,?,?,?)", (uid(), ex["id"], obj["id"], key,
                      dump(snapshot), dump(baseline), dump(candidate), cohort, now()))
            observation_id=c.execute("SELECT id FROM observations WHERE experiment_id=? AND request_id=? AND input_hash=?",(ex["id"],obj["id"],key)).fetchone()[0]
            c.execute("INSERT OR REPLACE INTO observation_heads VALUES(?,?,?)",(ex["id"],obj["id"],observation_id))

    def capture_experiment(self, eid):
        from .storage import Conflict
        with self.tx() as c:
            ex = self.experiment(eid, c)
            if ex["status"] != "shadow":
                raise Conflict("Only a running Shadow trial captures observations.")
            self.check_experiment_environment(ex, c)
            for row in c.execute("SELECT id FROM requests").fetchall():
                self.capture_shadow(c, row[0])
        return self.experiment_report(eid)

    def observation_list(self, eid, c, latest=True):
        result = []
        policy = self.experiment(eid, c)['policy']
        query = "SELECT rowid,* FROM observations WHERE experiment_id=? ORDER BY rowid"
        for row in c.execute(query, (eid,)):
            item = dict(row)
            for key in ("snapshot", "baseline", "candidate"):
                item[key] = json.loads(item[key])
            label = c.execute("SELECT data FROM adjudications WHERE observation_id=? ORDER BY seq DESC LIMIT 1", (item["id"],)).fetchone()
            item["label"] = json.loads(label[0]) if label else None
            shared = self.shared_observation_label(c, item, policy)
            if shared is not None:
                item['label'] = shared
            result.append(item)
        if latest:
            heads={r[0] for r in c.execute("SELECT observation_id FROM observation_heads WHERE experiment_id=?",(eid,))}
            result = [r for r in result if r["id"] in heads]
        return result


    def experiment_report(self, eid, c=None):
        if c is None:
            with self.connect() as db:
                return self.experiment_report(eid, db)
        ex = self.experiment(eid, c)
        observations = self.observation_list(eid, c)
        for observation in observations:
            observation['outcomes'] = [dict(r) for r in c.execute('SELECT type,note,created_at FROM outcomes WHERE request_id=?', (observation['request_id'],))]
        report = financial_report(observations, ex["settings"])
        blockers = []
        if ex["status"] != "shadow": blockers.append("This version is not running in Shadow.")
        if ex["base_id"] != self.policy(c)["id"]: blockers.append("The active baseline changed.")
        if ex["manifest"] != self.manifest(): blockers.append("The model, prompt or implementation changed.")
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(ex["started_at"])).total_seconds() / 3600 if ex["started_at"] else 0
        if age < ex["settings"]["min_shadow_hours"]: blockers.append("Minimum observation duration has not elapsed.")
        if report["candidate_auto"] < ex["settings"]["min_prospective_auto"]: blockers.append("Not enough prospective automatic proposals.")
        if report["reviewed_customer_groups"] < ex["settings"]["min_prospective_auto"]: blockers.append("Not enough independently reviewed customer groups.")
        if report["changed"] < ex["settings"]["min_changed_cases"]: blockers.append("Not enough prospective cases affected by the change.")
        if report["reviewed_auto"] != report["candidate_auto"]: blockers.append("Review every prospective automatic proposal; unknown assessments do not pass.")
        if report["critical"]: blockers.append("Critical violations were found.")
        if report["error_upper_95"] is None or report["error_upper_95"] * 10000 > ex["settings"]["max_error_bps"]:
            blockers.append("The 95% upper error estimate exceeds the risk allowance or is unknown.")
        if report["projected_loss_upper_cents"] is None or report["projected_loss_upper_cents"] > ex["settings"]["max_projected_loss_cents"]:
            blockers.append("Projected loss upper estimate exceeds the configured allowance or is unknown.")
        for o in observations:
            if o["cohort"] != "prospective" or o["candidate"]["action"] != "auto_approve": continue
            if o["candidate"]["proposed_amount_cents"] > ex["settings"]["max_single_cents"]:
                blockers.append("A proposed automatic refund exceeds the release single-payment cap.")
            evidence = o["snapshot"]["evidence"]
            if evidence.get("method") == "live":
                if evidence.get("model_manifest") != fingerprint(ex["manifest"].get("ai", {})):
                    blockers.append("AI evidence does not match the frozen model and prompt.")
            for criterion in ex["policy"]["criteria"]:
                actual = evidence.get("facts", {}).get("semantic." + criterion["id"], {}).get("value")
                checked = (o.get("label") or {}).get("semantic_checks", {}).get(criterion["id"])
                if checked not in ("yes", "no") or checked != actual:
                    blockers.append("New semantic criteria need matching independent yes/no assessments on automatic proposals.")
        report["shadow_hours"] = age
        from .decision_metrics import shadow_reports
        gate = {"passed": not blockers, "blockers": list(dict.fromkeys(blockers))}
        metrics = shadow_reports(observations, ex['baseline'], ex['policy'], ex['settings'],
            {'manifest':ex['manifest'], 'started_at':ex['started_at'], 'generated_at':datetime.now(timezone.utc).isoformat(),
             'synthetic_workspace':bool(self.state(c).get('demo_scenario')),
             'baseline_id':ex['base_id'], 'candidate_id':ex.get('source_policy_id'), 'gate':gate})
        additional = [
            ('Running in Shadow', ex['status']=='shadow', True, 'boolean'),
            ('Baseline unchanged', ex['base_id']==self.policy(c)['id'], True, 'boolean'),
            ('Model and implementation unchanged', ex['manifest']==self.manifest(), True, 'boolean'),
            ('Observation hours', round(age,2), ex['settings']['min_shadow_hours'], 'hours'),
            ('Prospective automatic proposals', report['candidate_auto'], ex['settings']['min_prospective_auto'], 'count'),
            ('Prospective changed routes', report['changed'], ex['settings']['min_changed_cases'], 'count'),
        ]
        metrics['prospective']['criteria'] += [{'label':label, 'actual':actual, 'required':required, 'unit':unit,
            'status':'pass' if actual>=required else 'fail', 'detail':'Frozen release requirement.'} for label,actual,required,unit in additional]
        metrics['prospective']['criteria'].append({'label':'Evidence identity and semantic checks', 'actual':
            not any('AI evidence' in b or 'semantic criteria' in b for b in blockers) if report['candidate_auto'] else None,
            'required':True, 'unit':'boolean', 'status':'unknown' if not report['candidate_auto'] else
            'fail' if any('AI evidence' in b or 'semantic criteria' in b for b in blockers) else 'pass',
            'detail':'Automatic live proposals must use evidence from the frozen model and prompt. Additional questions need matching independent assessments.'})
        return {"experiment": ex, "observations": observations, "financial": report,
                'stale_reasons':(["Current changed since these checks started."] if ex['base_id']!=self.policy(c)['id'] else [])+
                    (["The model, prompt or evaluation implementation changed."] if ex['manifest']!=self.manifest() else []),
                'decision_reports':metrics,
                "comparison": {"baseline": comparison_metrics(observations, 'baseline'),
                               "candidate": comparison_metrics(observations, 'candidate')},
                "gate": gate}

    def stop_experiment(self, eid, reason):
        from .storage import Conflict
        if not reason.strip(): raise ValueError("Give a reason for stopping this version.")
        with self.tx() as c:
            ex = self.experiment(eid, c)
            if ex["status"] not in ("draft", "backtested", "shadow"): raise Conflict("This version is already closed.")
            c.execute("UPDATE experiments SET status='stopped' WHERE id=?", (eid,))
            self.audit(c, eid, "experiment_stopped", {"reason": reason}, "manager")
        return self.experiment(eid)

    def promote_experiment(self, eid, reason):
        from .storage import Conflict, uid, now, dump
        if not reason.strip(): raise ValueError("Explain why this policy is ready for controlled activation.")
        with self.tx() as c:
            report = self.experiment_report(eid, c)
            if not report["gate"]["passed"]: raise Conflict("Release blocked: " + " ".join(report["gate"]["blockers"]))
            ex = report["experiment"]; p = ex["policy"]; pid = ex.get('source_policy_id') or uid()
            source=c.execute('SELECT status,data FROM policies WHERE id=?',(pid,)).fetchone() if ex.get('source_policy_id') else None
            if source and (source['status']!='draft' or validate_policy(json.loads(source['data']))[0]!=p):
                raise Conflict('Only the exact checked draft version can become active. Save a new version to restore an archived policy.')
            c.execute("UPDATE policies SET status='archived' WHERE status='active'")
            if source:c.execute("UPDATE policies SET status='active' WHERE id=?",(pid,))
            else:c.execute("INSERT INTO policies VALUES(?,?,?,?,?,?,?)", (pid, p["name"], dump(p), fingerprint(p), "active", ex["base_id"], now()))
            c.execute("UPDATE state SET value=? WHERE key='active_policy'", (pid,))
            # Activation enables this exact version's automatic local execution.
            c.execute("UPDATE state SET value='simulate' WHERE key='mode'")
            c.execute("UPDATE state SET value=CAST(value AS INTEGER)+1 WHERE key='epoch'")
            c.execute("INSERT INTO release_limits VALUES(?,?,?)", (pid, dump(ex["settings"]), now()))
            for row in c.execute("SELECT id FROM requests WHERE status='ready'").fetchall():
                obj = self.request(row[0], c); e = self.candidate(c, obj, p)
                ev = evaluate(obj["data"], e, p, bool(obj["conflict"]))
                c.execute("UPDATE requests SET evidence=?,evaluation=?,queue=?,version=version+1 WHERE id=?", (dump(e), dump(ev), ev["queue"], obj["id"]))
            c.execute("UPDATE experiments SET status='superseded' WHERE status='active'")
            c.execute("UPDATE experiments SET status='active',activated_policy_id=? WHERE id=?", (pid, eid))
            self.audit(c, pid, "policy_promoted", {"experiment_id": eid, "reason": reason, "financial": report["financial"], "settings": ex["settings"]}, "manager")
            return self.policy(c)

    def release_budget(self, c=None, policy_id=None):
        if c is None:
            with self.connect() as db: return self.release_budget(db,policy_id=policy_id)
        from .storage import now
        from .policy_management import _policy
        policy = _policy(c,policy_id) if policy_id else self.policy(c)
        pid = policy['id']
        row = c.execute("SELECT settings FROM release_limits WHERE policy_id=?", (pid,)).fetchone()
        settings = json.loads(row[0]) if row else ReleaseSettings().model_dump()
        settings.update(policy['execution_limits'])
        spent = c.execute("SELECT COALESCE(SUM(amount_cents),0),COUNT(*) FROM automation_spend WHERE policy_id=?", (pid,)).fetchone()
        day = c.execute("SELECT COALESCE(SUM(amount_cents),0) FROM automation_spend WHERE substr(created_at,1,10)=?", (now()[:10],)).fetchone()[0]
        return {"policy_id": pid, "settings": settings, "release_spent_cents": spent[0], "release_count": spent[1],
                "daily_spent_cents": day, "source": "approved_trial" if row else "policy_settings", "currency": "USD"}

    def check_release_budget(self, c, obj, amount):
        from .storage import now
        b = self.release_budget(c); s = b["settings"]
        released=c.execute("SELECT id FROM experiments WHERE activated_policy_id=?",(b["policy_id"],)).fetchone()
        if released and self.experiment(released[0],c)["manifest"]!=self.manifest():
            return "The released model or policy implementation changed; a new version must be checked"
        evidence=obj["evidence"]
        if getattr(self,'runtime_analysis_ready',None) and not self.runtime_analysis_ready(c,obj,self.policy(c)['data']):
            return 'Waiting for saved evidence analysis of the current request fields'
        if not evidence.get('complete'):return 'Complete evidence analysis is required before automatic payment'
        if type(amount) is not int or amount<=0:return 'A valid refund amount is required before automatic payment'
        if evidence.get("method")=="live":
            if getattr(self,"runtime_manifest",None) and evidence.get("model_manifest")!=fingerprint(self.runtime_manifest().get("ai",{})):
                return "Stored AI evidence belongs to a different model or prompt"
        customer = c.execute("SELECT COALESCE(SUM(amount_cents),0) FROM automation_spend WHERE customer_id=? AND substr(created_at,1,10)=?",
                             (obj["data"]["customer_id"], now()[:10])).fetchone()[0]
        checks = [(amount > s["max_single_cents"], "Single-payment cap exceeded"),
                  (b["daily_spent_cents"] + amount > s["daily_cents"], "Daily automatic-refund budget reached"),
                  (customer + amount > s["customer_daily_cents"], "Customer daily budget reached"),
                  (b["release_spent_cents"] + amount > s["release_cents"], "Release refund budget reached"),
                  (b["release_count"] + 1 > s["release_count"], "Release operation limit reached")]
        return next((message for failed, message in checks if failed), None)

    def mine_rules(self, hourly_cents=3000, adverse_bps=500, min_support=5, base_id=None):
        from .storage import uid, now, dump
        with self.tx() as c:
            rows = [json.loads(r[0]) for r in c.execute("SELECT data FROM history")]
            active = self.policy(c)
            base_id = base_id or active['id']
            base = c.execute('SELECT data FROM policies WHERE id=?', (base_id,)).fetchone()
            if not base: raise ValueError('The selected policy version no longer exists.')
            engine = getattr(self, 'history_evidence', None)
            evidence_provider = (lambda row, criteria: engine.evidence(row, criteria, c)) if engine else None
            report = discover(rows, json.loads(base[0]), hourly_cents, adverse_bps, min_support,
                              evidence_provider=evidence_provider)
            rid = uid(); report['id'] = rid; report['base_id'] = base_id; report['active_id'] = active['id']
            report['base_hash'] = fingerprint(json.loads(base[0]))
            c.execute("INSERT INTO mining_runs VALUES(?,?,?)", (rid, dump(report), now()))
            self.audit(c, rid, "rules_discovered", {"candidates": len(report["candidates"]), "data_hash": report["data_hash"]}, "manager")
            return report

    def latest_mining(self):
        with self.connect() as c:
            row = c.execute("SELECT report FROM mining_runs ORDER BY created_at DESC LIMIT 1").fetchone()
            return json.loads(row[0]) if row else None
