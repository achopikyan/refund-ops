"""Reproducible source-derived policies and source provenance.

No historical decision/outcome is ever added to a request's evidence. Reconstruction
targets who handled a request, not whether the historical decision was correct.
"""
from itertools import product
from pathlib import Path
from zipfile import ZipFile
import hashlib
import json
import xml.etree.ElementTree as ET

from .domain import Policy, PolicyChecks, Rule, Condition, parse_csv, validate_policy, fingerprint
from .financial import ExecutionLimits

CUTOFF = '2026-08-01'


def load_sources(folder):
    folder = Path(folder)
    files = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir()) if p.is_file()}
    data = {}
    for kind in ('history','pending'):
        raw = parse_csv((folder/(kind+'.csv')).read_text(encoding='utf-8-sig'), 'DMY')
        grouped = {}
        for row in raw: grouped.setdefault(row['normalized']['request_id'],[]).append(row)
        data[kind] = {'raw':raw,'groups':grouped,'rows':[v[0]['normalized'] for v in grouped.values()]}
    for key, group in data['history']['groups'].items():
        if len({r['hash'] for r in group}) > 1: raise ValueError('Conflicting historical versions: '+key)
    doc = next(folder.glob('*.docx'))
    ns = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    parts = {}
    with ZipFile(doc) as z:
        for name in z.namelist():
            if name.startswith('word/') and name.endswith('.xml') and any(k in name for k in ('document','comment','footnote','endnote','header','footer')):
                root = ET.fromstring(z.read(name))
                parts[name] = {'paragraphs':[''.join(n.text or '' for n in p.iter() if n.tag in ('{'+ns['w']+'}t','{'+ns['w']+'}delText')) for p in root.findall('.//w:p',ns)],
                               'hidden_runs':len(root.findall('.//w:vanish',ns)), 'insertions':len(root.findall('.//w:ins',ns)), 'deletions':len(root.findall('.//w:del',ns))}
    return {**data,'hashes':files,'document':parts,
            'dictionary':(folder/'data_dictionary.csv').read_text(encoding='utf-8-sig'),
            'policy_notes':(folder/'policy_notes.csv').read_text(encoding='utf-8-sig')}


def legacy_match(r, cap, tenure, prior):
    return (r.get('amount_cents') is not None and r['amount_cents'] < cap
            and r.get('tenure_months') is not None and r['tenure_months'] >= tenure
            and r.get('prior_refunds_12m') is not None and r['prior_refunds_12m'] <= prior
            and r.get('fraud_flag') is False
            and (r['stated_reason'] != 'changed_mind' or r.get('days_since_delivery') is not None and r['days_since_delivery'] <= 14))


def infer_legacy(history):
    eligible = [r for r in history if not r['errors'] and all(r[k] is not None for k in ('amount_cents','tenure_months','prior_refunds_12m','fraud_flag'))]
    train = [r for r in eligible if r['requested_at'] < CUTOFF and r['decided_at'][:10] < CUTOFF]
    if not train: raise ValueError('No valid training rows for reconstruction.')
    # Predeclared simple boundaries, not per-ID exceptions or customer memorisation.
    candidates = []
    for cap, tenure, prior in product(range(2500,10500,500),range(25),range(3)):
        mismatches = [r['request_id'] for r in train if legacy_match(r,cap,tenure,prior) != (r['decided_by']=='auto')]
        candidates.append((len(mismatches),cap,tenure,prior,mismatches))
    best = min(candidates)
    seen = {r['customer_id'] for r in train}
    later = [r for r in eligible if r['requested_at'] >= CUTOFF and r['customer_id'] not in seen]
    params = best[1:4]
    def score(rows):
        errors = [{'id':r['request_id'],'observed_auto':r['decided_by']=='auto','predicted_auto':legacy_match(r,*params)} for r in rows if legacy_match(r,*params) != (r['decided_by']=='auto')]
        return {'total':len(rows),'correct':len(rows)-len(errors),'exceptions':errors}
    return {'cutoff':CUTOFF,'amount_below_cents':params[0],'minimum_tenure_months':params[1],
            'maximum_prior_refunds':params[2],'search_size':len(candidates),'training':score(train),'later_customer_disjoint':score(later),
            'all_eligible':score(eligible),'excluded_missing_or_invalid':[r['request_id'] for r in history if r not in eligible],
            'excluded_later_seen_customers':[r['request_id'] for r in eligible if r['requested_at']>=CUTOFF and r['customer_id'] in seen],
            'uncertainty':'Best fit to observed routing, not recovery of source code. The observed $54 auto / $55 manual boundary cannot establish behaviour at unseen cent values. RF-1002 remains an exception; missing fields are not imputed. The data was inspected during development, so the later set is a diagnostic, not a blind test.'}


def build_policies(inferred):
    c = lambda field,op,value:Condition(field=field,op=op,value=value)
    def rule(id,name,priority,conditions,reason,action='auto_approve'):
        return Rule(id=id,name=name,priority=priority,conditions=conditions,reason_code=reason,action=action)
    v1 = Policy(name='Policy v1',checks=PolicyChecks(**{key:key=='change_mind_window' for key in PolicyChecks.model_fields}),rules=[rule('legacy-small','Small refunds from established customers',100,[
        c('amount_cents','lt',inferred['amount_below_cents']), c('tenure_months','gte',inferred['minimum_tenure_months']),
        c('prior_refunds_12m','lte',inferred['maximum_prior_refunds']), c('fraud_flag','eq',False)],'small_established_customer')]).model_dump()
    clean = [c('fraud_flag','eq',False),c('prior_refunds_12m','eq',0),c('tenure_months','gte',0)]
    v2 = Policy(name='Policy v2',execution_limits=ExecutionLimits(max_single_cents=30000),rules=[
        rule('amount-limit','Review amounts above $300',950,[c('amount_cents','gt',30000)],'high_value','review'),
        rule('repeat-requests','Review repeat refund requests',900,[c('prior_refunds_12m','gt',0)],'repeat_requests','review'),
        rule('carrier-incident','Review Northfield delivery disruption',850,[c('stated_reason','eq','never_arrived'),c('facts.location','eq','northfield')],'carrier_incident','review'),
        rule('confirmed-card','Confirmed stolen card: full refund',880,[c('facts.fraud_confirmed','eq','yes')],'confirmed_stolen_card'),
        rule('our-error','Confirmed fulfilment error: full refund',750,[c('facts.our_error','eq','yes')],'confirmed_merchant_error'),
        rule('electronics-damage-review','Review electronics damage after merchant-error checks',700,[c('category','eq','electronics'),c('stated_reason','eq','arrived_damaged')],'damage_origin','review'),
        rule('simple-size','Wrong-size apparel returns up to $100',600,[c('stated_reason','eq','wrong_size'),c('category','eq','apparel'),c('amount_cents','lte',10000),*clean],'simple_return'),
        rule('simple-mind','Change-of-mind returns up to $75',550,[c('stated_reason','eq','changed_mind'),c('amount_cents','lte',7500),c('days_since_delivery','lte',14),*clean],'simple_return'),
        rule('small-damage','Apparel and home damage up to $50',500,[c('stated_reason','eq','arrived_damaged'),c('category','in',['apparel','home']),c('amount_cents','lte',5000),*clean],'small_established_customer'),
        rule('verified-damage','Photo-supported apparel and home damage up to $150',450,[c('stated_reason','eq','arrived_damaged'),c('category','in',['apparel','home']),c('amount_cents','lte',15000),c('facts.photo','eq','yes'),*clean],'verified_damage'),
    ]).model_dump()
    for p in (v1,v2):
        _, issues = validate_policy(p)
        if issues: raise ValueError('; '.join(issues))
    return v1,v2


def broader_candidate(v2):
    """An intentionally broader, ordinary editable candidate for comparing tradeoffs."""
    from copy import deepcopy
    v3 = deepcopy(v2)
    v3['name'] = 'Policy v3'
    v3['rules'] = [r for r in v3['rules'] if r['id'] not in ('repeat-requests', 'carrier-incident', 'electronics-damage-review')]
    for rule in v3['rules']:
        if rule['id'] == 'verified-damage':
            rule['name'] = 'Broader photo-supported damage up to $300'
            rule['conditions'] = [condition for condition in rule['conditions'] if condition['field'] != 'category']
            for condition in rule['conditions']:
                if condition['field'] == 'amount_cents':
                    condition['value'] = 30000
    v3['rules'].append(Rule(
        id='broad-returns', name='Apparel returns up to $300, including repeat requests', priority=650,
        conditions=[Condition(field='category',op='eq',value='apparel'),
                    Condition(field='stated_reason',op='in',value=['wrong_size','changed_mind']),
                    Condition(field='amount_cents',op='lte',value=30000),
                    Condition(field='fraud_flag',op='eq',value=False)],
        reason_code='simple_return', action='auto_approve').model_dump())
    _, issues = validate_policy(v3)
    if issues:
        raise ValueError('; '.join(issues))
    return v3


def context_issues(request, history):
    """Only previous request-time facts; never use future outcomes or decisions."""
    prior = [r for r in history if request.get('customer_id') and r.get('customer_id') == request['customer_id'] and r.get('requested_at','') < request.get('requested_at','') and r.get('request_id') != request.get('request_id')]
    tenure = request.get('tenure_months')
    earlier = [r for r in prior if tenure is not None and r.get('tenure_months') is not None and r['tenure_months'] > tenure + 1]
    if earlier:
        last = max(earlier,key=lambda r:r['requested_at'])
        return [f"Customer tenure is {tenure} months, below the {last['tenure_months']} months recorded in earlier request {last['request_id']}. Verify the customer data."]
    return []


def populate(store, sources, v1, v2, report, *, v3=None, current_version=2):
    """Only an unused staged database; resetting the user's DB is a separate step."""
    from .storage import dump, now, uid
    with store.tx() as c:
        if c.execute('SELECT COUNT(*) FROM requests').fetchone()[0] or c.execute('SELECT COUNT(*) FROM policies').fetchone()[0] != 1:
            raise ValueError('Build into a new staged database, not a working workspace.')
        c.execute('DELETE FROM policies'); c.execute("DELETE FROM state WHERE key='active_policy'")
        ids=[]
        versions = [v1, v2] + ([v3] if v3 is not None else [])
        if current_version not in range(1, len(versions) + 1):
            raise ValueError('Current must identify one of the source versions.')
        for version,p in enumerate(versions,1):
            pid=uid(); ids.append(pid)
            c.execute('INSERT INTO policies VALUES(?,?,?,?,?,?,?)',(pid,p['name'],dump(p),fingerprint(p),'active' if version==current_version else 'draft',ids[0] if version>1 else None,now()))
            c.execute('INSERT INTO draft_sources VALUES(?,?)',(pid,dump({'source':'source_rebuild','rules':report['rule_provenance'] if version==2 else [],'reconstruction':report['legacy_reconstruction'],'source_hashes':sources['hashes']})))
        current_id = ids[current_version - 1]
        c.execute("INSERT INTO state VALUES('active_policy',?)",(current_id,))
        c.execute("UPDATE state SET value='simulate' WHERE key='mode'")
        c.execute("INSERT INTO state VALUES('source_rebuild',?)",(dump({'versions':ids,'hashes':sources['hashes']}),))
        store.audit(c,current_id,'source_workspace_rebuilt',{'historical_reference':ids[0],'current':current_id,'automatic_execution':True},'manager')
    return ids
