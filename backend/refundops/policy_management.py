"""Numbered policy library, paired comparisons and guarded rollback.

Exploration never qualifies a release. Rollback restores an existing identity and
preserves financial limits, decisions and spend. Current processes eligible approvals automatically.
"""
import json
from .domain import policy_content, evaluate, fingerprint, pending_evidence, validate_policy
from .experiments import assess, decision_signature, request_input
from .storage import Conflict, dump
from .financial import policy_execution_limits


def _policy(c, pid):
    row = c.execute('SELECT rowid AS version,* FROM policies WHERE id=?', (pid,)).fetchone()
    if not row:
        raise KeyError('Policy version not found')
    data=policy_content(json.loads(row['data']))
    return {**dict(row), 'data':data, 'execution_limits':policy_execution_limits(c,pid,data)}


def _checks(store, c, pid, released=False):
    if released:
        row = c.execute('SELECT id FROM experiments WHERE activated_policy_id=? ORDER BY rowid DESC LIMIT 1', (pid,)).fetchone()
    else:
        row = c.execute("""SELECT e.id FROM experiments e LEFT JOIN trial_sources s ON s.experiment_id=e.id
            WHERE (s.policy_id=? OR e.activated_policy_id=?) AND e.status!='superseded'
            ORDER BY e.rowid DESC LIMIT 1""", (pid,pid)).fetchone()
    return store.experiment(row[0],c) if row else None


def _qualification(store, c, policy):
    warnings = []
    release = _checks(store,c,policy['id'],released=True)
    if not c.execute('SELECT 1 FROM release_limits WHERE policy_id=?', (policy['id'],)).fetchone() or not release:
        warnings.append('This version has no recorded release checks. Current still applies its saved rules and payment checks.')
    if release:
        if release['manifest'] != store.manifest():
            warnings.append('The model, prompt or policy implementation changed since release. A new version must be qualified before automatic execution.')
        if validate_policy(policy['data'])[0] != release['policy']:
            warnings.append('The saved policy no longer matches its recorded release checks.')
    return {'passed':not warnings, 'warnings':warnings}


def _selection(store,c,policy_ids):
    if not isinstance(policy_ids,(list,tuple)) or any(not isinstance(pid,str) or not pid for pid in policy_ids):
        raise ValueError('Select saved policy version IDs.')
    unique = list(dict.fromkeys(policy_ids))
    active = store.policy(c)
    candidates = [pid for pid in unique if pid != active['id']]
    if len(candidates) > 5:
        raise ValueError('Compare at most five saved versions with Current.')
    return active, [_policy(c,pid) for pid in candidates]


def policy_library(store):
    with store.connect() as c:
        c.execute('BEGIN')
        current = store.policy(c)
        versions = []
        for row in c.execute('SELECT id FROM policies ORDER BY rowid DESC').fetchall():
            p = _policy(c,row[0]); checks = _checks(store,c,p['id'])
            stage = 'current' if p['id']==current['id'] else 'archived' if p['status']=='archived' else 'shadow' if checks and checks['status']=='shadow' else 'stopped' if checks and checks['status']=='stopped' else 'backtested' if checks and checks['status']=='backtested' else 'draft'
            qualification = _qualification(store,c,p)
            if stage == 'shadow':
                readiness = store.experiment_report(checks['id'],c)['gate']
            elif stage == 'current':
                readiness = {'passed':qualification['passed'],'blockers':qualification['warnings']}
            else:
                readiness = {'passed':False,'blockers':['Archived versions can be restored through a reviewed rollback.' if stage=='archived' else 'Run backtest and prospective Shadow before activation.']}
            versions.append({**p,'stage':stage,'checks_id':checks['id'] if checks else None,
                             'checks_status':checks['status'] if checks else None,'readiness':readiness,
                             'stale':bool(stage in ('backtested','shadow') and (checks['base_id']!=current['id'] or checks['manifest']!=store.manifest())),
                             'qualification':qualification,'can_rollback':p['status']=='archived'})
        numbers = {p['id']:p['version'] for p in versions}
        history = []
        for row in c.execute("SELECT * FROM audit WHERE type IN ('policy_promoted','policy_rolled_back') ORDER BY id DESC LIMIT 100").fetchall():
            detail = json.loads(row['detail']); to_id = detail.get('to_id',row['object_id'])
            checks_id = detail.get('experiment_id')
            release = store.experiment(checks_id,c) if checks_id else None
            from_id = detail.get('from_id') or (release['base_id'] if release else None)
            history.append({'id':row['id'],'type':row['type'],'created_at':row['created_at'],
                            'from_id':from_id,'to_id':to_id,'from_version':numbers.get(from_id),
                            'to_version':numbers.get(to_id),'reason':detail.get('reason',''),
                            'checks_id':checks_id,'preview_id':detail.get('preview_id')})
        return {'current_id':current['id'],'versions':versions,'history':history}


def _summary(evaluations, baseline):
    routes = {'review':0,'fraud':0,'auto_approve':0}
    for ev in evaluations:
        route = 'auto_approve' if ev['action']=='auto_approve' else 'fraud' if ev.get('queue')=='fraud' else 'review'
        routes[route] += 1
    total = len(evaluations)
    return {'total':total,'routes':routes,'auto_count':routes['auto_approve'],
            'auto_rate':routes['auto_approve']/total if total else None,
            'payout_cents':sum(ev.get('proposed_amount_cents') or 0 for ev in evaluations if ev['action']=='auto_approve'),
            'changed_count':sum(decision_signature(ev)!=decision_signature(old) for ev,old in zip(evaluations,baseline))}


def compare_backtest(store,policy_ids):
    from .decision_metrics import historical_rows, build_report
    with store.connect() as c:
        c.execute('BEGIN')
        active, policies = _selection(store,c,policy_ids)
        history = [json.loads(row[0]) for row in c.execute('SELECT data FROM history ORDER BY id')]
        engine=getattr(store,'history_evidence',None)
        analysis=engine.summary([p['data']['criteria'] for p in [active,*policies]],history) if engine else None
        if analysis and not analysis['ready']:
            return {'mode':'backtest','preparing':True,'analysis':analysis,'current':{'policy_id':active['id'],'version':active['version'],'summary':_summary([],[])},
                    'versions':[{'policy_id':p['id'],'version':p['version'],'available':False,'reason':'Full historical extraction is in progress.'} for p in policies],
                    'requests':[],'compared_requests':0,'total_requests':len(history),'excluded_requests':len(history),'reviewed_requests':0}
        rows = []
        for data in history:
            inputs = request_input(data)
            evidence = engine.evidence(inputs,active['data']['criteria'],c) if engine else pending_evidence(inputs)
            rows.append({'request_id':data['request_id'],'external_id':data['request_id'],
                         'amount_cents':data.get('amount_cents'),'current':assess(inputs,evidence,active['data']),
                         'candidates':{p['id']:assess(inputs,engine.evidence(inputs,p['data']['criteria'],c) if engine else evidence,p['data']) for p in policies},
                         'historical_decision':data.get('decision'),'outcome_note':data.get('outcome_note') or None})
        baseline = [row['current'] for row in rows]
        def metrics(p):
            settings = {**store.cost_assumptions(c), **policy_execution_limits(c,p['id'],p['data'])}
            provider=(lambda data,criteria:engine.evidence(data,criteria,c)) if engine else None
            return build_report(historical_rows(history,active['data'],p['data'],provider),active['data'],p['data'],settings,mode='backtest',
                metadata={'scope':'history','comparison_only':True,'data_fingerprint':fingerprint(history),
                          'evidence_mode':'Full live extraction' if engine else 'Awaiting model extraction','manifest':store.manifest()})
        return {'mode':'backtest','current':{'policy_id':active['id'],'version':active['version'],'summary':_summary(baseline,baseline)},
                'versions':[{'policy_id':p['id'],'version':p['version'],'checks_id':None,'available':True,
                             'summary':_summary([row['candidates'][p['id']] for row in rows],baseline), 'decision_report':metrics(p)} for p in policies],
                'current_decision_report':metrics(active), 'analysis':analysis,
                'requests':rows,'data_fingerprint':fingerprint(history),'compared_requests':len(rows),
                'total_requests':len(rows),'excluded_requests':0,'reviewed_requests':0,
                'limitations':['Every version uses the same historical rows and persisted model extraction for its exact question set.' if engine else 'Every version uses the same historical rows. Missing model extraction stays incomplete.',
                               'Historical decisions and outcomes are display context only and never enter evaluation.',
                               'Unknown outcomes remain unknown. This replay does not prove correctness, avoided losses or release readiness.',
                               'This comparison does not save or advance version checks.']}


def compare_shadow(store,policy_ids):
    with store.connect() as c:
        active, policies = _selection(store,c,policy_ids)
        checks = {p['id']:_checks(store,c,p['id']) for p in policies}
    dashboard = store.shadow_dashboard([p['id'] for p in policies])
    if dashboard['current']['id'] != active['id']:
        raise Conflict('The current policy changed while preparing the comparison. Refresh and try again.')
    by_policy = {v['policy_id']:v for v in dashboard['versions']}
    rows = [{'request_id':r['request_id'],'external_id':r['external_id'],'amount_cents':r['amount_cents'],
             'current':r['baseline'],'candidates':{v['policy_id']:r['candidates'][v['id']] for v in dashboard['versions'] if v['id'] in r['candidates']},
             'human_reference':r['label'],'work_status':r['work_status']} for r in dashboard['requests']]
    baseline = [r['current'] for r in rows]
    versions = []
    for p in policies:
        observed = by_policy.get(p['id']); check = checks[p['id']]
        available = bool(observed and observed['status']=='shadow' and not observed['stale'])
        reason = None if available else 'The baseline, model or implementation changed. Recheck this saved version.' if observed and observed['stale'] else 'This version is not running in Shadow.'
        summary = {**observed['metrics'],**_summary([r['candidates'][p['id']] for r in rows],baseline)} if available else None
        versions.append({'policy_id':p['id'],'version':p['version'],'checks_id':observed['id'] if observed else check['id'] if check else None,
                         'available':available,'reason':reason,'summary':summary,
                         'decision_reports':observed.get('decision_reports') if available else None,
                         'observed_requests':observed['observed'] if observed else 0,'readiness':observed['gate'] if observed else None})
    return {'mode':'shadow','current':{'policy_id':active['id'],'version':active['version'],
                                      'summary':{**dashboard['current']['metrics'],**_summary(baseline,baseline)}},
            'versions':versions,'requests':rows, 'current_decision_reports':dashboard.get('current_decision_reports'),
            'data_fingerprint':fingerprint([(r['request_id'],r['current']['input_fingerprint']) for r in rows]),
            'total_requests':dashboard['total_requests'],'compared_requests':dashboard['compared_requests'],
            'excluded_requests':dashboard['excluded_requests'],'reviewed_requests':dashboard['reviewed_requests'],
            'limitations':[dashboard['note'],'Only selected running, fresh versions contribute to the shared request intersection.',
                           'Draft, stopped and stale versions have no comparable Shadow result.']}


def _rollback_target(c,pid):
    target = _policy(c,pid)
    if target['status'] != 'archived':
        raise Conflict('Rollback is available only for an archived version that was previously Current. Draft versions must qualify through Shadow.')
    return target


def rollback_preview(store,pid):
    with store.connect() as c:
        target = _rollback_target(c,pid)
    report = store.preview(target['data'])
    with store.tx() as c:
        current = store.policy(c); fresh_target = _rollback_target(c,pid)
        row = c.execute('SELECT * FROM previews WHERE id=?',(report['id'],)).fetchone()
        if row['base_id'] != current['id'] or row['workspace_fingerprint'] != store.workspace_fingerprint(c) or fresh_target['data'] != target['data']:
            raise Conflict('The workspace changed during the preview. Create a fresh rollback preview.')
        qualification = _qualification(store,c,target)
        warnings = ['Rollback restores this version and automatic processing within its preserved payment limits.', *qualification['warnings']]
        saved = json.loads(row['data'])
        saved['rollback'] = {'target_id':pid,'target_hash':fingerprint(target['data']),
                             'source_id':current['id'],'manifest':store.manifest(),
                             'prepared_hash':fingerprint(saved['prepared_evidence'])}
        saved.update(target={'id':pid,'version':target['version']},current={'id':current['id'],'version':current['version']},
                     qualification=qualification,warnings=warnings,execution_mode='simulate')
        c.execute('UPDATE previews SET data=? WHERE id=?',(dump(saved),report['id']))
        return {key:value for key,value in saved.items() if key not in ('prepared_evidence','rollback')}


def rollback_version(store,pid,preview_id,reason):
    if not reason.strip():
        raise ValueError('Record why this previous version should be restored.')
    with store.tx() as c:
        target = _rollback_target(c,pid); current = store.policy(c)
        row = c.execute('SELECT * FROM previews WHERE id=?',(preview_id,)).fetchone()
        if not row:
            raise KeyError('Rollback preview not found')
        saved = json.loads(row['data']); association = saved.get('rollback',{})
        if association.get('target_id') != pid or association.get('target_hash') != fingerprint(target['data']) or json.loads(row['policy']) != validate_policy(target['data'])[0]:
            raise Conflict('This preview does not match the exact archived target version.')
        if row['base_id'] != current['id'] or association.get('source_id') != current['id'] or row['workspace_fingerprint'] != store.workspace_fingerprint(c) or association.get('manifest') != store.manifest():
            raise Conflict('The rollback preview is stale. Preview the current workspace again.')
        eligible = [store.request(r[0],c) for r in c.execute("SELECT id FROM requests WHERE status='ready' AND NOT EXISTS(SELECT 1 FROM decisions WHERE decisions.request_id=requests.id)").fetchall()]
        evidence = {obj['id']:store.candidate(c,obj,target['data']) for obj in eligible}
        if fingerprint(evidence) != association.get('prepared_hash'):
            raise Conflict('Candidate evidence changed after the rollback preview. Create a new preview.')
        qualification = _qualification(store,c,target)
        c.execute("UPDATE policies SET status='archived' WHERE id=?",(current['id'],))
        c.execute("UPDATE policies SET status='active' WHERE id=?",(pid,))
        c.execute("UPDATE state SET value=? WHERE key='active_policy'",(pid,))
        c.execute("UPDATE state SET value='simulate' WHERE key='mode'")
        c.execute("UPDATE state SET value=CAST(value AS INTEGER)+1 WHERE key='epoch'")
        for obj in eligible:
            e = evidence[obj['id']]
            ev = evaluate(obj['data'],e,target['data'],bool(obj['conflict']))
            c.execute('UPDATE requests SET evidence=?,evaluation=?,queue=?,version=version+1 WHERE id=?',
                      (dump(e),dump(ev),ev['queue'],obj['id']))
        c.execute("UPDATE experiments SET status='superseded' WHERE status='active'")
        release = _checks(store,c,pid,released=True)
        if release:
            c.execute("UPDATE experiments SET status='active' WHERE id=?",(release['id'],))
        store.audit(c,pid,'policy_rolled_back',{'from_id':current['id'],'to_id':pid,
                    'from_version':current['version'],'to_version':target['version'],'reason':reason,
                    'preview_id':preview_id,'qualification':qualification,'updated_requests':len(eligible)},'manager')
        return {'current':store.policy(c),'previous':{'id':current['id'],'version':current['version']},
                'execution_mode':'simulate','qualification':qualification,'updated_requests':len(eligible),'preview_id':preview_id}
