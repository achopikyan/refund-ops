"""Explicit cost assumptions and conservative risk estimates; no model confidence scores."""
from math import exp, lgamma, log, log1p, ceil
from pydantic import BaseModel, ConfigDict, Field


class ExecutionLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    max_single_cents: int = Field(default=10000, ge=1, le=1000000000)
    daily_cents: int = Field(default=50000, ge=1, le=1000000000)
    customer_daily_cents: int = Field(default=20000, ge=1, le=1000000000)
    release_cents: int = Field(default=100000, ge=1, le=1000000000)
    release_count: int = Field(default=100, ge=1, le=1000000)


def policy_execution_limits(c, pid, policy):
    if policy.get('execution_limits') is not None: return policy['execution_limits']
    # Old versions stored limits in their checks/release. Show those exact values
    # instead of silently substituting defaults or rewriting historical records.
    row=c.execute('SELECT settings FROM release_limits WHERE policy_id=?',(pid,)).fetchone()
    if not row:
        row=c.execute('''SELECT e.settings FROM experiments e LEFT JOIN trial_sources s ON s.experiment_id=e.id
            WHERE s.policy_id=? OR e.activated_policy_id=? ORDER BY e.rowid DESC LIMIT 1''',(pid,pid)).fetchone()
    if row:
        import json
        settings=json.loads(row[0])
        return {key:settings[key] for key in ExecutionLimits.model_fields}
    return ExecutionLimits().model_dump()


class ShadowRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    min_prospective_auto: int = Field(default=30, ge=1, le=10000)
    min_changed_cases: int = Field(default=5, ge=0, le=10000)
    min_shadow_hours: float = Field(default=24.0, ge=0, le=8760)
    max_error_bps: int = Field(default=1000, ge=1, le=10000)
    projection_cases: int = Field(default=100, ge=1, le=100000)
    max_projected_loss_cents: int = Field(default=100000, ge=0, le=1000000000)


class CostAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    hourly_cost_cents: int = Field(default=3000, ge=0, le=1000000)
    review_minutes: float = Field(default=8.0, gt=0, le=120)
    ai_cost_cents: int = Field(default=2, ge=0, le=10000)
    audit_cost_cents: int = Field(default=100, ge=0, le=100000)
    audit_fraction: float = Field(default=0.1, ge=0, le=1)


class ReleaseSettings(ExecutionLimits, ShadowRequirements, CostAssumptions):
    pass


def error_upper(errors: int, total: int, alpha: float = .05) -> float | None:
    """Exact one-sided Clopper-Pearson bound; exchangeable Bernoulli cases assumed."""
    if not total:
        return None
    if errors == total:
        return 1.0
    if errors == 0:
        return 1 - alpha ** (1 / total)
    def cdf(p):
        logs = [lgamma(total + 1) - lgamma(k + 1) - lgamma(total - k + 1)
                + k * log(p) + (total - k) * log1p(-p) for k in range(errors + 1)]
        largest = max(logs)
        return exp(largest) * sum(exp(v - largest) for v in logs)
    low, high = errors / total, 1.0 - 1e-14
    for _ in range(55):
        mid = (low + high) / 2
        if cdf(mid) > alpha:
            low = mid
        else:
            high = mid
    return high


def proposal_amount(evaluation):
    return evaluation.get("proposed_amount_cents", 0) or 0 if evaluation["action"] == "auto_approve" else 0


def financial_report(observations: list[dict], settings: dict) -> dict:
    prospective = [o for o in observations if o["cohort"] == "prospective"]
    auto = [o for o in prospective if o["candidate"]["action"] == "auto_approve"]
    reviewed = [o for o in auto if o.get("label") and o["label"]["allowed_cents"] is not None
                and o['label'].get('captured_before_review', True)]
    new_auto = [o for o in auto if o["baseline"]["action"] != "auto_approve"]
    returned = [o for o in prospective if o['baseline']['action']=='auto_approve' and o['candidate']['action']!='auto_approve']
    over = lambda o, key: max(0, proposal_amount(o[key]) - o["label"]["allowed_cents"])
    candidate_loss = sum(over(o, "candidate") for o in reviewed)
    baseline_loss = sum(over(o, "baseline") for o in reviewed)
    errors = sum(over(o, "candidate") > 0 for o in reviewed)
    # Repeated applications by one customer must not masquerade as independent evidence.
    groups = {}
    for o in auto:
        if o['snapshot']['data'].get('customer_id'):
            groups.setdefault(o["snapshot"]["data"]["customer_id"], []).append(o)
    checked_groups = [g for g in groups.values() if all(o in reviewed for o in g)]
    group_errors = sum(any(over(o, "candidate") > 0 for o in g) for g in checked_groups)
    upper = error_upper(group_errors, len(checked_groups))
    projection = settings["projection_cases"]
    projected = ceil(upper * projection * settings["max_single_cents"]) if upper is not None else None
    # Upper loss envelope is conditional on future cases being represented by the cohort.
    # It is deliberately based on maximum permitted severity, not mean request amount.
    savings = round((len(new_auto) - len(returned)) * settings["review_minutes"] / 60 * settings["hourly_cost_cents"])
    operating = round(len(prospective) * settings["ai_cost_cents"] + len(auto) * settings["audit_fraction"] * settings["audit_cost_cents"])
    all_new_labelled = all(o in reviewed for o in new_auto)
    new_overpayment = sum(over(o, "candidate") for o in new_auto if o in reviewed)
    checked = [o for o in prospective if o.get("label")]
    return {
        "prospective": len(prospective), "backlog": len(observations) - len(prospective),
        "candidate_auto": len(auto), "new_auto": len(new_auto), 'returned_to_review':len(returned), "reviewed_auto": len(reviewed),
        "changed": sum(o["baseline"]["action"] != o["candidate"]["action"] for o in prospective),
        "critical": sum(o["label"]["critical"] for o in checked),
        "candidate_payout_cents": sum(proposal_amount(o["candidate"]) for o in auto),
        "unreviewed_cents": sum(proposal_amount(o["candidate"]) for o in auto if o not in reviewed),
        "candidate_overpayment_cents": candidate_loss, "baseline_overpayment_same_cases_cents": baseline_loss,
        "error_count": errors, "error_rate": errors / len(reviewed) if reviewed else None,
        "reviewed_customer_groups": len(checked_groups), "customer_groups_with_error": group_errors,
        "error_upper_95": upper, "projected_loss_upper_cents": projected,
        "scenario_labor_savings_cents": savings, "scenario_operating_cost_cents": operating,
        "scenario_net_on_observed_cases_cents": savings - operating - new_overpayment if all_new_labelled and new_auto else None,
        "unknown_outcome_policy": "Unknown is not success. Chargeback prevention and customer impact are not inferred.",
        "projection_assumption": "One-sided 95% bound on customer groups with any overpayment × future approvals × maximum allowed payout. Repeated customers count once. This conservative scenario assumes representative independent customer groups; distribution shifts weaken it.",
        "economic_assumption": "Labor, AI and recurring audit costs are configured scenarios. Net scenario covers additional automatic approvals against an adjudicated correct-review benchmark, not measured human error. Baseline overpayment covers automatic proposals only. This is not measured ROI or a forecast of chargebacks.",
        "chargeback_fee_reference_cents": 2500,
    }
