"""Role-specific workflows and traceable, history-derived policy drafts."""
import json
from collections import Counter
from datetime import datetime, timezone
from .domain import policy_content, initial_policy, fingerprint, validate_policy
from .mining import discover

WORKSPACE_SCHEMA = """
CREATE TABLE IF NOT EXISTS draft_sources(policy_id TEXT PRIMARY KEY,report TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decision_context(decision_id TEXT PRIMARY KEY,evaluation TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reopened(request_id TEXT PRIMARY KEY,note TEXT NOT NULL,closed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS trial_sources(experiment_id TEXT PRIMARY KEY,policy_id TEXT NOT NULL);
"""

class WorkspaceStore:
    def setup_status(self):
        with self.connect() as c:
            return {"history_count": c.execute("SELECT COUNT(*) FROM history").fetchone()[0],
                    "qualified": self.release_budget(c)["source"] == "approved_trial",
                    "draft_count": c.execute("SELECT COUNT(*) FROM policies WHERE status='draft'").fetchone()[0],
                    "active_policy": self.policy(c)}

    def save_draft(self, policy, report=None, parent_id=None, from_scratch=False):
        p, issues = validate_policy(policy)
        if issues: raise ValueError("; ".join(issues))
        if from_scratch and parent_id: raise ValueError('A policy created from scratch cannot also have a base version.')
        with self.tx() as c:
            parent_id=None if from_scratch else parent_id or self.policy(c)['id']
            return self._insert_draft(c,p,report,parent_id)

    def _insert_draft(self,c,p,report,parent_id):
        from .storage import dump, uid, now
        if parent_id is not None and not c.execute('SELECT 1 FROM policies WHERE id=?',(parent_id,)).fetchone():raise ValueError('The parent policy version no longer exists.')
        inherited = c.execute('SELECT report FROM draft_sources WHERE policy_id=?',(parent_id,)).fetchone()
        source = 'history' if report else 'manager'
        if report is None and inherited: report=json.loads(inherited[0])
        pid=uid();created=now()
        c.execute("INSERT INTO policies VALUES(?,?,?,?,?,?,?)", (pid,p['name'],dump(p),fingerprint(p),'draft',parent_id,created))
        if report: c.execute('INSERT INTO draft_sources VALUES(?,?)',(pid,dump(report)))
        self.audit(c,pid,'draft_created',{'source':source},'manager')
        number=c.execute('SELECT rowid FROM policies WHERE id=?',(pid,)).fetchone()[0]
        return {"id":pid,"name":p['name'],"data":p,"source":report,"status":"draft","parent_id":parent_id,"created_at":created,"version":number}

    def update_draft(self, pid, policy, expected_policy):
        p, issues = validate_policy(policy)
        if issues: raise ValueError('; '.join(issues))
        with self.tx() as c:
            return self._update_draft(c, pid, p, expected_policy)

    def _update_draft(self, c, pid, policy, expected_policy, report=None):
        from .storage import Conflict, dump
        row = c.execute('SELECT rowid AS version,* FROM policies WHERE id=?', (pid,)).fetchone()
        if not row: raise KeyError('Policy version not found')
        checks = c.execute('SELECT e.* FROM experiments e JOIN trial_sources s ON s.experiment_id=e.id WHERE s.policy_id=?', (pid,)).fetchall()
        if row['status'] != 'draft' or pid == self.policy(c)['id'] or any(e['status'] != 'draft' for e in checks):
            raise Conflict('This version is locked because its checks have started. Create a new version from Policies to change its rules.')
        before = policy_content(json.loads(row['data']))
        if expected_policy is None or fingerprint(before) != fingerprint(expected_policy):
            raise Conflict('This draft changed in another editor. Reopen the version before saving. Your local changes are still in this browser.')
        c.execute('UPDATE policies SET name=?,data=?,hash=? WHERE id=?', (policy['name'],dump(policy),fingerprint(policy),pid))
        # An unrun check has no observations/results yet. Keep it aligned with the draft.
        for e in checks:
            settings=json.loads(e['settings'])
            if policy.get('execution_limits') is not None: settings.update(policy['execution_limits'])
            c.execute('UPDATE experiments SET policy=?,settings=? WHERE id=?', (dump(policy),dump(settings),e['id']))
        if report:
            if report['base_id'] != pid: raise ValueError('These candidates belong to a different policy version.')
            old = c.execute('SELECT report FROM draft_sources WHERE policy_id=?', (pid,)).fetchone()
            if old:
                previous = json.loads(old[0])
                new_ids = {r['rule_id'] for r in report.get('rules',[])}
                report = {**report, 'rules':[r for r in previous.get('rules',[]) if r['rule_id'] not in new_ids]+report.get('rules',[])}
            c.execute('INSERT OR REPLACE INTO draft_sources VALUES(?,?)', (pid,dump(report)))
        self.audit(c,pid,'draft_updated',{'before_hash':fingerprint(before),'after_hash':fingerprint(policy)},'manager')
        return {**dict(row),'name':policy['name'],'data':policy,'hash':fingerprint(policy)}

    def draft_from_candidates(self,run_id,candidate_ids,policy=None,target_id=None,expected_policy=None):
        from .mining import covered_by
        from .storage import Conflict
        from copy import deepcopy
        with self.tx() as c:
            row=c.execute('SELECT report FROM mining_runs WHERE id=?',(run_id,)).fetchone()
            if not row: raise ValueError('Discovery report not found.')
            report=json.loads(row[0])
            if report.get('active_id') != self.policy(c)['id']:
                raise Conflict('Current policy changed. Discover candidates again before creating a draft.')
            history=[json.loads(r[0]) for r in c.execute('SELECT data FROM history')]
            valid=sorted([r for r in history if not r.get('errors')],key=lambda r:(r['requested_at'],r['request_id']))
            if fingerprint(valid) != report['data_hash']:
                raise Conflict('History changed. Discover candidates again before creating a draft.')
            candidates={x['id']:x for x in report['candidates']}
            if len(set(candidate_ids)) != len(candidate_ids) or any(x not in candidates for x in candidate_ids):
                raise ValueError('Select distinct candidates from this discovery report.')
            base=json.loads(c.execute('SELECT data FROM policies WHERE id=?',(report['base_id'],)).fetchone()[0])
            if report.get('base_hash') and report['base_hash'] != fingerprint(base):
                raise Conflict('This draft changed after discovery. Generate fresh candidates before saving these suggestions.')
            selected=[candidates[x] for x in candidate_ids]
            if policy is not None:
                final_ids={r['id'] for r in policy['rules']}
                if any(item['rule']['id'] not in final_ids for item in selected):
                    raise ValueError('Selected candidates must be included in the version being saved.')
            priority=min([r['priority'] for r in base['rules'] if r['enabled']] or [1000])-1
            if policy is None and priority-len(selected)+1 < 0: raise ValueError('Not enough priority space. Edit rule priorities first.')
            provenance=[]
            for i,item in enumerate(selected):
                rule=deepcopy(item['rule'])
                if policy is None and any(covered_by(rule,old) for old in base['rules']):
                    raise ValueError('A selected rule is already covered by this policy or an earlier selection. Choose complementary candidates.')
                rule['priority']=priority-i;base['rules'].append(rule)
                provenance.append({'rule_id':rule['id'],'source':'history search','support':item['training']['support'],
                    'example_ids':item['support_ids'][:12],'unknown_outcomes':item['training']['unknown_outcomes'],'exceptions':item.get('exception_ids',[]), 'discovery':item})
            base.update(name=base['name']+' · proposed changes',automation_enabled=True)
            p,issues=validate_policy(policy if policy is not None else base)
            if issues: raise ValueError('; '.join(issues))
            source={**report,'candidates':selected,'rules':provenance,'input_rows':len(history),'selected_candidate_ids':candidate_ids,
                    'provenance_note':'Evidence describes the original discovered candidates. Later edits require a fresh backtest.'}
            if target_id:
                return self._update_draft(c,target_id,p,expected_policy,source)
            return self._insert_draft(c,p,source,report['base_id'])

    def generate_initial(self, hourly_cents=3000, adverse_bps=500, min_support=5):
        from .domain import compare, pending_evidence
        with self.connect() as c: rows=[json.loads(r[0]) for r in c.execute("SELECT data FROM history")]
        if not rows: raise ValueError("Import historical requests before generating the first policy.")
        # The business notes supply mandatory restrictions, not the undefined 'small/good' thresholds.
        base=initial_policy()
        base.update(name="History-derived starting policy",automation_enabled=True)
        result=discover(rows,base,hourly_cents,adverse_bps,min_support)
        selected=[]; reasons=set()
        for candidate in result["candidates"]:
            reason=candidate["rule"]["conditions"][0]["value"]
            if reason in reasons: continue
            reasons.add(reason)
            rule=dict(candidate["rule"]);rule["priority"]=500-len(selected)
            base["rules"].append(rule)
            selected.append({k:candidate[k] for k in ("id","rule","training","later_diagnostic","support_ids","scenario_net_cents")})
        # Each rule has inspectable support and exceptions; these are observations, never labels.
        provenance=[]
        for rule in base["rules"]:
            matched=[]
            for r in rows:
                vals=[compare(cond,r,pending_evidence(r)["facts"]) for cond in rule["conditions"]]
                if all(v is True for v in vals): matched.append(r)
            mined=next((x for x in selected if x["rule"]["id"]==rule["id"]),None)
            provenance.append({"rule_id":rule["id"],"source":"history search" if mined else "assignment example" if rule["id"]=="amount-limit" else "policy_notes.csv",
                "support":len(matched),"example_ids":[r["request_id"] for r in matched[:12]],
                "exceptions":[r["request_id"] for r in matched if r["decision"] not in ("approved","auto_approved") or "chargeback" in r["outcome_note"].lower()],
                "unknown_outcomes":sum(not r["outcome_note"] for r in matched),"discovery":mined})
        report={**result,"candidates":selected,"rules":provenance,"input_rows":len(rows),
                "mandatory_constraints":["14-day changed-mind window","Photo above $50 for damage","Delivery proof requires investigation","Fraud-team confirmation for stolen card","Partial-refund judgment remains human"],
                "baseline":{"decisions":dict(Counter(r["decision"] for r in rows)),"already_auto":sum(r["decided_by"]=="auto" for r in rows),"unknown_outcomes":sum(not r["outcome_note"] for r in rows)}}
        return self.save_draft(base,report)

    def draft_source(self,pid):
        with self.connect() as c:
            row=c.execute("SELECT report FROM draft_sources WHERE policy_id=?",(pid,)).fetchone()
            return json.loads(row[0]) if row else None

    def customer_history(self,rid):
        obj=self.request(rid);customer=obj["data"]["customer_id"]
        with self.connect() as c:
            history=[json.loads(r[0]) for r in c.execute("SELECT data FROM history WHERE json_extract(data,'$.customer_id')=?",(customer,))]
            current=[self.request(r[0],c) for r in c.execute("SELECT id FROM requests WHERE json_extract(data,'$.customer_id')=? AND id!=?",(customer,obj["id"]))]
        return {"customer_id":customer,"historical":history,"current":current,
                "caution":"Prior requests are context, not proof of abuse. No order identifier is available to establish cross-request duplicates."}

    def reopen(self,rid,version,note,close=False):
        from .storage import Conflict
        if not note.strip(): raise ValueError("Record the reason for the follow-up review.")
        with self.tx() as c:
            obj=self.request(rid,c);self.check_version(obj,version)
            if not obj["decision"]: raise Conflict("Only a decided request can be reopened for follow-up.")
            c.execute("INSERT INTO reopened VALUES(?,?,?) ON CONFLICT(request_id) DO UPDATE SET note=excluded.note,closed=excluded.closed",(obj["id"],note,int(close)))
            c.execute("UPDATE requests SET version=version+1 WHERE id=?",(obj["id"],))
            self.audit(c,obj["id"],"follow_up_closed" if close else "reopened_for_follow_up",{"note":note,"original_payment_locked":True},"reviewer")
            return self.request(obj["id"],c)

    def feedback(self):
        """Observed mature cohorts; no unobserved result is called a success."""
        with self.connect() as c:
            rows=c.execute("SELECT d.*,x.evaluation FROM decisions d LEFT JOIN decision_context x ON x.decision_id=d.id").fetchall()
            groups={}
            for row in rows:
                ev=json.loads(row["evaluation"]) if row["evaluation"] else {}
                key=(row["policy_id"],ev.get("rule_id") or ev.get("reason_code") or "legacy-unknown")
                g=groups.setdefault(key,{"policy_id":key[0],"rule_id":key[1],"decisions":0,"overrides":0,"mature":0,"unknown_outcomes":0,"adverse":0,"paid_cents":0})
                g["decisions"]+=1;g["paid_cents"]+=row["amount_cents"] or 0
                if ev.get("action")=="auto_approve" and row["action"]!="approved":g["overrides"]+=1
                age=(datetime.now(timezone.utc)-datetime.fromisoformat(row["created_at"])).days
                outcomes=c.execute("SELECT type FROM outcomes WHERE request_id=?",(row["request_id"],)).fetchall()
                g["mature"]+=int(age>=30)
                g["unknown_outcomes"]+=int(not outcomes)
                g["adverse"]+=int(any(o[0] in ("chargeback","audit_fail") for o in outcomes))
            return {"groups":list(groups.values()),"maturity_days":30,"caution":"30 days is an explicit monitoring assumption, not a guaranteed chargeback horizon. Missing outcomes remain unknown. Overrides measure disagreement with automatic recommendations, not model accuracy."}
