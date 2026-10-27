"""Pure normalization, evidence validation, and policy evaluation."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .financial import ExecutionLimits

REASONS = {"wrong_size", "changed_mind", "arrived_damaged", "wrong_item", "never_arrived", "late_delivery"}
COLUMNS = "request_id requested_at customer_id tenure_months prior_refunds_12m amount_usd category payment_method stated_reason customer_note support_note days_since_delivery fraud_flag decision decided_by outcome_note decided_at review_minutes".split()
FACTS = {"effective_reason", "already_refunded", "fraud_reported", "fraud_confirmed", "our_error", "matches_order", "photo", "proof_delivery", "investigation", "cosmetic", "customer_damage", "reason_conflict", "injection", "location", "delivered", "video", "partial_damage", "no_product_damage", "batch_defect", "carrier_delay", "address_mismatch"}
BOOLEAN_FACTS = FACTS - {"effective_reason", "location"}
STAFF_FACTS = {"fraud_confirmed", "our_error", "photo", "proof_delivery", "investigation", "matches_order", "video", "batch_defect"}
CONTEXT_FIELDS = {'requested_at','amount_cents','category','payment_method','tenure_months',
                  'prior_refunds_12m','days_since_delivery','fraud_flag','stated_reason'}

def instruction_attempt(text):
    """Conservative tripwire; not a claim to detect every possible injection."""
    return re.search(r'SYSTEM NOTE|skip human review|ignore (?:all |previous |prior )?instructions|'
                     r'ignore (?:the )?(?:policy|rules)|(?:system|developer|assistant)\s*(?:message|prompt|:)|'
                     r'<\|(?:im_start|system|assistant)|\[INST\]|reveal.{0,30}(?:prompt|secret|key)|'
                     r'игнориру[йя].{0,30}(?:инструк|правил)|не следуй.{0,20}инструк|'
                     r'выполни.{0,20}(?:команд|инструк)|override.{0,20}(?:policy|rules)|'
                     r'ignora(?:r)?\s+(?:(?:todas|las|estas|anteriores)\s+){0,4}(?:instrucciones|reglas)|'
                     r'ignoriere\s+(?:(?:alle|die|bisherigen|vorherigen)\s+){0,4}(?:anweisungen|regeln)|'
                     r'התעלם\s+(?:מכל\s+)?(?:מההוראות|ההוראות|מהכללים)', text or '', re.I)
def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()

def money(value: str | int | Decimal) -> int:
    s = str(value).strip()
    if not re.fullmatch(r"(?:USD\s*|\$\s*)?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?(?:\s*USD)?", s, re.I):
        raise ValueError("Use a positive USD amount with at most two decimal places.")
    try:
        v = Decimal(re.sub(r"USD|\$|,|\s", "", s, flags=re.I))
        if v <= 0 or v > 10000000:
            raise ValueError("Amount must be greater than zero and no more than $10,000,000.")
        return int(v * 100)
    except InvalidOperation as e:
        raise ValueError("Invalid amount.") from e

def normalize(raw: dict[str, str], date_format: str = "DMY") -> dict:
    r: dict[str, Any] = {k: str(raw.get(k, "") or "").strip() for k in COLUMNS}
    errors, warnings = [], []
    for k in ("request_id", "customer_id"):
        if not r[k]:
            errors.append(f"Missing {k}")
    try:
        r["amount_cents"] = money(r["amount_usd"])
    except ValueError as e:
        r["amount_cents"] = None
        errors.append(str(e))
    for k in ("tenure_months", "prior_refunds_12m", "days_since_delivery"):
        value = r[k]
        if not value:
            r[k] = None
            warnings.append(f"{k} is unknown")
        elif not re.fullmatch(r"\d+", value):
            r[k] = None
            errors.append(f"{k} must be a non-negative integer")
        else:
            r[k] = int(value)
    flag = r["fraud_flag"].lower()
    r["fraud_flag"] = True if flag in ("yes","y","true","1") else False if flag in ("no","n","false","0") else None
    if r["fraud_flag"] is None:
        warnings.append("Fraud flag is unknown")
    aliases = {"damaged":"arrived_damaged", "late":"late_delivery"}
    reason = re.sub(r"\s+", "_", r["stated_reason"].lower())
    r["stated_reason"] = aliases.get(reason, reason)
    if r["stated_reason"] not in REASONS:
        errors.append("Unknown stated reason")
    for k, allowed in (("category", {"apparel","home","electronics"}), ("payment_method", {"card","paypal"})):
        r[k] = r[k].lower()
        if r[k] not in allowed:
            errors.append(f"Unknown {k}")
    try:
        d = r["requested_at"]
        if "/" in d:
            if date_format not in ("DMY", "MDY"):
                raise ValueError("Choose DMY or MDY for slash-separated dates")
            d = datetime.strptime(d, "%d/%m/%Y" if date_format == "DMY" else "%m/%d/%Y").date().isoformat()
            warnings.append(f"Date interpreted as {date_format}")
        else:
            d = datetime.fromisoformat(d.replace("Z", "+00:00")).date().isoformat()
        r["requested_at"] = d
    except (ValueError, TypeError):
        errors.append("Invalid or ambiguous requested_at")
    r["errors"], r["warnings"] = errors, warnings
    return r

def parse_csv(text: str, date_format: str = "DMY") -> list[dict]:
    if len(text.encode("utf-8")) > 10 * 1024 * 1024:
        raise ValueError("CSV exceeds 10 MB.")
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff"), newline=""))
    missing = set(COLUMNS) - set(reader.fieldnames or [])
    if missing:
        raise ValueError("Missing columns: " + ", ".join(sorted(missing)))
    result = []
    for line, raw in enumerate(reader, 2):
        if line > 10001:
            raise ValueError("CSV exceeds 10,000 rows.")
        if None in raw:
            raise ValueError(f"Too many columns on row {line}. Check CSV quoting.")
        result.append({"line": line, "raw": raw, "normalized": normalize(raw, date_format), "hash": fingerprint(raw)})
    return result

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Fact(Strict):
    name: str
    value: str
    source: Literal["customer_note","support_note"]
    quote: str
    context_fields: list[str] = []

class Extraction(Strict):
    facts: list[Fact]
    summary: str
    assessed_facts: list[str] = []

def validate_evidence(r: dict, output: dict, method: str, criteria: list[dict] | None = None) -> dict:
    parsed = Extraction.model_validate(output)
    allowed = FACTS | {"semantic." + x["id"] for x in (criteria or [])}
    facts, issues = {}, []
    for f in parsed.facts:
        if set(f.context_fields) - CONTEXT_FIELDS:
            issues.append(f"Unsupported context field for {f.name}")
            continue
        if f.name not in allowed:
            issues.append(f"Unsupported fact: {f.name}")
            continue
        if not f.quote.strip() or f.quote not in str(r.get(f.source, "")):
            issues.append(f"Source quotation could not be verified for {f.name}")
            continue
        if f.name.startswith("semantic."):
            criterion=next((x for x in (criteria or []) if "semantic."+x["id"]==f.name),None)
            if criterion and f.source not in criterion["sources"]:
                issues.append(f"Source is not allowed for {f.name}")
                continue
        if (f.name in BOOLEAN_FACTS or f.name.startswith("semantic.")) and f.value not in ("yes", "no", "unknown"):
            issues.append(f"Invalid value for {f.name}")
            continue
        if f.name == "effective_reason" and f.value not in REASONS:
            issues.append("Invalid effective reason")
            continue
        item = f.model_dump()
        item['context'] = {key:r.get(key) for key in f.context_fields}
        if f.name in STAFF_FACTS and f.value == "yes" and f.source != "support_note":
            item["value"] = "unknown"
            item["note"] = "Customer statement is not staff confirmation"
        if f.name in facts and facts[f.name]["value"] != item["value"]:
            item["value"] = "unknown"
            item["note"] = "Conflicting statements"
        facts[f.name] = item
    return {"facts": facts, "summary": parsed.summary, "issues": issues, "method": method,
            "complete": not issues and method == "live", "fingerprint": fingerprint(output),
            "assessed_facts": parsed.assessed_facts}

def pending_evidence(r: dict) -> dict:
    """No model result exists yet. Never infer semantic facts from text locally."""
    return {"facts": {}, "summary": "Automatic evidence analysis is pending.",
            "issues": [], "method": None, "complete": False, "assessed_facts": []}


def contradictory_conditions(conditions):
    """Find impossible AND conditions without treating unknown as a matching value."""
    groups = {}
    for condition in conditions:
        groups.setdefault(condition.field, []).append(condition)
    for field, group in groups.items():
        numeric = FIELD_CATALOG.get(field, {}).get('type') == 'integer'
        allowed = None
        lower, upper = 0, float('inf')
        forbidden = set()
        for c in group:
            v = c.value
            if c.op in ('eq', 'in'):
                values = v if c.op == 'in' and isinstance(v, list) else [v]
                if any(isinstance(x, list) for x in values): continue
                values = set(values)
                allowed = values if allowed is None else allowed & values
            elif c.op == 'ne' and not isinstance(v, list): forbidden.add(v)
            if numeric and type(v) is int:
                if c.op in ('gt', 'gte'): lower = max(lower, v + (c.op == 'gt'))
                if c.op in ('lt', 'lte'): upper = min(upper, v - (c.op == 'lt'))
        if lower > upper: return field
        if allowed is not None:
            allowed -= forbidden
            if numeric: allowed = {v for v in allowed if type(v) is int and lower <= v <= upper}
            if not allowed: return field
    return None

class Condition(Strict):
    field: str
    op: Literal["eq","ne","gt","gte","lt","lte","in"]
    value: str | int | bool | list[str] | list[int] | None

class Rule(Strict):
    id: str
    name: str
    priority: int = Field(ge=0, le=1000)
    conditions: list[Condition]
    match: Literal["all","any"] = "all"
    action: Literal["auto_approve","review","fraud","information","hold"]
    enabled: bool = True
    reason_code: str = "policy_rule"
    reason: str = ""

class Criterion(Strict):
    id: str
    question: str
    sources: list[Literal["customer_note","support_note"]]

def policy_content(data):
    """Read legacy policy records without the retired descriptive metadata."""
    return {'execution_limits':None, **{key:value for key,value in data.items() if key not in {'description','small_customer_enabled','small_amount_cents','minimum_tenure','maximum_prior_refunds'}}} if isinstance(data,dict) else data


class PolicyChecks(Strict):
    evidence_analysis: bool = True
    previous_refund: bool = True
    untrusted_instructions: bool = True
    fraud_reports: bool = True
    customer_history: bool = True
    item_mismatch: bool = True
    damage_origin: bool = True
    reason_consistency: bool = True
    change_mind_window: bool = True
    damage_photo: bool = True
    partial_damage: bool = True
    cosmetic_damage: bool = True
    late_delivery: bool = True
    delivery_proof: bool = True


class Policy(Strict):
    name: str = 'Policy version'
    checks: PolicyChecks = Field(default_factory=PolicyChecks)
    @model_validator(mode='before')
    @classmethod
    def discard_legacy_description(cls, data):
        return policy_content(data)
    change_mind_days: int = Field(default=14,ge=0,le=365)
    damage_photo_above_cents: int = Field(default=5000,ge=0,le=1000000000)
    rules: list[Rule]
    criteria: list[Criterion] = []
    automation_enabled: bool = True
    execution_limits: ExecutionLimits | None = None

def initial_policy() -> dict:
    return Policy(name="Careful start",
        rules=[
            Rule(id="amount-limit",reason_code="high_value",name="Review amounts above $300",priority=900,conditions=[Condition(field="amount_cents",op="gt",value=30000)],action="review"),
            Rule(id="confirmed-card",reason_code="confirmed_stolen_card",name="Confirmed stolen card — full refund",priority=800,conditions=[Condition(field="facts.fraud_confirmed",op="eq",value="yes")],action="auto_approve"),
            Rule(id="fraud-review",reason_code="fraud_confirmation_required",name="Payment risk goes to fraud team",priority=700,conditions=[Condition(field="fraud_flag",op="eq",value=True)],action="fraud"),
            Rule(id="our-error",reason_code="confirmed_merchant_error",name="Confirmed fulfilment error — full refund",priority=600,conditions=[Condition(field="facts.our_error",op="eq",value="yes")],action="auto_approve"),
        ], criteria=[]).model_dump()

from .catalog import FIELD_CATALOG, REASONS as ROUTING_REASONS
FIELDS = set(FIELD_CATALOG)
def validate_policy(data: dict) -> tuple[dict,list[str]]:
    p = Policy.model_validate(data)
    issues = []
    ids = [r.id for r in p.rules]
    if len(ids) != len(set(ids)):
        issues.append("Rule IDs must be unique")
    ci = [c.id for c in p.criteria]
    if len(ci) != len(set(ci)):
        issues.append("Criterion IDs must be unique")
    for c in p.criteria:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,49}", c.id) or not c.sources or not c.question.strip():
            issues.append("Semantic criteria need a valid ID, question and source")
    priorities = {}
    for r in p.rules:
        if r.reason_code not in ROUTING_REASONS:issues.append(f"{r.name}: choose a supported routing reason")
        if not r.enabled:
            continue
        if not r.conditions:
            issues.append(f"{r.name}: at least one condition is required")
        priorities.setdefault(r.priority, set()).add(r.action)
        for c in r.conditions:
            valid = c.field in FIELDS or c.field.removeprefix("facts.") in FACTS and c.field.startswith("facts.") or c.field in {"facts.semantic."+x for x in ci}
            if not valid:
                issues.append(f"{r.name}: unsupported field {c.field}")
            numeric = FIELD_CATALOG.get(c.field, {}).get("type") == "integer"
            if c.op in ("gt","gte","lt","lte") and (not numeric or type(c.value) is not int):
                issues.append(f"{r.name}: numeric comparison requires an integer numeric field")
            if c.op == "in" and not isinstance(c.value, list):
                issues.append(f"{r.name}: 'in' requires a list")
            if c.field=="fraud_flag" and (c.op not in ("eq","ne") or type(c.value) is not bool):
                issues.append(f"{r.name}: fraud_flag requires a boolean equality")
            if numeric and c.op in ("eq","ne") and type(c.value) is not int:
                issues.append(f"{r.name}: numeric equality requires an integer")
            if c.op == 'in' and isinstance(c.value,list):
                if not c.value or any(type(v) is not (int if numeric else str) for v in c.value):
                    issues.append(f"{r.name}: choose a non-empty list of correctly typed values")
            if numeric and (type(c.value) is int and c.value < 0 or isinstance(c.value,list) and any(type(v) is int and v < 0 for v in c.value)):
                issues.append(f"{r.name}: numeric values cannot be negative")
            choices = (REASONS if c.field in ('stated_reason','facts.effective_reason') else
                       {'apparel','home','electronics'} if c.field == 'category' else
                       {'card','paypal'} if c.field == 'payment_method' else
                       {'yes','no','unknown'} if c.field.startswith('facts.') and c.field != 'facts.location' else None)
            if choices is not None:
                values = c.value if isinstance(c.value,list) else [c.value]
                if any(not isinstance(v,str) or v not in choices for v in values):
                    issues.append(f"{r.name}: choose supported values for {c.field}")
            elif not numeric and c.field != 'fraud_flag' and c.op in ('eq','ne') and not isinstance(c.value,str):
                issues.append(f"{r.name}: text equality requires a text value")
        if r.match == 'all' and (field := contradictory_conditions(r.conditions)):
            issues.append(f"{r.name}: contradictory conditions for {field}")
    for priority, actions in priorities.items():
        if len(actions) > 1:
            issues.append(f"Priority {priority} has conflicting actions; choose distinct priorities")
    return p.model_dump(), issues

def compare(condition: dict, r: dict, facts: dict) -> bool | None:
    field, op, expected = condition["field"], condition["op"], condition["value"]
    value = facts.get(field[6:], {}).get("value") if field.startswith("facts.") else r.get(field)
    if value is None or value == "unknown":
        return None
    try:
        return {"eq": lambda: value == expected, "ne": lambda: value != expected,
                "gt": lambda: value > expected, "gte": lambda: value >= expected,
                "lt": lambda: value < expected, "lte": lambda: value <= expected,
                "in": lambda: value in expected}[op]()
    except TypeError:
        return None

def condition_trace(condition, r, facts, evaluated=True):
    field = condition['field']
    fact = facts.get(field[6:], {}) if field.startswith('facts.') else {}
    actual = fact.get('value') if field.startswith('facts.') else r.get(field)
    return {**condition, 'actual': actual, 'matched': compare(condition, r, facts) if evaluated else None,
            'evaluated': evaluated, 'source': fact.get('source', 'request' if not field.startswith('facts.') else 'missing'),
            'quote': fact.get('quote', '')}

def condition_match(values, mode):
    """Three-valued matching after every condition has been evaluated."""
    if not values:
        return None  # Invalid empty rules cannot authorize by vacuous truth.
    if mode == 'all':
        return False if False in values else None if None in values else True
    return True if True in values else None if None in values else False


def evaluate_rules(r, facts, rules):
    """Evaluate every enabled rule independently of the eventual decision."""
    trace, disabled = [], []
    ordered = sorted(enumerate(rules), key=lambda item: (-item[1]['priority'], item[0]))
    for order, rule in ordered:
        enabled = rule['enabled']
        conditions = [condition_trace(c, r, facts, enabled) for c in rule['conditions']]
        matched = condition_match([c['matched'] for c in conditions], rule['match']) if enabled else None
        item = {'rule':rule['name'], 'rule_id':rule['id'], 'priority':rule['priority'],
                'policy_order':order + 1, 'match':rule['match'], 'action':rule['action'],
                'matched':matched, 'status':'disabled' if not enabled else 'matched' if matched is True else 'unknown' if matched is None else 'no_match',
                'conditions':conditions}
        (trace if enabled else disabled).append(item)
    return trace, disabled


def resolve_rule_matches(trace):
    """Priority chooses among matches and unresolved restrictive contenders.

    Equal priorities with one action retain declared policy order. Conflicting
    top actions fail closed even if a legacy policy bypassed validation.
    """
    contenders = [t for t in trace if t['matched'] is True or t['matched'] is None and t['action'] != 'auto_approve']
    if not contenders:
        return {'kind':'fallback', 'selected':None, 'contenders':[]}
    priority = contenders[0]['priority']
    top = [t for t in contenders if t['priority'] == priority]
    if len({t['action'] for t in top}) > 1:
        return {'kind':'priority_conflict', 'selected':None, 'contenders':top}
    selected = top[0]
    return {'kind':'unknown_rule_input' if selected['matched'] is None else 'priority',
            'selected':selected, 'contenders':top}

def evaluate(r: dict, e: dict, p: dict, conflict: bool = False) -> dict:
    facts = dict(e.get("facts", {}))
    # A cheap instruction-pattern detector remains independent of model output.
    for source in ("customer_note","support_note"):
        if match := instruction_attempt(r.get(source, "")):
            facts["injection"]={"value":"yes", "source":source, "quote":match.group(0)}
    # Semantic evidence is tied to the exact question, not just a reused ID.
    if p.get("criteria") and e.get("criteria_hash")!=fingerprint(p["criteria"]):
        facts={k:v for k,v in facts.items() if not k.startswith("semantic.")}
    def f(name): return facts.get(name, {}).get("value")
    trace, disabled = evaluate_rules(r, facts, p['rules'])
    selection = resolve_rule_matches(trace)
    effective = f('effective_reason') or r.get('stated_reason')
    checks = PolicyChecks.model_validate(p.get('checks',{})).model_dump()
    if not checks['reason_consistency']: effective = r.get('stated_reason')

    def result(action, code, explanation, rule=None, stage='required_check'):
        proposed_action = action
        kind = selection['kind'] if stage == 'rule' else stage
        gate = code if stage == 'required_check' else None
        if action=="auto_approve" and not p.get("automation_enabled",True):
            action,code,explanation="review","setup_required","The first policy must pass backtest, prospective Shadow and release review. Manual decisions remain available."
            kind, gate = 'approval_gate', code
        selected = next((t for t in trace if t['rule_id'] == rule), None)
        top = selection['contenders'] if stage == 'rule' else []
        conflicts = [t['rule_id'] for t in top] if kind == 'priority_conflict' else []
        if kind == 'required_check':
            summary = 'All enabled rules were checked. A required check determines the outcome and overrides any rule matches.'
        elif kind == 'approval_gate':
            summary = 'The selected rule proposed automatic approval, but a required approval check prevents it. Other matches cannot bypass that check.' if selected else 'A required approval check prevents automatic approval.'
        elif kind == 'priority_conflict':
            summary = f"Applicable rules at priority {top[0]['priority']} request incompatible actions. The outcome is Review until the policy priorities are corrected."
        elif kind == 'unknown_rule_input':
            summary = f"'{selected['rule']}' at priority {selected['priority']} may apply, but required information is unknown. Lower-priority matches cannot bypass this restrictive rule."
            if len(top) > 1:
                summary += ' Same-priority rules request the same action; declared policy order selects this explanation.'
        elif kind == 'priority':
            summary = f"'{selected['rule']}' has the highest applicable priority ({selected['priority']}) and determines the rule outcome."
            if len(top) > 1:
                summary += ' Same-priority rules request the same action; the first in declared policy order supplies the explanation.'
        else:
            summary = 'No matching rule or unresolved restrictive rule determines the outcome. Requests without an applicable rule go to Review.'
        decisive_rule = rule if selected and kind in ('priority', 'unknown_rule_input') else None
        for item in trace:
            if item['matched'] is False:
                role, detail = 'no_match', 'The conditions do not match this request.'
            elif item['rule_id'] in conflicts:
                role, detail = 'conflict', 'This top-priority contender conflicts with another applicable action. No rule was selected.'
            elif item['rule_id'] == decisive_rule:
                role = 'selected' if item['matched'] is True else 'blocking'
                detail = summary
            elif kind in ('required_check', 'approval_gate'):
                role = 'blocked' if selected and item['rule_id'] == selected['rule_id'] else 'overridden' if item['matched'] is True else 'unknown'
                detail = 'A required check determines the outcome; this rule cannot override it.'
            elif item['matched'] is None:
                role, detail = 'unknown', 'This rule has missing information and does not determine the outcome.'
            elif selected and item['priority'] == selected['priority']:
                role, detail = 'same_action', 'Same priority and same action as the selected rule; declared policy order selects the explanation.'
            else:
                role, detail = 'lower_priority', 'A higher-priority contender determines the outcome.'
            item.update(outcome_role=role, selection_explanation=detail)
        for item in disabled:
            item.update(outcome_role='disabled', selection_explanation='Disabled rules are not evaluated and cannot determine the outcome.')
        resolution = {'strategy':'all_rules_then_priority', 'kind':kind, 'summary':summary,
                      'selected_rule_id':rule if selected else None, 'decisive_rule_id':decisive_rule,
                      'selected_priority':selected['priority'] if selected else None,
                      'matched_rule_ids':[t['rule_id'] for t in trace if t['matched'] is True],
                      'blocking_rule_ids':[decisive_rule] if kind == 'unknown_rule_input' else [],
                      'conflicting_rule_ids':conflicts, 'required_check':gate,
                      'tie_break':'declared_policy_order' if len(top) > 1 and not conflicts else None,
                      'evaluated_count':len(trace), 'disabled_count':len(disabled)}
        return {"action": action, "queue": {"auto_approve":"ready","review":"general","fraud":"fraud","information":"information","hold":"hold"}[action],
                "reason_code": code, "explanation": explanation, "rule_id": rule, "trace":trace,
                "policy_name":p['name'], "remaining_rules":disabled,
                "evaluation_stage":stage, "resolution":resolution,
                "proposed_action":proposed_action,
                "proposed_amount_cents":r.get("amount_cents") if action=="auto_approve" else None,
                "input_fingerprint": fingerprint([r,e,p,conflict])}
    if conflict:
        return result("review","conflicting_versions","Different versions of this request must be reconciled.")
    if r.get("errors"):
        return result("information","invalid_data","Resolve data issues: " + "; ".join(r["errors"]))
    if checks['previous_refund'] and f("already_refunded") == "yes":
        return result("review","possible_previous_refund","The notes report a previous refund. Reconcile before paying.")
    if checks['untrusted_instructions'] and f("injection") == "yes":
        return result("review","untrusted_instruction","Customer text claims authority or attempts to instruct the system. It cannot authorize a refund.")
    if (r.get("fraud_flag") is True or checks['fraud_reports'] and f('fraud_reported') == 'yes') and f("fraud_confirmed")!="yes":
        return result("fraud","fraud_confirmation_required","Flagged payments require the fraud team's assessment. A stolen-card report alone is not confirmation.")
    if checks['customer_history'] and r.get('context_issues'):
        return result('review','customer_history_conflict','; '.join(r['context_issues']))
    # A confirmed stolen-card remedy concerns an unauthorised purchase, not a return.
    # It still needs an explicit rule and every data, evidence, model and execution gate.
    if checks['item_mismatch'] and f('our_error') == 'yes' and f('matches_order') == 'yes':
        return result('review','conflicting_evidence','Staff evidence both confirms a merchant error and says the item matches the order. Reconcile it first.')
    retail_claim = f('fraud_confirmed') != 'yes' and f('our_error') != 'yes'
    if checks['item_mismatch'] and retail_claim and f("matches_order") == "yes" and r.get("stated_reason") == "wrong_item":
        return result("review","conflicting_evidence","Support says the item matches the order; the customer selected wrong item.")
    if checks['damage_origin'] and retail_claim and f("customer_damage") == "yes":
        return result("review","damage_origin","Notes suggest damage after delivery; assess the evidence.")
    if checks['damage_origin'] and retail_claim and f('no_product_damage') == 'yes' and effective == 'arrived_damaged':
        return result('review','no_product_damage','The notes say the product is intact. Verify the actual reason before refunding damage.')
    if checks['delivery_proof'] and retail_claim and effective == "never_arrived" and f("proof_delivery") == "yes" and f("investigation") != "yes":
        return result("review","delivery_proof","Delivery proof is recorded without a confirmed carrier investigation. Review the policy-based refusal.")
    if checks['reason_consistency'] and retail_claim and f("reason_conflict") == "yes" and not f("effective_reason"):
        return result("review","reason_conflict","The selected reason conflicts with the notes.")
    if checks['change_mind_window'] and retail_claim and effective == "changed_mind" and (r.get("days_since_delivery") is None or r["days_since_delivery"] > p.get("change_mind_days",14)):
        return result("review","return_window",f"Change-of-mind returns require a known delivery interval within {p.get('change_mind_days',14)} days. Reviewer should assess refusal.")
    if checks['damage_photo'] and retail_claim and effective == "arrived_damaged" and r["amount_cents"] > p.get("damage_photo_above_cents",5000) and f("photo") != "yes":
        return result("information","photo_required",f"Damage claims above ${p.get('damage_photo_above_cents',5000)/100:g} require a photo confirmed in the evidence.")
    if checks['partial_damage'] and retail_claim and effective == 'arrived_damaged' and f('partial_damage') == 'yes':
        return result('review','partial_damage','Only part of the order is damaged. A reviewer must establish the appropriate refund amount.')
    if checks['cosmetic_damage'] and retail_claim and effective == "arrived_damaged" and f("cosmetic") == "yes":
        return result("review","partial_judgment","Cosmetic damage may merit a partial refund. A reviewer chooses the amount.")
    if checks['late_delivery'] and retail_claim and (effective == "late_delivery" or f("delivered") == "yes" and effective == "never_arrived"):
        return result("review","late_delivery_judgment","Late delivery requires reviewer judgment, including any partial refund.")
    # Resolution consumes the complete trace. It never short-circuits evaluation.
    if selection['kind'] == 'priority_conflict':
        return result('review','conflicting_rule_actions','Applicable rules with the same priority request incompatible actions. Correct the policy priorities before automatic approval.',stage='rule')
    if selection['selected']:
        selected = selection['selected']
        rule = next(x for x in p['rules'] if x['id'] == selected['rule_id'])
        if selected['matched'] is None:
            return result('review','unknown_rule_input',f"Cannot establish whether '{rule['name']}' applies.",rule['id'],stage='rule')
        if rule['action'] == 'auto_approve':
            if checks['evidence_analysis'] and not e.get('complete'):
                return result('review','analysis_incomplete','Complete automatic evidence analysis before an automatic approval.',rule['id'])
            if r.get('fraud_flag') is not False and f('fraud_confirmed') != 'yes':
                return result('fraud','fraud_not_cleared','Payment risk must be resolved before automatic approval.',rule['id'])
        return result(rule['action'],rule.get('reason_code','policy_rule'),rule.get('reason') or rule['name'],rule['id'],stage='rule')
    if r.get("fraud_flag") is not False:
        return result("fraud" if r.get("fraud_flag") else "review","fraud_unknown","Payment risk needs confirmation.")
    if not e.get("complete"):
        return result("review","analysis_incomplete","Automatic evidence analysis is incomplete. A reviewer can assess the source directly.")
    if effective in ("never_arrived","wrong_item"):
        return result("review","evidence_judgment","This reason needs evidence-led review or an explicit matching policy rule.")
    return result('review','outside_automation','No policy rule matched. Review the request.',stage='fallback')


def payment_constraint(r, e, p, action):
    """Policy-note obligations also apply at the human payment boundary.

    Reviewers can verify/correct evidence, but cannot pay through a known unresolved
    duplicate, fraud report, photo requirement or no-exceptions return window.
    """
    f = lambda name: e.get('facts',{}).get(name,{}).get('value')
    checks=PolicyChecks.model_validate(p.get('checks',{})).model_dump()
    if action != 'rejected' and checks['previous_refund'] and f('already_refunded') == 'yes':
        return 'Reconcile the reported previous refund and verify the evidence before paying again.'
    if action != 'rejected' and (r.get('fraud_flag') is True or checks['fraud_reports'] and f('fraud_reported') == 'yes') and f('fraud_confirmed') != 'yes':
        return 'The fraud team must resolve the flagged or reported fraud before payment.'
    if checks['fraud_reports'] and f('fraud_confirmed') == 'yes':
        return None if action == 'approved' else 'Confirmed stolen-card cases require a full refund to the original payment method.'
    if checks['item_mismatch'] and f('our_error') == 'yes' and f('matches_order') != 'yes':
        return None if action == 'approved' else 'Confirmed merchant errors require a full refund.'
    if action != 'rejected':
        effective = (f('effective_reason') if checks['reason_consistency'] else None) or r.get('stated_reason')
        if checks['change_mind_window'] and effective == 'changed_mind' and (r.get('days_since_delivery') is None or r['days_since_delivery'] > p.get('change_mind_days',14)):
            return 'The change-of-mind return window must be verified and satisfied before payment. No exceptions.'
        if checks['damage_photo'] and effective == 'arrived_damaged' and (r.get('amount_cents') or 0) > p.get('damage_photo_above_cents',5000) and f('photo') != 'yes':
            return 'Verify the required damage photo before payment. Video alone does not satisfy the photo requirement.'
        if checks['delivery_proof'] and effective == 'never_arrived' and f('proof_delivery') == 'yes' and f('investigation') != 'yes':
            return 'Delivery proof requires a verified carrier investigation before payment.'
    return None
