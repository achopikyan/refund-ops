"""Read-only descriptive risk signals; no routing authority or invented clean labels."""
import json
import re
from datetime import date
from .financial import error_upper, ReleaseSettings


def financial_scenario(cohort, order_amount_cents, review_minutes=8, hourly_cents=3000,
                       probability=None, stress_probability=None, prevention_fraction=1):
    """Illustrative cost comparison, with explicit assumptions rather than risk labels."""
    if order_amount_cents is not None and order_amount_cents < 0:
        raise ValueError('Order amount cannot be negative')
    if review_minutes < 0 or hourly_cents < 0 or not 0 < prevention_fraction <= 1:
        raise ValueError('Invalid review assumptions')
    rate = cohort['recorded_rate'] if probability is None else probability
    high = error_upper(cohort['chargebacks'], cohort['total']) if stress_probability is None else stress_probability
    if any(p is not None and not 0 <= p <= 1 for p in (rate, high)):
        raise ValueError('Probabilities must be between zero and one')
    fee = 2500
    exposure = order_amount_cents + fee if order_amount_cents is not None else None
    review = round(review_minutes / 60 * hourly_cents)
    return {'order_amount_cents':order_amount_cents, 'fee_cents':fee, 'exposure_cents':exposure,
            'probability':rate, 'stress_probability':high, 'review_minutes':review_minutes, 'hourly_cents':hourly_cents,
            'review_cost_cents':review, 'prevention_fraction':prevention_fraction,
            'estimated_loss_cents':round(rate * exposure) if rate is not None and exposure is not None else None,
            'stress_loss_cents':round(high * exposure) if high is not None and exposure is not None else None,
            'break_even_probability':review / (exposure * prevention_fraction) if exposure else None,
            'assumptions':['Order value initially uses the requested refund as a proxy; replace it if the order total is known.',
                           'The expected scenario uses the recorded chargeback rate. The stress scenario uses its one-sided 95% sampling upper estimate. Neither accounts for unreported outcomes.',
                           'Break-even compares review cost with avoidable loss. The initial 100% prevention assumption is optimistic, not measured review effectiveness.']}


def band(amount):
    if amount is None: return 'Unknown amount'
    return 'Up to $50' if amount <= 5000 else '$50–150' if amount <= 15000 else '$150–300' if amount <= 30000 else 'Above $300'


def assess(request, history, as_of):
    cutoff = min(as_of, request.get('requested_at') or as_of)
    unique = {r['request_id']: r for r in history if r.get('request_id') != request.get('request_id')}
    eligible = [r for r in unique.values() if not r.get('errors') and r.get('requested_at') and r['requested_at'] < cutoff and r.get('decision') in ('approved', 'partial')]
    reason = request.get('stated_reason')
    repeat = request.get('prior_refunds_12m')
    cohorts = [('Same reason, amount band and refund history', [r for r in eligible if r.get('stated_reason') == reason and band(r.get('amount_cents')) == band(request.get('amount_cents')) and repeat is not None and r.get('prior_refunds_12m') is not None and bool(r['prior_refunds_12m']) == bool(repeat)]),
               ('Same reason and amount band', [r for r in eligible if r.get('stated_reason') == reason and band(r.get('amount_cents')) == band(request.get('amount_cents'))]),
               ('Same reason', [r for r in eligible if r.get('stated_reason') == reason]),
               ('All prior approved or partial refunds', eligible)]
    name, selected = next(((name, rows) for name, rows in cohorts if len(rows) >= 10), cohorts[-1])

    def counts(rows):
        known, clean = [], []
        for row in rows:
            note = (row.get('outcome_note') or '').lower()
            # Explicit dates only: do not leak outcomes recorded after the as-of cutoff.
            dates = re.findall(r'\b\d{4}-\d{2}-\d{2}\b', note)
            if not dates or any(d > cutoff for d in dates): continue
            if re.search(r'\b(?:no chargeback|chargeback[- ]free)\b', note): clean.append(row)
            elif re.search(r'\bchargeback\b', note): known.append(row)
        n, k = len(rows), len(known)
        return {'total':n, 'chargebacks':k, 'confirmed_clean':len(clean), 'unknown':n-k-len(clean),
                'recorded_rate':k/n if n else None, 'examples':[{'request_id':r['request_id'],'amount_cents':r['amount_cents'],'note':r['outcome_note']} for r in known[:5]]}
    segment, baseline = counts(selected), counts(eligible)
    elevated = segment['total'] >= 10 and segment['chargebacks'] >= 2 and segment['recorded_rate'] > (baseline['recorded_rate'] or 0) * 1.5
    config=ReleaseSettings()
    times=[float(r['review_minutes']) for r in selected if isinstance(r.get('review_minutes'),(int,float)) and r['review_minutes'] > 0]
    minutes=sum(times)/len(times) if times else config.review_minutes
    scenario=financial_scenario(segment,request.get('amount_cents'),minutes,config.hourly_cost_cents)
    scenario['review_time_source']='Mean recorded review time in this cohort' if times else 'Default review-time assumption'
    return {'advisory_only':True, 'as_of':cutoff, 'segment':name, 'amount_band':band(request.get('amount_cents')),
            'level':'Elevated observed signal' if elevated else 'Limited outcome data' if segment['unknown'] else 'Historical context',
            'cohort':segment, 'baseline':baseline, 'refund_cents':request.get('amount_cents'),
            'expected_loss_cents':None, 'chargeback_fee_cents':2500, 'scenario':scenario,
            'explanation':'Recorded chargebacks divided by prior approved or partial requests. This is an observed reporting rate, not a calibrated probability for this request. Blank outcomes stay unknown.',
            'financial_note':'Chargeback exposure is the order amount plus a $25 fee. Order amount is not supplied, so full loss and expected loss cannot be calculated from the requested refund.',
            'limitations':['Small, selected sample; approval history does not establish causation.', 'Undated or later outcomes are excluded from known outcomes.', 'This module does not change the route, policy or decision.']}


def assess_store(store, rid):
    obj = store.request(rid)
    with store.connect() as c:
        history = [json.loads(row[0]) for row in c.execute('SELECT data FROM history')]
    return assess(obj['data'], history, min(store.state()['as_of'], date.today().isoformat()))
