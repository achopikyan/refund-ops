"""Current-version monitoring, with explicit scope for shared execution limits."""
import json
from collections import Counter
from datetime import datetime, timezone
from .policy_management import _qualification, _policy


def current_performance(store, policy_id=None):
    with store.connect() as c:
        c.execute('BEGIN')
        active=store.policy(c)
        policy = _policy(c,policy_id) if policy_id else active
        if policy['status'] not in ('active','archived'):
            raise ValueError('Performance is available for versions that have served requests.')
        is_current=policy['id']==active['id']
        pid = policy['id']
        state = store.state(c)
        requests = [store.request(r[0], c) for r in c.execute("SELECT id FROM requests WHERE status!='resolved'").fetchall()] if is_current else []
        ready = [r for r in requests if r['status'] in ('ready', 'in_review')]
        routes = Counter('auto_approve' if r['evaluation']['action']=='auto_approve' else 'fraud' if r['evaluation']['queue']=='fraud' else 'review' for r in ready)
        reasons = Counter((r['evaluation']['reason_code'],r['evaluation']['reason_label']) for r in ready)
        decisions = [dict(r) for r in c.execute('''SELECT d.*,x.evaluation,
            COALESCE((SELECT SUM(l.amount_cents) FROM ledger l WHERE l.decision_id=d.id),0) AS paid_cents,
            EXISTS(SELECT 1 FROM audit a WHERE a.object_id=d.request_id AND a.type='decision_recorded' AND json_extract(a.detail,'$.automatic')=1) AS automatic
            FROM decisions d LEFT JOIN decision_context x ON x.decision_id=d.id WHERE d.policy_id=?''', (pid,))]
        payments = c.execute('SELECT COUNT(*),COALESCE(SUM(l.amount_cents),0) FROM ledger l JOIN decisions d ON d.id=l.decision_id WHERE d.policy_id=?', (pid,)).fetchone()
        groups = {}
        events=Counter(); event_cases=Counter(); with_outcomes=0; daily={}; human_auto=0; excess_cents=0; below_cents=0; reference_errors=0
        for d in decisions:
            ev = json.loads(d['evaluation']) if d['evaluation'] else {}
            key = ev.get('rule_id') or ev.get('reason_code') or 'Not recorded'
            name=next((r['name'] for r in policy['data']['rules'] if r['id']==key),ev.get('reason_label') or key)
            group = groups.setdefault(key, {'rule_id':key,'rule_name':name,'decisions':0,'overrides':0,'mature':0,'unknown_outcomes':0,'adverse':0})
            group['decisions'] += 1
            group['overrides'] += int(ev.get('action')=='auto_approve' and (d['action']!='approved' or d['amount_cents']!=ev.get('proposed_amount_cents')))
            group['mature'] += int((datetime.now(timezone.utc)-datetime.fromisoformat(d['created_at'])).days>=30)
            outcomes = {r[0] for r in c.execute('SELECT type FROM outcomes WHERE request_id=?',(d['request_id'],))}
            for row in c.execute('SELECT type FROM outcomes WHERE request_id=?',(d['request_id'],)):events[row[0]]+=1
            event_cases.update(outcomes);with_outcomes+=bool(outcomes)
            day=d['created_at'][:10];trend=daily.setdefault(day,{'date':day,'decisions':0,'automatic':0,'human':0,'paid_cents':0})
            trend['decisions']+=1;trend['automatic' if d['automatic'] else 'human']+=1
            trend['paid_cents']+=d['paid_cents']
            if not d['automatic'] and ev.get('action')=='auto_approve':
                human_auto+=1
                allowed=0 if d['action']=='rejected' else d['amount_cents'] or 0
                excess=max(0,(ev.get('proposed_amount_cents') or 0)-allowed)
                excess_cents+=excess;reference_errors+=excess>0
                below_cents+=max(0,allowed-(ev.get('proposed_amount_cents') or 0))
            group['unknown_outcomes'] += int(not outcomes)
            group['adverse'] += int(bool(outcomes & {'chargeback','audit_fail'}))
        qualification = _qualification(store,c,policy)
        clock=datetime.now(timezone.utc)
        ages=[max(0,(clock-datetime.fromisoformat(r['created_at'])).total_seconds()/3600) for r in requests]
        age_bands=Counter('Under 1 hour' if h<1 else '1 to 24 hours' if h<24 else '1 to 7 days' if h<168 else 'Over 7 days' for h in ages)
        calls=[dict(r) for r in c.execute('SELECT purpose,cost,latency,status FROM llm_calls')]
        latency=sorted(r['latency'] for r in calls)
        return {
            'policy':{'id':pid,'version':policy['version'],'rules':len(policy['data']['rules']),'is_current':is_current},
            'mode':state['mode'] if is_current else 'archived','qualification':qualification,'budget':store.release_budget(c,policy_id=pid),
            'queue':{'open':len(requests),'ready':len(ready),'waiting':len(requests)-len(ready),
                     'routes':{k:routes[k] for k in ('review','fraud','auto_approve')},
                     'reasons':[{'code':code,'label':label,'count':count} for (code,label),count in reasons.most_common()],
                     'execution_blocked':sum(bool(r.get('automation_blocker')) for r in ready),
                     'analysis_attention':sum(not r['evidence'].get('complete',False) for r in ready)},
            'decisions':{'total':len(decisions),'automatic':sum(d['automatic'] for d in decisions),
                         'human':sum(not d['automatic'] for d in decisions),'payment_count':payments[0],'paid_cents':payments[1]},
            'operations':{'decision_types':dict(Counter(d['action'] for d in decisions)),
                          'automation_rate':sum(d['automatic'] for d in decisions)/len(decisions) if decisions else None,
                          'reference_auto_count':human_auto,'reference_excess_cases':reference_errors,'reference_excess_cents':excess_cents,
                          'reference_below_cents':below_cents,'oldest_open_hours':max(ages) if ages else None,
                          'queue_age_bands':dict(age_bands),'daily':sorted(daily.values(),key=lambda x:x['date']),
                          'reviewer_active_minutes':None,'measured_savings_cents':None},
            'outcomes':{'recorded_cases':with_outcomes,'missing_cases':len(decisions)-with_outcomes,
                        'coverage':with_outcomes/len(decisions) if decisions else None,'case_counts':dict(event_cases),
                        'event_counts':dict(events),'chargeback_rate':None,'chargeback_loss_cents':None},
            'ai_workspace':{'calls':len(calls),'recorded_cost_usd':sum(r['cost'] or 0 for r in calls),
                            'unknown_cost_calls':sum(r['cost'] is None for r in calls),'failures':sum(r['status']!='ok' for r in calls),
                            'p95_latency_seconds':latency[min(len(latency)-1,int(len(latency)*.95))] if latency else None,
                            'purposes':dict(Counter(r['purpose'] for r in calls)),
                            'scope':'All workspace calls, including history, candidates and model checks. Not attributable to Current or per-request cost.'},
            'provenance':{'synthetic_workspace':bool(state.get('demo_scenario')),'as_of':clock.isoformat()},
            'feedback':list(groups.values()),
            'scope':'Queue routing covers ready requests under Current. Decision, payment and outcome totals include only records attributed to this saved version, across all its active periods. Waiting requests retain their existing workflow until resumed.',
        }
