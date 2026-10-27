"""Shared reviewer references and paired comparisons on the operational request pool."""
from copy import deepcopy
import json
from .domain import fingerprint

SHARED_SHADOW_SCHEMA = """
CREATE TABLE IF NOT EXISTS shared_reviews(
 id TEXT PRIMARY KEY,request_id TEXT NOT NULL,input_hash TEXT NOT NULL,
 snapshot TEXT NOT NULL,data TEXT NOT NULL,created_at TEXT NOT NULL,
 FOREIGN KEY(request_id) REFERENCES requests(id));
CREATE INDEX IF NOT EXISTS shared_review_input ON shared_reviews(request_id,input_hash,created_at);
INSERT OR IGNORE INTO schema_version VALUES(3);
"""


def shared_input_hash(snapshot):
    return fingerprint([snapshot['data'], snapshot.get('baseline_evidence', snapshot.get('evidence')),
                        bool(snapshot['conflict'])])


def comparison_metrics(observations, side):
    """Descriptive comparisons to human decisions, not causal loss or accuracy claims."""
    auto = [o for o in observations if o[side]['action'] == 'auto_approve']
    reviewed = [o for o in observations if o.get('label') and o['label']['allowed_cents'] is not None]
    checked_auto = [o for o in auto if o in reviewed]
    amount = lambda o: o[side].get('proposed_amount_cents') or 0
    over = [max(0, amount(o) - o['label']['allowed_cents']) for o in checked_auto]
    routes = {'review': 0, 'fraud': 0, 'auto_approve': 0}
    for o in observations:
        ev = o[side]
        routes['auto_approve' if ev['action'] == 'auto_approve' else 'fraud' if ev.get('queue') == 'fraud' else 'review'] += 1
    exact = sum(amount(o) == o['label']['allowed_cents'] for o in checked_auto)
    return {'total': len(observations), 'reviewed': len(reviewed), 'routes': routes,
            'auto_count': len(auto), 'auto_rate': len(auto) / len(observations) if observations else None,
            'payout_cents': sum(amount(o) for o in auto), 'auto_reviewed': len(checked_auto),
            'auto_agreed': exact, 'agreement_rate': exact / len(checked_auto) if checked_auto else None,
            'overpayment_cents': sum(over), 'overpayment_cases': sum(x > 0 for x in over),
            'unreviewed_auto': len(auto) - len(checked_auto),
            'unreviewed_cents': sum(amount(o) for o in auto if o not in checked_auto),
            'manual_full_approvals': sum(o[side]['action'] != 'auto_approve' and
                o['label']['allowed_cents'] == o['snapshot']['data'].get('amount_cents') for o in reviewed)}


class SharedShadowStore:
    def record_shared_review(self, c, obj, label, created_at=None):
        from .storage import dump, now, uid
        from .experiments import request_input
        snapshot = {'data': request_input(obj['data']), 'baseline_evidence': deepcopy(obj['evidence']),
                    'conflict': bool(obj['conflict'])}
        ref = uid()
        c.execute('INSERT INTO shared_reviews VALUES(?,?,?,?,?,?)',
                  (ref, obj['id'], shared_input_hash(snapshot), dump(snapshot), dump(label), created_at or now()))
        return ref

    def migrate_decision_references(self, c):
        # Only audit-confirmed human decisions. Automatic payouts never label themselves.
        rows = c.execute("""SELECT d.* FROM decisions d WHERE EXISTS(
            SELECT 1 FROM audit a WHERE a.object_id=d.request_id AND a.type='decision_recorded'
            AND json_extract(a.detail,'$.automatic')=0)
            AND NOT EXISTS(SELECT 1 FROM shared_reviews s WHERE json_extract(s.data,'$.decision_id')=d.id)""").fetchall()
        for row in rows:
            obj = self.request(row['request_id'], c)
            if obj['conflict']:
                continue
            self.record_shared_review(c, obj, {'allowed_cents': 0 if row['action'] == 'rejected' else row['amount_cents'],
                'action': row['action'], 'critical': False, 'note': row['reason'], 'actor': row['actor'], 'minutes': 0,
                'source': 'human_decision', 'decision_id': row['id'], 'semantic_checks': {}}, row['created_at'])

    def record_decision_reference(self, c, obj, decision_id, action, amount, reason, actor):
        return self.record_shared_review(c, obj, {
            'allowed_cents': 0 if action == 'rejected' else amount, 'action': action,
            'critical': False, 'note': reason, 'actor': actor, 'minutes': 0,
            'source': 'human_decision', 'decision_id': decision_id, 'semantic_checks': {}})

    def shared_observation_label(self, c, observation, policy):
        row = c.execute('SELECT * FROM shared_reviews WHERE request_id=? AND input_hash=? ORDER BY rowid DESC LIMIT 1',
                        (observation['request_id'], shared_input_hash(observation['snapshot']))).fetchone()
        if not row:
            return None
        label = json.loads(row['data'])
        label.update(reference_id=row['id'], reviewed_at=row['created_at'],
                     captured_before_review=observation['created_at'] <= row['created_at'])
        scoped = label.pop('scoped_semantic_checks', {})
        label['semantic_checks'] = {q['id']: scoped[fingerprint(q)] for q in policy['criteria']
                                    if fingerprint(q) in scoped}
        return label

    def shadow_dashboard(self, policy_ids=None):
        """Every comparable version uses the same intersection, with explicit exclusions."""
        from .experiments import assess, request_input
        from .decision_metrics import shadow_reports
        from copy import deepcopy
        with self.connect() as c:
            active = self.policy(c)
            requests = [self.request(r[0], c) for r in c.execute('SELECT id FROM requests ORDER BY created_at,id').fetchall()]
            selected = set(policy_ids) if policy_ids is not None else None
            reports = []
            for row in c.execute("SELECT id FROM experiments WHERE status='shadow' ORDER BY created_at DESC").fetchall():
                ex = self.experiment(row[0], c)
                # Selection must happen before intersecting request coverage.
                if selected is not None and (ex['source_policy_id'] not in selected or ex['status'] != 'shadow'):
                    continue
                reports.append(self.experiment_report(row[0], c))
            versions = []
            maps = {}
            common = {r['id'] for r in requests}
            for report in reports:
                ex = report['experiment']
                stale = ex['manifest'] != self.manifest() or ex['base_id'] != active['id']
                by_request = {o['request_id']: o for o in report['observations']}
                # Never compare a version's stale input with the current request revision.
                fresh = {r['id'] for r in requests if r['id'] in by_request and shared_input_hash(
                    {'data': request_input(r['data']), 'baseline_evidence': r['evidence'], 'conflict': bool(r['conflict'])}) ==
                    shared_input_hash(by_request[r['id']]['snapshot'])}
                if not stale:
                    common &= fresh
                    maps[ex['id']] = by_request
                versions.append({'id': ex['id'], 'policy_id': ex['source_policy_id'], 'name': ex['policy']['name'],
                                 'status': ex['status'], 'stale': stale, 'observed': len(fresh),
                                 'prospective': report['financial']['prospective'],
                                 'gate': report['gate'], 'started_at': ex['started_at']})
            base_observations = []
            rows = []
            for obj in requests:
                if obj['id'] not in common:
                    continue
                snap = {'data': request_input(obj['data']), 'baseline_evidence': obj['evidence'], 'conflict': bool(obj['conflict'])}
                label = self.shared_observation_label(c, {'request_id': obj['id'], 'snapshot': snap,
                    'created_at': obj['created_at']}, active['data'])
                baseline = assess(obj['data'], obj['evidence'], active['data'], bool(obj['conflict']))
                observation = {'snapshot': snap, 'baseline': baseline, 'label': label}
                base_observations.append(observation)
                rows.append({'request_id': obj['id'], 'external_id': obj['external_id'],
                             'amount_cents': obj['data'].get('amount_cents'), 'baseline': baseline,
                             'label': label, 'work_status': obj['status'],
                             'candidates': {eid: values[obj['id']]['candidate'] for eid, values in maps.items()}})
            for version in versions:
                version['metrics'] = comparison_metrics([o for rid, o in maps.get(version['id'], {}).items()
                                                         if rid in common], 'candidate') if not version['stale'] else None
            current_metrics = None
            # All report columns use the same request IDs, cohort and eligible human references.
            # A request is prospective only if it arrived after EVERY selected version started.
            common_ids = sorted(common) if maps else []
            cohort = {rid:'prospective' if all(m[rid]['cohort']=='prospective' for m in maps.values()) else 'backlog' for rid in common_ids}
            for version in versions:
                if version['stale']: continue
                source = next(r for r in reports if r['experiment']['id']==version['id'])
                ex = source['experiment']; observations = []
                for rid in common_ids:
                    o = deepcopy(maps[version['id']][rid]); o['cohort'] = cohort[rid]
                    if o.get('label'):
                        o['label']['captured_before_review'] = all(bool(m[rid].get('label')) and m[rid]['label'].get('captured_before_review',False) for m in maps.values())
                    observations.append(o)
                meta = {'comparison_only':True,'shared_requests':len(common_ids),'data_fingerprint':fingerprint([(o['request_id'],shared_input_hash(o['snapshot'])) for o in observations]),
                        'synthetic_workspace':bool(self.state(c).get('demo_scenario')),
                        'manifest':ex['manifest']}
                version['decision_reports'] = shadow_reports(observations,ex['baseline'],ex['policy'],ex['settings'],meta)
                if current_metrics is None:
                    current_obs = deepcopy(observations)
                    for o in current_obs:
                        o['candidate']=o['baseline']; o['snapshot']['evidence']=o['snapshot']['baseline_evidence']
                    current_metrics=shadow_reports(current_obs,active['data'],active['data'],ex['settings'],meta)
            return {'current': {'id': active['id'], 'name': active['name'], 'version': active['version'],
                                'metrics': comparison_metrics(base_observations, 'baseline')},
                    'versions': versions, 'requests': rows, 'current_decision_reports':current_metrics, 'total_requests': len(requests),
                    'compared_requests': len(common), 'excluded_requests': len(requests) - len(common),
                    'reviewed_requests': sum(o['label'] is not None and o['label']['allowed_cents'] is not None for o in base_observations),
                    'note': 'One shared request pool and one human decision per request. Human decisions are reference judgments, not proven financial outcomes. Backlog comparisons do not qualify a release.'}

    def refresh_changed_checks(self):
        """Renew unreleased checks automatically; never activate or restart Shadow."""
        from .storage import Conflict
        with self.connect() as c:
            current=self.policy(c)['id'];manifest=self.manifest()
            stale=[row['id'] for row in c.execute("SELECT id,base_id,manifest FROM experiments WHERE status IN ('draft','backtested','shadow')")
                   if row['base_id']!=current or json.loads(row['manifest'])!=manifest]
        for eid in stale:
            try:self.recheck_experiment(eid,automatic=True)
            except Conflict:pass  # Another transaction may have already renewed it.

    def recheck_experiment(self, eid, automatic=False):
        """Retain old evidence; start fresh checks of the same immutable saved version."""
        from .storage import Conflict, dump, now, uid
        with self.tx() as c:
            old = self.experiment(eid, c)
            if old['status'] not in ('draft', 'backtested', 'shadow'):
                raise Conflict('Only an unreleased version can restart its checks.')
            base = self.policy(c); fresh = uid()
            c.execute('INSERT INTO experiments VALUES(?,?,?,?,?,?,?,NULL,NULL,?,NULL,NULL)',
                      (fresh, dump(old['policy']), base['id'], dump(base['data']), dump(self.manifest()),
                       dump(old['settings']), 'draft', now()))
            if old['source_policy_id']:
                c.execute('INSERT INTO trial_sources VALUES(?,?)', (fresh, old['source_policy_id']))
            c.execute("UPDATE experiments SET status='superseded' WHERE id=?", (eid,))
            self.audit(c, fresh, 'checks_restarted', {'previous_checks': eid, 'policy_id': old['source_policy_id'],
                       'automatic':automatic}, 'system' if automatic else 'manager')
        history=getattr(self,'history_evidence',None)
        if history:history.request_replay(fresh)
        else:self.backtest_experiment(fresh)
        return self.experiment_report(fresh)
