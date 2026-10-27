"""Bounded, explainable rule discovery. Historical decisions are observations, never labels."""
from copy import deepcopy
from itertools import product
from .domain import fingerprint, pending_evidence, evaluate, validate_policy


def implies(narrow, broad):
    """Conservative implication for the typed conditions used by bounded discovery."""
    if narrow['field'] != broad['field']: return False
    a, b = narrow['value'], broad['value']
    op, target = narrow['op'], broad['op']
    if op == target and a == b: return True
    if op == 'eq':
        if target == 'in': return a in b
        if target == 'ne': return a != b
    if isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(b, (int, float)) and not isinstance(b, bool):
        if target == 'lte': return op in ('eq', 'lte', 'lt') and a <= b
        if target == 'gte': return op in ('eq', 'gte', 'gt') and a >= b
        if target == 'lt': return op in ('eq', 'lte', 'lt') and (a < b or op == 'lt' and a == b)
        if target == 'gt': return op in ('eq', 'gte', 'gt') and (a > b or op == 'gt' and a == b)
    return False


def covered_by(rule, existing):
    """Ignore cosmetic names/IDs and ordering; retain different actions as distinct rules."""
    if rule['action'] != existing['action']: return False
    canonical = lambda r: sorted(fingerprint(c) for c in r['conditions'])
    if rule['match'] == existing['match'] and canonical(rule) == canonical(existing): return True
    if not existing['enabled'] or rule['match'] != 'all': return False
    covered = [any(implies(c, e) for c in rule['conditions']) for e in existing['conditions']]
    return all(covered) if existing['match'] == 'all' else any(covered)


def discover(history: list[dict], baseline: dict, hourly_cents=3000, adverse_bps=500, min_support=5, evidence_provider=None):
    rows = sorted([r for r in history if not r.get("errors")], key=lambda r: (r["requested_at"], r["request_id"]))
    split = max(1, int(len(rows) * .7))
    train, later = rows[:split], rows[split:]
    seen = {r["customer_id"] for r in train}
    validation = [r for r in later if r["customer_id"] not in seen]
    results = []; excluded_existing = 0
    for reason, cap, tenure, prior in product(("wrong_size", "changed_mind", "arrived_damaged"), (2500, 5000, 7500, 10000), (6, 12, 24), (0, 1)):
        def matches(r):
            return (r["stated_reason"] == reason and r["amount_cents"] <= cap and r["fraud_flag"] is False
                    and r["tenure_months"] is not None and r["tenure_months"] >= tenure
                    and r["prior_refunds_12m"] is not None and r["prior_refunds_12m"] <= prior)
        training = [r for r in train if matches(r)]
        if len(training) < min_support:
            continue
        conditions = [{"field": "stated_reason", "op": "eq", "value": reason},
                      {"field": "amount_cents", "op": "lte", "value": cap},
                      {"field": "tenure_months", "op": "gte", "value": tenure},
                      {"field": "prior_refunds_12m", "op": "lte", "value": prior},
                      {"field": "fraud_flag", "op": "eq", "value": False}]
        key = fingerprint(conditions)[:12]
        policy = deepcopy(baseline)
        priority = min([r["priority"] for r in policy["rules"] if r["enabled"]] or [1]) - 1
        # Rule priorities have a schema lower bound. Refuse an unsupported insertion.
        if priority < 0:
            continue
        rule = {"id": "mined-" + key, "name": f"{reason.replace('_', ' ')} up to ${cap / 100:g}", "priority": priority,
                "enabled": True, "match": "all", "conditions": conditions, "action": "auto_approve",
                "reason_code": "small_established_customer", "reason": f"{reason.replace('_', ' ').capitalize()}: within the proposed amount, tenure and refund-history limits."}
        if any(covered_by(rule, old) for old in baseline['rules']):
            excluded_existing += 1
            continue
        # The draft may propose automation; the active manual baseline remains unchanged.
        policy['automation_enabled'] = True
        policy["rules"].append(rule)
        policy["name"] = rule["name"]
        _, issues = validate_policy(policy)
        if issues:
            continue
        def stats(group):
            matched = [r for r in group if matches(r)]
            manual = [r for r in matched if r["decided_by"] != "auto"]
            minutes = sum(float(r["review_minutes"] or 0) for r in manual)
            exposure = sum(r["amount_cents"] for r in manual)
            exact_new = 0
            for r in matched:
                e = evidence_provider(r, baseline['criteria']) if evidence_provider else pending_evidence(r)
                if evaluate(r, e, policy)["action"] == "auto_approve" and evaluate(r, e, baseline)["action"] != "auto_approve":
                    exact_new += 1
            return {"support": len(matched), "historical_manual": len(manual), "already_auto": len(matched) - len(manual),
                    "historical_approved": sum(r["decision"] == "approved" for r in matched),
                    "manual_minutes": minutes, "manual_requested_cents": exposure,
                    "known_chargebacks": sum("chargeback" in r["outcome_note"].lower() for r in matched),
                    "unknown_outcomes": sum(not r["outcome_note"] for r in matched),
                    "labor_opportunity_cents": round(minutes / 60 * hourly_cents),
                    "loss_scenario_cents": round(exposure * adverse_bps / 10000),
                    "worst_case_overpayment_cents": exposure,
                    "executable_increment_with_existing_evidence": exact_new}
        tr, va = stats(train), stats(validation)
        if tr["historical_manual"] == 0:
            continue  # A rediscovery of wholly automatic work offers no additional labor opportunity.
        results.append({"id": key, "rule": rule, "policy": policy, "training": tr, "later_diagnostic": va,
                        "scenario_net_cents": tr["labor_opportunity_cents"] - tr["loss_scenario_cents"],
                        "status": "hypothesis", "support_ids": [r["request_id"] for r in training],
                        "exception_ids": [r['request_id'] for r in training if r['decision'] not in ('approved','auto_approved') or 'chargeback' in r['outcome_note'].lower()]})
    # Ranking uses discovery data only. Later diagnostic results never select the rule.
    results.sort(key=lambda x: (-x["scenario_net_cents"], -x["training"]["historical_manual"], x["id"]))
    return {"candidates": results[:30], "searched": 72, "eligible_candidates": len(results), "excluded_existing": excluded_existing,
            "data_hash": fingerprint(rows), "training_count": len(train), "later_count": len(validation),
            "excluded_repeated_customers": len(later) - len(validation), "excluded_invalid": len(history) - len(rows),
            "assumptions": {"hourly_cost_cents": hourly_cents, "hypothetical_error_bps": adverse_bps, "min_support": min_support},
            "limitations": ["Historical approval is not a correctness label; blank outcomes remain unknown.",
                            "Labor opportunity is an upper opportunity from recorded manual work, not proven savings. Required evidence may still require a reviewer.",
                            "The error percentage is an explicit scenario, not an estimated probability. All requested money is not loss.",
                            "Chronological 70/30 diagnostic with repeated customers removed. These supplied records were already inspected; not a blind holdout.",
                            "Historical notes have no timestamps. Full policy replay can be conservative when note evidence is incomplete.",
                            "Only approved conditions are mined. Mandatory safety checks and higher-priority rules remain in force."]}
