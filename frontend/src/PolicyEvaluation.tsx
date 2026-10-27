import { useQuery } from '@tanstack/react-query';
import { api, Badge, Icon, money, words, ReasonBadge } from './components';
import type { RequestRecord } from './components';
import { RequestSection } from './RequestSections';
import { ActionTag } from './visualLanguage';

type Check = {
  field: string,
  op: string,
  value: unknown,
  actual: unknown,
  matched: boolean | null,
  evaluated: boolean,
  source: string,
  quote: string
};
type RuleTrace = {
  rule: string,
  rule_id: string,
  priority: number,
  policy_order?: number,
  match: string,
  action: string,
  matched: boolean | null,
  status: string,
  conditions: Check[],
  outcome_role?: string,
  selection_explanation?: string
};
type Resolution = {
  strategy: string,
  kind: string,
  summary: string,
  selected_rule_id: string | null,
  decisive_rule_id: string | null,
  selected_priority: number | null,
  matched_rule_ids: string[],
  blocking_rule_ids: string[],
  conflicting_rule_ids: string[],
  required_check: string | null,
  tie_break: string | null,
  evaluated_count: number,
  disabled_count: number
};
type TraceReport = {
  policy_id: string,
  policy_version?: number,
  recorded_decision: boolean,
  evaluation: {
    trace: RuleTrace[],
    remaining_rules: RuleTrace[],
    resolution?: Resolution,
    explanation: string,
    rule_id: string | null,
    evaluation_stage: string,
    action: string,
    reason_code: string,
    reason_label?: string,
    next_action?: string,
    supporting_signals?: string[],
    proposed_action: string
  }
};
const operators: Record<string, string> = {
  eq: 'is',
  ne: 'is not',
  gt: 'more than',
  gte: 'at least',
  lt: 'less than',
  lte: 'at most',
  in: 'one of'
};
const roles: Record<string, string> = {
  selected: 'Determines outcome',
  blocking: 'Missing information blocks selection',
  blocked: 'Approval check overrides',
  overridden: 'Required check overrides',
  lower_priority: 'Lower priority match',
  same_action: 'Same outcome, later in policy order',
  conflict: 'Conflicting top priority',
  unknown: 'Missing information',
  no_match: 'Does not match',
  disabled: 'Disabled'
};

function value(field: string, v: unknown): string {
  return v == null ?
    'Unknown' :
    Array.isArray(v) ?
      v.map(x => value(field, x)).join(', ') :
      field === 'amount_cents' ?
        money(Number(v)) :
        typeof v === 'boolean' ? (v ? 'Yes' : 'No') : words(String(v));
}

function ConditionTable({ checks }: { checks: Check[] }) {
  const { data: catalog = {} } = useQuery({ queryKey: ['catalog'], queryFn: () => api<Record<string, { label: string }>>('/field-catalog') });
  return <div className="condition-table-wrap">
    <table className="case-condition-table">
      <thead><tr><th>Variable</th><th>Required</th><th>This request</th><th>Check</th></tr></thead>
      <tbody>
        {
          checks.map((c, i) => <tr key={i}>
            <td>
              {catalog[c.field]?.label || words(c.field.replace('facts.', ''))}
              <small>{words(c.source)}</small>
            </td>
            <td>{operators[c.op]} {value(c.field, c.value)}</td>
            <td>
              {value(c.field, c.actual)}
              {c.quote && <small className="condition-quote">“{c.quote}”</small>}
            </td>
            <td>
              <span
                className={
                  'condition-result ' + (!c.evaluated ? 'skipped' : c.matched === true ? 'met' : c.matched === false ? 'unmet' : 'unknown')
                }
              >
                {
                  !c.evaluated ?
                    'Not checked' :
                    c.matched === true ? '✓ Met' : c.matched === false ? '✕ Not met' : '? Unknown'
                }
              </span>
            </td>
          </tr>)
        }
      </tbody>
    </table>
  </div>;
}

export function PolicyEvaluation({ request: r }: { request: RequestRecord }) {
  const { data, error } = useQuery({
    queryKey: ['case-policy-evaluation', r.id, r.version],
    queryFn: () => api<TraceReport>('/requests/' + r.id + '/policy-evaluation')
  });
  const ev = data?.evaluation;
  const resolution = ev?.resolution;
  const allRules = resolution?.strategy === 'all_rules_then_priority';
  const unknown = ev?.trace.filter(t => t.matched === null).length || 0;
  const reasonCode = ev?.reason_code === 'policy_rule' && ev.rule_id === 'amount-limit' ?
    'high_value' :
    ev?.reason_code || r.evaluation.reason_code;
  const reasonLabel = ev?.reason_label ||
    (reasonCode === r.evaluation.reason_code ? r.evaluation.reason_label : words(reasonCode));
  const rule = (t: RuleTrace) => {
    const decisive = t.outcome_role === 'selected' || t.outcome_role === 'blocking';
    const badge = t.status === 'disabled' ?
      'Disabled' :
      t.outcome_role === 'conflict' ?
        'Conflict' :
        t.outcome_role === 'selected' ?
          'Selected' :
          t.outcome_role === 'blocking' ?
            'Blocking' :
            t.matched === true ? 'Matched' : t.matched === false ? 'No match' : 'Unknown';
    return <details
      key={t.rule_id}
      className={'case-rule ' + (decisive ? 'decisive' : '')}
      open={decisive || t.outcome_role === 'conflict' || undefined}
    >
      <summary>
        <span className="rule-order">{t.priority}</span>
        <span>
          <strong>{words(t.rule)}</strong>
          <small>
            {t.match === 'all' ? 'All conditions required' : 'Any condition may match'}
            {t.outcome_role ? ' · ' + roles[t.outcome_role] : ''}
          </small>
        </span>
        <Badge
          tone={
            t.outcome_role === 'conflict' ?
              'red' :
              decisive && t.matched === true ?
                'green' :
                t.matched === null && t.status !== 'disabled' ? 'amber' : 'neutral'
          }
        >
          {badge}
        </Badge>
      </summary>
      <div className="case-rule-body">
        <ActionTag action={t.action} route />
        {t.selection_explanation && <p className="small muted">{words(t.selection_explanation)}</p>}
        <ConditionTable checks={t.conditions} />
      </div>
    </details>;
  };
  return <RequestSection
    id="case-policy"
    title="Policy evaluation"
    icon="policy"
    subtitle={
      allRules ?
        'Every enabled rule is checked. Priorities and required checks determine one outcome.' :
        'Rule checks and the selected policy outcome.'
    }
  >
    {
      error ?
        <p className="alert error">Policy evaluation could not be loaded.</p> :
        !data || !ev ?
          <p>Loading policy evaluation…</p> :
          <>
            <div className="section-line">
              <strong className="case-policy-version">
                {
                  data.policy_version ?
                    `Policy v${data.policy_version}` :
                    `Policy version ${data.policy_id.slice(0, 8)}`
                }
              </strong>
            </div>
            {
              !allRules &&
              <p className="alert warning" role="status">Restart START.cmd to load evaluation of every rule. This server still returns a partial rule trace.</p>
            }
            <div className="case-policy-result">
              <div className="case-routing">
                <ActionTag action={ev.action} route />
                <ReasonBadge code={reasonCode} label={reasonLabel} explanation={words(ev.explanation)} />
              </div>
              <p>{words(ev.explanation)}</p>
              <p><strong>Next:</strong> {ev.next_action || r.evaluation.next_action}</p>
              <div className="signal-list">
                {
                  (ev.supporting_signals || r.evaluation.supporting_signals).map(x => <Badge key={x}>{words(x)}</Badge>)
                }
              </div>
            </div>
            {
              allRules && resolution ?
                <>
                  <div className="policy-stop">
                    <Icon name="branch" />
                    <div><strong>How the outcome was selected</strong><p>{words(resolution.summary)}</p></div>
                  </div>
                  <div className="signal-list">
                    <Badge>{resolution.evaluated_count} rules checked</Badge>
                    <Badge>{resolution.matched_rule_ids.length} matched</Badge>
                    {unknown > 0 && <Badge tone="amber">{unknown} with missing information</Badge>}
                    {resolution.disabled_count > 0 && <Badge>{resolution.disabled_count} disabled</Badge>}
                  </div>
                  <p className="small muted">Every condition is checked using the same request and evidence. A higher priority determines the result;
                    multiple matches are not votes.</p>
                </> :
                <p className="small muted">The legacy trace below contains only the rules checked before the previous evaluator selected an outcome.</p>
            }
            {ev.trace.map(rule)}
            {
              ev.trace.length === 0 && allRules &&
              <p className="small muted">This policy has no enabled rules. Requests go to Review unless a required check directs them elsewhere.</p>
            }

            {
              ev.remaining_rules.length > 0 &&
              <details className="remaining-rules">
                <summary>
                  {ev.remaining_rules.length} {allRules ? 'disabled rules' : 'rules absent from the legacy trace'}
                </summary>
                <p className="small muted">
                  {
                    allRules ?
                      'Disabled rules are excluded from evaluation and outcome selection.' :
                      'These rules were disabled or were not reached by the previous evaluator.'
                  }
                </p>
                {ev.remaining_rules.map(rule)}
              </details>
            }
            <p className="small muted">A policy result is a recommendation. Payment eligibility, duplicate protection and release limits are
              checked separately.</p>
          </>
    }
  </RequestSection>;
}

export default PolicyEvaluation;
