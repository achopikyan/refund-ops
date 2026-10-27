"""Paired decision evidence for Backtest, Shadow and Comparison.

Descriptive routing, human references and financial scenarios are kept separate.
This module never changes a policy, request, reference judgment or payment.
"""
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
from math import ceil, log
import re
from .financial import ReleaseSettings, error_upper


def route(ev):
    return 'auto_approve' if ev['action'] == 'auto_approve' else 'fraud' if ev.get('queue') == 'fraud' or ev['action'] == 'fraud' else 'review'


def payout(ev):
    return (ev.get('proposed_amount_cents') or 0) if route(ev) == 'auto_approve' else 0


def fraction(n, d):
    return n / d if d else None


def historical_reference(data):
    """Post-decision fields are diagnostic context only, never evaluator inputs."""
    action, amount = data.get('decision'), data.get('amount_cents')
    note = data.get('outcome_note') or ''
    allowed = amount if action == 'approved' else 0 if action == 'rejected' else None
    if action == 'partial' and amount is not None:
        match = re.search(r'\b(\d+(?:\.\d+)?)\s*(?:percent|%)\s+issued\b', note, re.I)
        if match and 0 <= Decimal(match[1]) <= 100:
            allowed = int((Decimal(amount) * Decimal(match[1]) / 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    return {'allowed_cents': allowed, 'action': action, 'source': 'historical_decision',
            'actor': data.get('decided_by') or 'Unknown', 'minutes': data.get('review_minutes'),
            'critical': False, 'note': note, 'captured_before_review': False}


def historical_rows(history, baseline, candidate, evidence_provider=None):
    from .domain import pending_evidence
    from .experiments import assess, request_input
    rows = []
    for data in history:
        inputs = request_input(data)
        e = evidence_provider(inputs,candidate['criteria']) if evidence_provider else pending_evidence(inputs)
        baseline_e = evidence_provider(inputs,baseline['criteria']) if evidence_provider else e
        rows.append({'id': data['request_id'], 'data': inputs, 'history': data,
                     'baseline': assess(inputs, baseline_e, baseline), 'candidate': assess(inputs, e, candidate),
                     'evidence': e, 'baseline_evidence': baseline_e, 'conflict': False, 'cohort': 'history',
                     'label': historical_reference(data), 'observed_at': None})
    return rows


def observation_rows(observations):
    return [{'id': o['snapshot'].get('external_id') or o['request_id'], 'data': o['snapshot']['data'],
             'baseline': o['baseline'], 'candidate': o['candidate'], 'evidence': o['snapshot']['evidence'],
             'baseline_evidence': o['snapshot'].get('baseline_evidence', o['snapshot']['evidence']),
             'conflict': o['snapshot'].get('conflict', False), 'cohort': o['cohort'],
             'label': o.get('label'), 'outcomes': o.get('outcomes', []), 'observed_at': o.get('created_at')} for o in observations]


def reference_known(row, mode):
    label = row.get('label') or {}
    if label.get('allowed_cents') is None: return False
    if mode == 'backtest': return label.get('actor') not in ('auto', 'Unknown', None)
    return label.get('captured_before_review', False)


def adverse(row):
    note = (row.get('history', {}).get('outcome_note') or '').lower()
    events = {o['type'] for o in row.get('outcomes', [])}
    return {'chargeback': 'chargeback' in note or 'chargeback' in events,
            'overturned': 'overturned' in note or 'refunded on appeal' in note or 'appeal_overturned' in events,
            'account_closed': 'closed account' in note,
            'note_recorded': bool(note) or bool(events)}


def amount_band(amount):
    if amount is None: return 'Unknown'
    if amount <= 5000: return '$0 to $50'
    if amount <= 10000: return 'Over $50 to $100'
    if amount <= 30000: return 'Over $100 to $300'
    return 'Over $300'


def segment_values(row):
    d = row['data']; tenure = d.get('tenure_months'); prior = d.get('prior_refunds_12m')
    rid = d.get('request_id', row['id'])
    return {'customer_reason': d.get('stated_reason') or 'Unknown', 'amount_band': amount_band(d.get('amount_cents')),
            'routing_reason': row['candidate'].get('reason_code') or 'Unknown',
            'category': d.get('category') or 'Unknown', 'payment_method': d.get('payment_method') or 'Unknown',
            'tenure': 'Unknown' if tenure is None else 'Under 12 months' if tenure < 12 else '12 months or more',
            'prior_refunds': 'Unknown' if prior is None else 'No prior refunds' if prior == 0 else 'Prior refunds',
            'source_channel': 'Web form' if rid.startswith('RF-1') else 'Support desk' if rid.startswith('RF-2') else 'Other / unknown',
            'location': row.get('evidence', {}).get('facts', {}).get('location', {}).get('value') or 'Unknown',
            'request_month': (d.get('requested_at') or 'Unknown')[:7]}


def side_summary(rows, side, mode, cap):
    auto = [r for r in rows if route(r[side]) == 'auto_approve']
    reviewed = [r for r in auto if reference_known(r, mode)]
    excess = [max(0, payout(r[side]) - r['label']['allowed_cents']) for r in reviewed]
    groups = defaultdict(list)
    for r in auto:
        if r['data'].get('customer_id'): groups[r['data']['customer_id']].append(r)
    checked = [g for g in groups.values() if all(reference_known(r, mode) for r in g)]
    errors = sum(any(payout(r[side]) > r['label']['allowed_cents'] for r in g) for g in checked)
    upper = error_upper(errors, len(checked)) if mode == 'shadow' else None
    counts = {key: 0 for key in ('auto_approve', 'review', 'fraud')}
    counts.update(Counter(route(r[side]) for r in rows))
    return {'total': len(rows), 'routes': counts, 'auto_count': len(auto), 'auto_rate': fraction(len(auto), len(rows)),
            'payout_cents': sum(payout(r[side]) for r in auto), 'reviewed_auto': len(reviewed),
            'review_coverage': fraction(len(reviewed), len(auto)),
            'reviewed_payout_cents': sum(payout(r[side]) for r in reviewed),
            'unreviewed_auto': len(auto) - len(reviewed),
            'unreviewed_cents': sum(payout(r[side]) for r in auto if not reference_known(r, mode)),
            'agreement_count': sum(payout(r[side]) == r['label']['allowed_cents'] for r in reviewed),
            'agreement_rate': fraction(sum(payout(r[side]) == r['label']['allowed_cents'] for r in reviewed), len(reviewed)),
            'overpayment_cases': sum(x > 0 for x in excess), 'overpayment_cents': sum(excess),
            'overpayment_rate': fraction(sum(x > 0 for x in excess), len(reviewed)),
            'excess_share_of_reviewed_payout': fraction(sum(excess), sum(payout(r[side]) for r in reviewed)),
            'underpayment_cases': sum(payout(r[side]) < r['label']['allowed_cents'] for r in reviewed),
            'customer_groups': len(groups), 'reviewed_customer_groups': len(checked), 'group_errors': errors,
            'error_upper_95': upper, 'cap_exceedances': sum(payout(r[side]) > cap for r in auto),
            'chargeback_cases_on_auto': sum(adverse(r)['chargeback'] for r in auto),
            'outcome_notes_on_auto': sum(adverse(r)['note_recorded'] for r in auto),
            'manual_full_approvals': sum(route(r[side]) != 'auto_approve' and reference_known(r, mode)
                                       and r['label']['allowed_cents'] == r['data'].get('amount_cents') for r in rows)}


def review_minutes(row, fallback):
    label = row.get('label') or {}
    # Operational decisions currently do not capture reviewer active time.
    recorded = row.get('history', {}).get('review_minutes') if row.get('history', {}).get('decided_by') != 'auto' else None
    if not row.get('history') and label.get('source') != 'human_decision': recorded = label.get('minutes')
    try:
        if recorded is not None and str(recorded).strip() and float(recorded) > 0: return float(recorded), True
    except (ValueError, TypeError): pass
    return fallback, False


def policy_diff(before, after):
    a, b = ({r['id']: r for r in p['rules']} for p in (before, after))
    changes = [{'id': rid, 'name': r['name'], 'change': 'added' if rid not in a else 'modified'}
               for rid, r in b.items() if rid not in a or r != a[rid]]
    changes += [{'id': rid, 'name': r['name'], 'change': 'removed'} for rid, r in a.items() if rid not in b]
    settings = [{'field': key, 'before': before.get(key), 'after': after.get(key)}
                for key in sorted((set(before) | set(after)) - {'name', 'description', 'rules'}) if before.get(key) != after.get(key)]
    return {'rules': changes, 'settings': settings}


def build_report(rows, baseline_policy, candidate_policy, settings=None, *, mode, metadata=None):
    settings = ReleaseSettings.model_validate(settings or {}).model_dump()
    metadata = dict(metadata or {})
    a, b = (side_summary(rows, side, mode, settings['max_single_cents']) for side in ('baseline', 'candidate'))
    new = [r for r in rows if route(r['baseline']) != 'auto_approve' and route(r['candidate']) == 'auto_approve']
    returned = [r for r in rows if route(r['baseline']) == 'auto_approve' and route(r['candidate']) != 'auto_approve']
    newly = side_summary(new, 'candidate', mode, settings['max_single_cents'])
    transitions = defaultdict(lambda: {'count': 0, 'requested_cents': 0, 'request_ids': []})
    cases = []
    minutes = {'saved': 0.0, 'added': 0.0, 'recorded_saved': 0.0, 'recorded_added': 0.0, 'estimated_saved_cases': 0, 'estimated_added_cases': 0}
    for kind, population in (('saved', new), ('added', returned)):
        for r in population:
            duration, recorded = review_minutes(r, settings['review_minutes'])
            minutes[kind] += duration
            if recorded: minutes['recorded_' + kind] += duration
            else: minutes['estimated_' + kind + '_cases'] += 1
    for r in rows:
        old, new_route = route(r['baseline']), route(r['candidate'])
        t = transitions[old, new_route]; t['count'] += 1; t['requested_cents'] += r['data'].get('amount_cents') or 0; t['request_ids'].append(r['id'])
        label = r.get('label'); known = reference_known(r, mode); events = adverse(r)
        flags = []
        if old != 'auto_approve' and new_route == 'auto_approve': flags.append('new_auto')
        if old == 'auto_approve' and new_route != 'auto_approve': flags.append('returned_to_review')
        if old == 'fraud' and new_route != 'fraud': flags.append('less_fraud_review')
        if new_route == 'auto_approve' and known and payout(r['candidate']) > label['allowed_cents']: flags.append('above_reference')
        if new_route == 'auto_approve' and not known: flags.append('unreviewed_auto')
        if events['chargeback']: flags.append('recorded_chargeback')
        if events['overturned']: flags.append('overturned_appeal')
        if r['data'].get('errors') or r.get('conflict'): flags.append('data_issue')
        if not r.get('evidence', {}).get('complete'): flags.append('incomplete_evidence')
        if (label or {}).get('critical'): flags.append('critical_finding')
        cases.append({'id': r['id'], 'amount_cents': r['data'].get('amount_cents'),
                      'customer_reason': r['data'].get('stated_reason'), 'cohort': r['cohort'],
                      'baseline': {k: r['baseline'].get(k) for k in ('action', 'queue', 'reason_code', 'explanation', 'rule_id', 'proposed_amount_cents')},
                      'candidate': {k: r['candidate'].get(k) for k in ('action', 'queue', 'reason_code', 'explanation', 'rule_id', 'proposed_amount_cents')},
                      'reference': label, 'reference_eligible': known, 'flags': flags,
                      'changed': any(r['baseline'].get(k) != r['candidate'].get(k) for k in ('action', 'reason_code', 'rule_id', 'proposed_amount_cents'))})
    # Compare excess on the UNION of both automatic cohorts, with the same reference.
    paired = [r for r in rows if reference_known(r, mode) and (route(r['baseline']) == 'auto_approve' or route(r['candidate']) == 'auto_approve')]
    excess_delta = sum(max(0, payout(r['candidate']) - r['label']['allowed_cents']) - max(0, payout(r['baseline']) - r['label']['allowed_cents']) for r in paired)
    savings = round((minutes['saved'] - minutes['added']) / 60 * settings['hourly_cost_cents'])
    shared_ai = len(rows) * settings['ai_cost_cents']
    extra_ai = shared_ai if candidate_policy.get('criteria') != baseline_policy.get('criteria') and candidate_policy.get('criteria') else 0
    audit_delta = round((b['auto_count'] - a['auto_count']) * settings['audit_fraction'] * settings['audit_cost_cents'])
    operating_margin = savings - extra_ai - audit_delta
    reviewed_new = [r for r in new if reference_known(r, mode)]
    new_excess = sum(max(0, payout(r['candidate']) - r['label']['allowed_cents']) for r in reviewed_new)
    new_exposure = sum(payout(r['candidate']) for r in new)
    new_review_saving = round(minutes['saved'] / 60 * settings['hourly_cost_cents'])
    new_operating = extra_ai + round(len(new) * settings['audit_fraction'] * settings['audit_cost_cents'])
    break_even = min(1, max(0, (new_review_saving - new_operating) / new_exposure)) if new_exposure else None
    stress = ceil(b['error_upper_95'] * settings['projection_cases'] * settings['max_single_cents']) if b['error_upper_95'] is not None else None
    group_target = ceil(log(.05) / log(1 - settings['max_error_bps'] / 10000)) if settings['max_error_bps'] < 10000 else 1
    segments = []
    for dimension in segment_values(rows[0]) if rows else []:
        buckets = defaultdict(list)
        for r in rows: buckets[segment_values(r)[dimension]].append(r)
        for value, group in sorted(buckets.items()):
            left, right = (side_summary(group, side, mode, settings['max_single_cents']) for side in ('baseline', 'candidate'))
            segments.append({'dimension': dimension, 'value': value, 'total': len(group),
                             'baseline_auto': left['auto_count'], 'candidate_auto': right['auto_count'],
                             'auto_rate': right['auto_rate'], 'payout_cents': right['payout_cents'],
                             'reviewed_auto': right['reviewed_auto'], 'overpayment_cases': right['overpayment_cases'],
                             'overpayment_cents': right['overpayment_cents'], 'error_upper_95': right['error_upper_95'],
                             'reviewed_customer_groups': right['reviewed_customer_groups'],
                             'known_chargebacks': right['chargeback_cases_on_auto'],
                             'new_auto': sum(route(r['baseline']) != 'auto_approve' and route(r['candidate']) == 'auto_approve' for r in group)})
    rules = []
    for rule in candidate_policy['rules']:
        traces = [(r, next((t for t in r['candidate'].get('trace', []) if t['rule_id'] == rule['id']), None)) for r in rows]
        matching = [(r, t) for r, t in traces if t and t['matched'] is True]
        winning = [r for r, t in matching if r['candidate'].get('resolution', {}).get('decisive_rule_id') == rule['id']]
        auto_wins = [r for r in winning if route(r['candidate']) == 'auto_approve']
        overlap = Counter(t2['rule_id'] for r, t in matching for t2 in r['candidate'].get('trace', []) if t2['matched'] is True and t2['rule_id'] != rule['id'])
        rules.append({'id': rule['id'], 'name': rule['name'], 'enabled': rule['enabled'], 'priority': rule['priority'],
                      'matches': len(matching), 'wins': len(winning), 'overridden': len(matching) - len(winning),
                      'unknown': sum(t is not None and t['matched'] is None for _, t in traces),
                      'auto_count': len(auto_wins), 'payout_cents': sum(payout(r['candidate']) for r in auto_wins),
                      'new_auto': sum(r in new for r in auto_wins),
                      'reviewed_auto': sum(reference_known(r, mode) for r in auto_wins),
                      'overpayment_cases': sum(reference_known(r, mode) and payout(r['candidate']) > r['label']['allowed_cents'] for r in auto_wins),
                      'overlaps': [{'id': rid, 'count': count} for rid, count in overlap.most_common()],
                      'request_ids': [r['id'] for r in winning]})
    dates = sorted(r['data']['requested_at'] for r in rows if r['data'].get('requested_at'))
    critical = sum(bool((r.get('label') or {}).get('critical')) for r in rows)
    quality = {'total': len(rows), 'distinct_customers': len({r['data']['customer_id'] for r in rows if r['data'].get('customer_id')}),
               'missing_customers': sum(not r['data'].get('customer_id') for r in rows),
               'invalid': sum(bool(r['data'].get('errors')) for r in rows), 'conflicts': sum(bool(r.get('conflict')) for r in rows),
               'complete_evidence': sum(bool(r.get('evidence', {}).get('complete')) for r in rows),
               'evidence_methods': dict(Counter('live' for r in rows if r.get('evidence', {}).get('method') == 'live')),
               'blocked_by_evidence': sum(r['candidate']['reason_code'] in ('analysis_incomplete', 'unknown_rule_input') for r in rows),
               'reference_count': sum(reference_known(r, mode) for r in rows),
               'late_references': sum(bool(r.get('label')) and not r['label'].get('captured_before_review', True) for r in rows) if mode == 'shadow' else 0,
               'outcome_notes': sum(adverse(r)['note_recorded'] for r in rows),
               'unknown_outcomes': sum(not adverse(r)['note_recorded'] for r in rows),
               'date_from': dates[0] if dates else None, 'date_to': dates[-1] if dates else None}
    criteria = [
        {'label': 'Recorded critical findings', 'actual': critical, 'required': 0, 'unit': 'count', 'status': 'fail' if critical else 'pass', 'detail': 'Zero recorded findings does not prove all possible failures were tested.'},
        {'label': 'Automatic proposals above the payment cap', 'actual': b['cap_exceedances'], 'required': 0, 'unit': 'count', 'status': 'fail' if b['cap_exceedances'] else 'pass', 'detail': 'Every proposed automatic amount must fit the saved execution limit.'},
        {'label': 'Automatic proposals reviewed', 'actual': b['review_coverage'], 'required': 1, 'unit': 'percent', 'status': 'pass' if mode == 'shadow' and b['auto_count'] and b['reviewed_auto'] == b['auto_count'] else 'unknown', 'detail': 'Same-input human reference captured after the prediction. Historical decisions cannot qualify a release.'},
        {'label': 'Reviewed customer groups', 'actual': b['reviewed_customer_groups'] if mode == 'shadow' else None, 'required': settings['min_prospective_auto'], 'unit': 'count', 'status': 'pass' if mode == 'shadow' and b['reviewed_customer_groups'] >= settings['min_prospective_auto'] else 'unknown', 'detail': f'With zero errors, at least {group_target} independent groups are needed for the configured error bound.'},
        {'label': 'Upper overpayment error rate', 'actual': b['error_upper_95'], 'required': settings['max_error_bps'] / 10000, 'unit': 'percent', 'status': 'unknown' if b['error_upper_95'] is None else 'pass' if b['error_upper_95'] * 10000 <= settings['max_error_bps'] else 'fail', 'detail': 'One-sided 95% bound on customer groups with any excess above the reviewer amount; not a chargeback probability.'},
        {'label': 'Future overpayment stress', 'actual': stress, 'required': settings['max_projected_loss_cents'], 'unit': 'money', 'status': 'unknown' if stress is None else 'pass' if stress <= settings['max_projected_loss_cents'] else 'fail', 'detail': f"Next {settings['projection_cases']} automatic approvals, at the saved per-payment cap and upper error bound. A scenario, not a guarantee."},
    ]
    eligible = mode == 'shadow' and metadata.get('scope') == 'prospective' and not metadata.get('comparison_only')
    if not rows:
        for criterion in criteria: criterion['status'] = 'unknown'
    if not eligible:
        for criterion in criteria: criterion['release_eligible'] = False
    metadata['qualification_eligible'] = eligible
    return {'mode': mode, 'metadata': metadata, 'quality': quality, 'baseline': a, 'candidate': b, 'newly_automatic': newly,
            'changes': {'new_auto': len(new), 'new_auto_cents': new_exposure, 'returned_to_review': len(returned),
                        'returned_cents': sum(payout(r['baseline']) for r in returned),
                        'route_changed': sum(route(r['baseline']) != route(r['candidate']) for r in rows),
                        'reason_or_rule_only': sum(c['changed'] and route(r['baseline']) == route(r['candidate']) and payout(r['baseline']) == payout(r['candidate']) for c, r in zip(cases, rows)),
                        'changed_amount': sum(payout(r['baseline']) != payout(r['candidate']) and route(r['baseline']) == route(r['candidate']) for r in rows),
                        'fraud_to_auto': sum(route(r['baseline']) == 'fraud' and route(r['candidate']) == 'auto_approve' for r in rows)},
            'transitions': [{'from': k[0], 'to': k[1], **v} for k, v in sorted(transitions.items())],
            'safety': {'critical': critical, 'paired_auto_reference_count': len(paired), 'paired_excess_delta_cents': excess_delta,
                       'known_chargebacks': sum(adverse(r)['chargeback'] for r in rows),
                       'new_auto_chargebacks': sum(adverse(r)['chargeback'] for r in new),
                       'chargebacks_sent_to_review': sum(adverse(r)['chargeback'] for r in returned),
                       'appeals_overturned': sum(adverse(r)['overturned'] for r in rows),
                       'chargeback_probability': None, 'chargeback_loss_cents': None,
                       'chargeback_fee_only_cents': 2500 * sum(adverse(r)['chargeback'] for r in rows),
                       'clean_groups_needed_if_no_more_errors': max(0, group_target - b['reviewed_customer_groups']) if not b['group_errors'] and mode == 'shadow' else None},
            'workload': {**{k: round(v, 2) for k, v in minutes.items()}, 'net_minutes_freed': round(minutes['saved'] - minutes['added'], 2),
                         'review_queue_delta': b['routes']['review'] - a['routes']['review'], 'fraud_queue_delta': b['routes']['fraud'] - a['routes']['fraud']},
            'money': {'labor_delta_cents': savings, 'shared_ai_cost_cents': shared_ai, 'extra_ai_cost_cents': extra_ai,
                      'audit_delta_cents': audit_delta, 'operating_margin_cents': operating_margin,
                      'new_auto_review_reference_excess_cents': new_excess,
                      'net_against_correct_review_cents': operating_margin - new_excess if mode == 'shadow' and len(new) == len(reviewed_new) and new else None,
                      'new_auto_break_even_error_rate': break_even, 'stress_loss_cents': stress,
                      'measured_roi_cents': None, 'assumptions': settings},
            'criteria': criteria, 'segments': segments, 'rules': rules, 'cases': cases,
            'policy_changes': policy_diff(baseline_policy, candidate_policy),
            'limitations': [
                'Workload, reference disagreements, monetary exposure and uncertainty describe different trade-offs. The manager chooses the balance; this report does not rank or recommend versions.',
                'Historical decisions are fallible observations. Agreement, including agreement with Current, is not accuracy.',
                'Blank outcomes remain unknown regardless of record age. Outcome notes have no complete follow-up window; a calibrated chargeback rate cannot be inferred.',
                'Requested refund amount is not the order amount. Full chargeback loss and processor-risk thresholds are unavailable; the $25 fee is only a partial scenario.',
                'Routing an adverse case to a reviewer is additional scrutiny, not a proven prevented loss. Shadow makes no candidate payments and cannot establish causal ROI.',
                'Reviewer judgments may be influenced by Current. Candidate outputs are hidden, but these are not fully blind ground-truth labels.',
                'Confidence bounds assume representative independent customer groups. Repeated customers are grouped; shared carrier incidents can still create dependence. Segment bounds are exploratory, not simultaneous guarantees.',
                'A fixed-sample 95% bound is not a sequential-testing guarantee. Do not keep looking until it passes; retain the observation window and review schedule agreed before Shadow.',
                'Historical replay is exploratory development evidence, not a held-out test. Free-text notes have no timestamps proving they were available at decision time. Complete extraction does not prove fact accuracy.',
            ]}


def shadow_reports(observations, baseline, candidate, settings, metadata=None):
    rows = observation_rows(observations)
    return {scope: build_report([r for r in rows if scope == 'all' or r['cohort'] == scope], baseline, candidate, settings,
                                mode='shadow', metadata={**(metadata or {}), 'scope': scope})
            for scope in ('prospective', 'backlog', 'all')}
