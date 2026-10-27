import MultiPolicyComparison from './MultiPolicyComparison';
import MetricHelp from './MetricHelp';
import PolicyEconomics from './PolicyEconomics';
import { useEffect, useState, type ReactNode } from 'react';
import { policyLabel, usePolicyVersions } from './policyIdentity';
import { Badge, Empty, money, words } from './components';
import { UiIcon } from './visualLanguage';
import { PolicyResult, HumanReference } from './ShadowPolicies';

export const percent = (n: number | null | undefined) => n == null ? 'Unknown' : (100 * n).toFixed(1) + '%';
const n = (v: number | null | undefined) => v == null ? 'Unknown' : new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(v);
const routes: Record<string, string> = { auto_approve: 'Auto Approve', review: 'Review', fraud: 'Fraud Review' };
const flagNames: Record<string, string> = {
  new_auto: 'New Auto Approve',
  returned_to_review: 'Returned to review',
  less_fraud_review: 'Leaves Fraud Review',
  above_reference: 'Above reference amount',
  unreviewed_auto: 'No eligible reference',
  recorded_chargeback: 'Recorded chargeback',
  overturned_appeal: 'Overturned appeal',
  data_issue: 'Data issue',
  incomplete_evidence: 'Incomplete evidence',
  critical_finding: 'Critical finding'
};
const dimensionNames: Record<string, string> = {
  customer_reason: 'Customer reason',
  routing_reason: 'Routing reason',
  amount_band: 'Refund amount',
  category: 'Product category',
  payment_method: 'Payment method',
  tenure: 'Customer tenure',
  prior_refunds: 'Refund history',
  source_channel: 'Source channel',
  location: 'Extracted location',
  request_month: 'Request month'
};
function Stat({ label, value, detail }: { label: string, value: string, detail: string }) {
  return <div className="decision-stat">
    <span><MetricHelp label={label} /></span>
    <strong>{value}</strong>
    <small>{detail}</small>
  </div>
}
function values(row: any) {
  return row.unit === 'money' ?
    money(row.actual) :
    row.unit === 'percent' ?
      percent(row.actual) :
      row.unit === 'boolean' ? row.actual == null ? 'Unknown' : row.actual ? 'Yes' : 'No' : n(row.actual)
}
function exportReport(report: any) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `${report.mode}-decision-evidence.json`;
  link.click();
  URL.revokeObjectURL(url)
}

export function ShadowDecisionReport({ reports, label = 'This version' }: { reports: any, label?: string }) {
  const [scope, setScope] = useState('prospective');
  if (!reports) return <p className="alert">Updated decision metrics are unavailable. Restart the application to load the updated API.</p>;
  return <>
    <div className="decision-scope">
      <strong>Requests included</strong>
      <div className="tabs" aria-label="Shadow report cohort">
        {
          [['prospective', 'New arrivals'], ['backlog', 'Existing requests'], ['all', 'All observations']].map(([key, title]) => <button
            key={key}
            aria-pressed={scope === key}
            className={scope === key ? 'selected' : ''}
            onClick={() => setScope(key)}
          >
            {title} <span>{reports[key]?.quality.total ?? 0}</span>
          </button>)
        }
      </div>
    </div>
    <DecisionReport report={reports[scope]} label={label} />
  </>;
}

export default function DecisionReport({ report: r, label = 'This version', comparisonVersions, casesExtra }: { report: any, label?: string, comparisonVersions?: any[], casesExtra?: ReactNode }) {
  const { data: policies = [] } = usePolicyVersions();
  const [tab, setTab] = useState('summary'),
    [dimension, setDimension] = useState('amount_band'),
    [filter, setFilter] = useState('all'),
    [search, setSearch] = useState(''),
    [page, setPage] = useState(0);
  useEffect(() => setPage(0), [filter, search, r?.metadata.scope]);
  if (!r) return <div className="alert">Run historical replay again to save the expanded report. Existing results are retained until you rerun
    it.</div>;
  const a = r.baseline,
    b = r.candidate,
    q = r.quality,
    m = r.money,
    w = r.workload,
    s = r.safety,
    change = r.changes;
  const shadow = r.mode === 'shadow', meta = r.metadata, comparison = !!meta.comparison_only;
  const baseline = policies.find(p => r.metadata.baseline_id ? p.id === r.metadata.baseline_id : p.status === 'active');
  const baselineLabel = baseline ?
    policyLabel(baseline.version) + (baseline.status === 'active' ? ' | Current' : ' | baseline when checks started') :
    'Current';
  const caseMaps = comparisonVersions?.map(v => ({ ...v, casesById: new Map(v.report.cases.map((c: any) => [c.id, c])) }));
  const shownFlags = Object.fromEntries(Object.entries(flagNames).filter(([id]) => comparison || !['new_auto', 'returned_to_review', 'less_fraud_review'].includes(id)));
  const caseRows = caseMaps ?
    r.cases.map((c: any) => ({ ...c, changed: caseMaps.some(v => (v.casesById.get(c.id) as any)?.changed) })) :
    r.cases;
  const cases = caseRows.filter((c: any) => (filter === 'all' || filter === 'changed' && c.changed || c.flags.includes(filter)) &&
    (!search ||
      (c.id + ' ' + c.customer_reason + ' ' + c.flags.join(' ')).toLowerCase().includes(search.toLowerCase())));
  const pages = Math.max(1, Math.ceil(cases.length / 20)), at = Math.min(page, pages - 1);
  const openCases = (value: string) => { setFilter(value); setTab('cases'); setPage(0) };
  const segments = r.segments.filter((x: any) => x.dimension === dimension);
  const gate = meta.qualification_eligible ? meta.gate : null;
  return <section className="panel decision-report" aria-label="Decision evidence">
    <header className="decision-report-header">
      <div>
        <div className="section-line">
          <h2>Decision evidence</h2>
          <Badge tone={shadow ? 'purple' : 'blue'}>
            {shadow ? 'Shadow observations' : 'Historical replay'}
          </Badge>
        </div>
        <p>
          {label}
          {comparison ? ` compared with ${baselineLabel}` : ''}. {q.total} requests · {q.distinct_customers} customers{q.date_from ? ` · ${q.date_from} to ${q.date_to}` : ''}
        </p>
      </div>
      <button onClick={() => exportReport(r)}><UiIcon name="download" />Export report</button>
    </header>
    <nav className="decision-tabs" aria-label="Decision evidence sections">
      {
        [
          ['summary', 'chart', 'Decision'],
          ['safety', 'shield', 'Safety & evidence'],
          ['money', 'money', 'Workload & money'],
          ['segments', 'split', 'Segments & rules'],
          ['cases', 'file', 'Cases']
        ].map(([id, icon, title]) => <button
          key={id}
          aria-pressed={tab === id}
          className={tab === id ? 'selected' : ''}
          onClick={() => setTab(id)}
        >
          <UiIcon name={icon} />
          {title}
        </button>)
      }
    </nav>
    <div className="decision-body">
      {
        meta.synthetic_workspace &&
        <p className="decision-notice">Demonstration workspace: synthetic new arrivals and authored reviewer references. The scenario exercises
          trade-offs and workflow; it is not evidence of production safety.</p>
      }
      {
        !q.total &&
        <Empty
          title="No evidence in this cohort yet"
          detail={
            shadow ?
              'New arrivals count only after Shadow starts. Existing requests have a separate view.' :
              'Import historical records to run a meaningful replay.'
          }
        />
      }
      {
        shadow && !meta.qualification_eligible &&
        <p className="decision-notice">
          {
            comparison ?
              'This shared comparison is descriptive. Open each version’s Shadow page for its release requirements for new arrivals.' :
              'Existing requests help investigate behavior. This cohort cannot qualify a release.'
          }
        </p>
      }
      {
        !shadow &&
        <p className="decision-notice">
          <UiIcon name="info" />
          {
            meta.evidence_mode === 'Full live extraction' ?
              'Full historical LLM extraction is saved for every request. This replay is exploratory; complete extraction does not prove factual accuracy or release safety.' :
              'Model extraction is not available for this replay. Missing evidence stays incomplete; these results do not establish safe automation.'
          }
        </p>
      }
      {
        tab === 'summary' &&
        <>
          <div className="decision-objective">
            <UiIcon name="target" />
            <div>
              <h3>{comparison ? 'Decision context' : 'Policy results'}</h3>
              <p>
                {
                  comparison ?
                    'Compare reviewer workload, reference disagreements, monetary exposure and uncertainty. The acceptable balance is your decision; these reports do not rank or recommend versions.' :
                    'Results for this version on the selected dataset. Human decisions are reference observations, not ground truth. Use Compare versions to inspect differences against Current and other candidates.'
                }
              </p>
            </div>
          </div>
          {
            comparison ?
              (<div className="decision-stats">
                <Stat
                  label="Auto Approve"
                  value={`${a.auto_count} → ${b.auto_count}`}
                  detail={`${percent(b.auto_rate)} of ${q.total} requests; proposed ${money(b.payout_cents)}`}
                />
                <Stat
                  label="Net reviewer capacity"
                  value={`${n(w.net_minutes_freed)} min`}
                  detail={`${n(w.saved)} freed, ${n(w.added)} added; scenario, not measured savings`}
                />
                <Stat
                  label="Above human reference"
                  value={b.reviewed_auto ? money(b.overpayment_cents) : 'Unknown'}
                  detail={
                    `${b.overpayment_cases} of ${b.reviewed_auto} comparable automatic proposals; ${b.unreviewed_auto} unknown`
                  }
                />
                <Stat
                  label="Error upper bound · 95%"
                  value={percent(b.error_upper_95)}
                  detail={`${b.group_errors} affected / ${b.reviewed_customer_groups} fully reviewed customer groups`}
                />
              </div>) :
              <div className="decision-stats">
                <Stat
                  label="Auto Approve"
                  value={n(b.auto_count)}
                  detail={`${percent(b.auto_rate)} of ${q.total} requests`}
                />
                <Stat label="Review" value={n(b.routes.review)} detail="Requests routed to the reviewer" />
                <Stat
                  label="Fraud Review"
                  value={n(b.routes.fraud)}
                  detail="Requests routed to fraud specialists"
                />
                <Stat
                  label="Automatic proposed refunds"
                  value={money(b.payout_cents)}
                  detail="Proposals only; this test makes no payments"
                />
              </div>
          }
          <div className={comparison ? "decision-two" : ""}>
            {
              comparison &&
              <div className="decision-block">
                <h3>What changes</h3>
                <dl className="decision-definitions">
                  <div>
                    <dt><MetricHelp label="New automatic proposals" /></dt>
                    <dd>
                      <button className="text-button" onClick={() => openCases('new_auto')}>
                        {change.new_auto} · {money(change.new_auto_cents)}
                      </button>
                    </dd>
                  </div>
                  <div>
                    <dt><MetricHelp label="Returned to a reviewer" /></dt>
                    <dd>
                      <button className="text-button" onClick={() => openCases('returned_to_review')}>
                        {change.returned_to_review} · {money(change.returned_cents)}
                      </button>
                    </dd>
                  </div>
                  <div>
                    <dt><MetricHelp label="Fraud Review → Auto Approve" /></dt>
                    <dd>{change.fraud_to_auto}</dd>
                  </div>
                  <div>
                    <dt><MetricHelp label="Reason or rule changes only" /></dt>
                    <dd>{change.reason_or_rule_only}</dd>
                  </div>
                  <div><dt><MetricHelp label="Automatic amount changes" /></dt><dd>{change.changed_amount}</dd></div>
                </dl>
              </div>
            }
            <div className="decision-block">
              <h3>Evidence still needed</h3>
              <dl className="decision-definitions">
                <div>
                  <dt><MetricHelp label="Automatic proposals without eligible reference" /></dt>
                  <dd>{b.unreviewed_auto} · {money(b.unreviewed_cents)}</dd>
                </div>
                <div>
                  <dt><MetricHelp label="Incomplete extraction" /></dt>
                  <dd>{q.total - q.complete_evidence} / {q.total}</dd>
                </div>
                <div>
                  <dt><MetricHelp label="Requests without an outcome record" /></dt>
                  <dd>{q.unknown_outcomes} / {q.total}</dd>
                </div>
                <div><dt><MetricHelp label="Chargeback probability / causal ROI" /></dt><dd>Not estimable</dd></div>
              </dl>
              <p className="small muted">A recorded note is not necessarily a final outcome. Blank follow-up is never a clean outcome.</p>
            </div>
          </div>
          <div className="decision-block">
            <div className="section-line">
              <h3>{shadow ? 'Release requirements' : 'Safety diagnostics and future Shadow requirements'}</h3>
              {
                gate &&
                <Badge tone={gate.passed ? 'green' : 'amber'}>
                  {gate.passed ? 'Ready for manager decision' : 'More evidence required'}
                </Badge>
              }
            </div>
            <p className="small muted">Targets are saved, configurable constraints. They do not define overall policy quality or resolve your
              trade-offs.</p>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th><MetricHelp label="Check" /></th>
                    <th><MetricHelp label="Observed" /></th>
                    <th><MetricHelp label="Target" /></th>
                    <th><MetricHelp label="Assessment" /></th>
                  </tr>
                </thead>
                <tbody>
                  {
                    r.criteria.map((c: any) => <tr key={c.label}>
                      <td><strong>{c.label}</strong><small>{c.detail}</small></td>
                      <td>{values(c)}{c.unit === 'hours' ? ' h' : ''}</td>
                      <td>{values({ ...c, actual: c.required })}{c.unit === 'hours' ? ' h' : ''}</td>
                      <td>
                        <Badge tone={c.status === 'fail' ? 'red' : c.status === 'pass' ? 'green' : 'amber'}>
                          {
                            c.status === 'pass' ?
                              'Within configured target' :
                              c.status === 'fail' ? 'Outside configured target' : 'Not established'
                          }
                        </Badge>
                      </td>
                    </tr>)
                  }
                </tbody>
              </table>
            </div>
            {gate?.blockers.length > 0 && <ul>{gate.blockers.map((x: string) => <li key={x}>{x}</li>)}</ul>}
          </div>
          <div className="decision-block">
            <h3>Rollout and rollback decision</h3>
            <p>The report exposes changed cases, affected segments and financial scenarios for your decision. Execution
              budgets and request evidence checks are separate controls. Choose the level of exposure, review effort
              and ongoing monitoring that fits your operation.</p>
            <p className="small muted">Payment budgets and request integrity checks are enforced. Broader business outcomes require manager
              monitoring; this screen does not claim an automatic statistical rollback system. Activation and Shadow
              start remain explicit actions.</p>
          </div>
        </>
      }
      {
        tab === 'safety' &&
        <>
          <div className="decision-stats">
            <Stat
              label="Eligible references"
              value={`${q.reference_count} / ${q.total}`}
              detail={
                shadow ?
                  `${q.late_references} late judgments excluded from error estimates` :
                  'Recorded human decisions with a known refund amount; legacy auto decisions excluded'
              }
            />
            <Stat
              label="Automatic reference coverage"
              value={percent(b.review_coverage)}
              detail={
                `${b.reviewed_auto} of ${b.auto_count}; ${money(b.reviewed_payout_cents)} of proposed money covered`
              }
            />
            <Stat
              label="Exact amount agreement"
              value={percent(b.agreement_rate)}
              detail={`${b.agreement_count} / ${b.reviewed_auto}; agreement is not correctness`}
            />
            <Stat
              label="Critical findings"
              value={q.total ? n(s.critical) : 'Unknown'}
              detail="Recorded findings, not proof every failure was tested"
            />
          </div>
          <div className="decision-two">
            <div className="decision-block">
              <h3>Automatic proposal risk</h3>
              <p className="small muted">A reference is a human refund decision for the same request. Excess is the amount proposed above that
                decision, not a confirmed loss. The 95% upper estimate describes uncertainty across fully reviewed customer
                groups; a small sample remains uncertain even with zero observed differences.</p>
              <dl className="decision-definitions">
                <div>
                  <dt><MetricHelp label="Excess above reference" /></dt>
                  <dd>
                    {b.reviewed_auto ? money(b.overpayment_cents) : 'Unknown'} · {b.overpayment_cases}/{b.reviewed_auto}
                  </dd>
                </div>
                <div>
                  <dt><MetricHelp label="Excess / reviewed proposed money" /></dt>
                  <dd>{percent(b.excess_share_of_reviewed_payout)}</dd>
                </div>
                <div>
                  <dt><MetricHelp label="Below reference amount" /></dt>
                  <dd>{b.underpayment_cases} / {b.reviewed_auto}</dd>
                </div>
                <div><dt><MetricHelp label="Proposals above payment cap" /></dt><dd>{b.cap_exceedances}</dd></div>
                {
                  comparison &&
                  <div>
                    <dt><MetricHelp label="New Auto Approve: excess cases" /></dt>
                    <dd>{r.newly_automatic.overpayment_cases} / {r.newly_automatic.reviewed_auto}</dd>
                  </div>
                }
                {
                  comparison &&
                  <div>
                    <dt><MetricHelp label="New Auto Approve: 95% upper error bound" /></dt>
                    <dd>{percent(r.newly_automatic.error_upper_95)}</dd>
                  </div>
                }
                {
                  comparison &&
                  <div>
                    <dt><MetricHelp label="Paired excess change vs Current" /></dt>
                    <dd>{s.paired_auto_reference_count ? money(s.paired_excess_delta_cents) : 'Unknown'}</dd>
                  </div>
                }
              </dl>
              {
                comparison &&
                <p className="small muted">This change is calculated on the same {s.paired_auto_reference_count} referenced requests automatic in either version, including requests returned to Review. A negative
                  change means less proposed excess; it is not proven avoided loss.</p>
              }
            </div>
            <div className="decision-block">
              <h3>Adverse outcomes to inspect</h3>
              <dl className="decision-definitions">
                <div>
                  <dt><MetricHelp label="Recorded chargebacks in this cohort" /></dt>
                  <dd>
                    <button className="text-button" onClick={() => openCases('recorded_chargeback')}>
                      {s.known_chargebacks}
                    </button>
                  </dd>
                </div>
                <div>
                  <dt><MetricHelp label="Chargeback cases now automatic" /></dt>
                  <dd>{b.chargeback_cases_on_auto}</dd>
                </div>
                {
                  comparison &&
                  <div>
                    <dt><MetricHelp label="Chargeback cases newly automatic" /></dt>
                    <dd>{s.new_auto_chargebacks}</dd>
                  </div>
                }
                {
                  comparison &&
                  <div>
                    <dt><MetricHelp label="Chargeback cases returned to review" /></dt>
                    <dd>{s.chargebacks_sent_to_review}</dd>
                  </div>
                }
                <div>
                  <dt><MetricHelp label="Overturned appeals" /></dt>
                  <dd>
                    <button className="text-button" onClick={() => openCases('overturned_appeal')}>
                      {s.appeals_overturned}
                    </button>
                  </dd>
                </div>
                <div><dt><MetricHelp label="Chargeback rate / full loss" /></dt><dd>Unknown</dd></div>
              </dl>
              <p className="small muted">Outcome events happened under the operating policy. Shadow outcomes are attached for diagnosis, never
                attributed causally to a candidate. Follow-up completeness and full order amounts are missing.</p>
            </div>
          </div>
          <div className="decision-block">
            <h3>Data and extraction coverage</h3>
            <div className="decision-stats">
              <Stat
                label="Complete evidence"
                value={`${q.complete_evidence} / ${q.total}`}
                detail="Completeness does not establish factual accuracy"
              />
              <Stat
                label="Invalid / conflicting inputs"
                value={`${q.invalid} / ${q.conflicts}`}
                detail="Counts may overlap; payment remains guarded"
              />
              <Stat
                label="Blocked by extraction"
                value={n(q.blocked_by_evidence)}
                detail="Incomplete or unknown evidence"
              />
              <Stat
                label="Missing customer identity"
                value={n(q.missing_customers)}
                detail="Cannot form independent customer groups"
              />
            </div>
            <p>Extraction methods: {
              Object.entries(q.evidence_methods).map(([key, value]) => `${words(key)}: ${value}`).join(' · ') ||
              'None'
            }
            </p>
            <p className="small muted">Provider calls serve the whole workspace and are not attributable to this cohort from the existing call
              log.</p>
          </div>
        </>
      }
      {
        tab === 'money' &&
        (comparison ?
          <>
            <div className="decision-notice">All money below is proposed exposure or a scenario. No candidate payment occurs in Backtest or Shadow.
              Freed reviewer capacity is not automatically a cash saving.</div>
            <div className="decision-stats">
              <Stat
                label="Automatic proposed money"
                value={`${money(a.payout_cents)} → ${money(b.payout_cents)}`}
                detail="Cash exposure, not refund loss"
              />
              <Stat
                label="Operating margin change"
                value={money(m.operating_margin_cents)}
                detail="Priced net capacity minus incremental AI and audit costs"
              />
              <Stat
                label="Future overpayment stress"
                value={money(m.stress_loss_cents)}
                detail={
                  `${m.assumptions.projection_cases} approvals × ${money(m.assumptions.max_single_cents)} cap × upper group error bound`
                }
              />
              <Stat
                label="New-auto break-even error rate"
                value={percent(m.new_auto_break_even_error_rate)}
                detail="Full proposed amount lost per error; scenario threshold, not an estimated error rate"
              />
            </div>
            <div className="decision-two">
              <div className="decision-block">
                <h3>Reviewer workload</h3>
                <dl className="decision-definitions">
                  <div><dt><MetricHelp label="Time freed by new automation" /></dt><dd>{n(w.saved)} min</dd></div>
                  <div><dt><MetricHelp label="Time added by returned reviews" /></dt><dd>{n(w.added)} min</dd></div>
                  <div>
                    <dt><MetricHelp label="Recorded-time inputs: freed / added" /></dt>
                    <dd>{n(w.recorded_saved)} / {n(w.recorded_added)} min</dd>
                  </div>
                  <div>
                    <dt><MetricHelp label="Cases using assumed time: freed / added" /></dt>
                    <dd>{w.estimated_saved_cases} / {w.estimated_added_cases}</dd>
                  </div>
                  <div><dt><MetricHelp label="Review queue change" /></dt><dd>{n(w.review_queue_delta)}</dd></div>
                  <div>
                    <dt><MetricHelp label="Fraud Review queue change" /></dt>
                    <dd>{n(w.fraud_queue_delta)}</dd>
                  </div>
                  <div>
                    <dt><MetricHelp label="Manual cases with full-approval reference" /></dt>
                    <dd>{b.manual_full_approvals}</dd>
                  </div>
                </dl>
                <p className="small muted">Historical time is a scenario input. Live reviewer active time, waiting time and specialist cost are
                  not measured. A full human approval does not prove the case was safe to automate.</p>
              </div>
              <div className="decision-block">
                <h3>Economic assumptions</h3>
                <dl className="decision-definitions">
                  <div>
                    <dt><MetricHelp label="Priced capacity change" /></dt>
                    <dd>{money(m.labor_delta_cents)}</dd>
                  </div>
                  <div>
                    <dt><MetricHelp label="Shared extraction cost" /></dt>
                    <dd>{money(m.shared_ai_cost_cents)}</dd>
                  </div>
                  <div>
                    <dt><MetricHelp label="Additional candidate extraction" /></dt>
                    <dd>{money(m.extra_ai_cost_cents)}</dd>
                  </div>
                  <div><dt><MetricHelp label="Audit cost change" /></dt><dd>{money(m.audit_delta_cents)}</dd></div>
                  <div>
                    <dt><MetricHelp label="Reference excess on new automation" /></dt>
                    <dd>
                      {r.newly_automatic.reviewed_auto ? money(m.new_auto_review_reference_excess_cents) : 'Unknown'}
                    </dd>
                  </div>
                  <div>
                    <dt><MetricHelp label="Net against correct-review benchmark" /></dt>
                    <dd>{money(m.net_against_correct_review_cents)}</dd>
                  </div>
                  <div>
                    <dt><MetricHelp label="Chargeback fee-only scenario" /></dt>
                    <dd>{money(s.chargeback_fee_only_cents)}</dd>
                  </div>
                  <div><dt><MetricHelp label="Measured causal ROI" /></dt><dd>Not estimable</dd></div>
                </dl>
                <p className="small muted">Shared extraction cancels in the version delta. Different candidate questions assume one extra extraction
                  per request. Net requires every newly automatic proposal to have an eligible reference and assumes correct
                  human review; it excludes unmeasured customer harm. Chargeback fees are not subtracted again as overlapping
                  losses.</p>
              </div>
            </div>
            <div className="decision-block">
              <h3>Saved assumptions and execution limits</h3>
              <div className="decision-assumptions">
                {
                  [
                    ['Review hourly cost', money(m.assumptions.hourly_cost_cents)],
                    ['Minutes per review', n(m.assumptions.review_minutes)],
                    ['AI cost per extraction', money(m.assumptions.ai_cost_cents)],
                    ['Audit cost', money(m.assumptions.audit_cost_cents)],
                    ['Audit fraction', percent(m.assumptions.audit_fraction)],
                    ['Single refund', money(m.assumptions.max_single_cents)],
                    ['Daily total', money(m.assumptions.daily_cents)],
                    ['Daily per customer', money(m.assumptions.customer_daily_cents)],
                    ['Release total', money(m.assumptions.release_cents)],
                    ['Release count', n(m.assumptions.release_count)]
                  ].map(([key, value]) => <div key={key}><small>{key}</small><strong>{value}</strong></div>)
                }
              </div>
              <p className="small muted">Edit cost assumptions in workspace Settings and execution limits in version Settings. Saved Backtest
                and Shadow retain their own assumptions.</p>
            </div>
          </> :
          <PolicyEconomics report={r} />)
      }
      {
        tab === 'segments' &&
        <>
          <div className="decision-block">
            <div className="section-line">
              <div>
                <h3>Results by segment</h3>
                <p className="small muted">Look for a risky subgroup hidden by a good overall average. Small samples remain uncertain.</p>
              </div>
              <select
                aria-label="Segment dimension"
                value={dimension}
                onChange={e => setDimension(e.target.value)}
              >
                {Object.entries(dimensionNames).map(([id, title]) => <option key={id} value={id}>{title}</option>)}
              </select>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th><MetricHelp label="Segment" /></th>
                    <th><MetricHelp label="Requests" /></th>
                    <th><MetricHelp label={comparison ? "Auto: Current to version" : "Auto Approve"} /></th>
                    <th><MetricHelp label="Proposed money" /></th>
                    <th><MetricHelp label="Reviewed auto" /></th>
                    <th><MetricHelp label="Excess cases / amount" /></th>
                    <th><MetricHelp label="95% upper bound" /></th>
                    <th><MetricHelp label="Recorded chargebacks on auto" /></th>
                  </tr>
                </thead>
                <tbody>
                  {
                    segments.map((x: any) => <tr key={x.value}>
                      <td>{words(String(x.value))}</td>
                      <td>{x.total}</td>
                      <td>
                        {comparison ? `${x.baseline_auto} to ${x.candidate_auto}` : x.candidate_auto}
                        <small>{percent(x.auto_rate)}</small>
                      </td>
                      <td>{money(x.payout_cents)}</td>
                      <td>{x.reviewed_auto} / {x.candidate_auto}</td>
                      <td>{x.reviewed_auto ? `${x.overpayment_cases} / ${money(x.overpayment_cents)}` : 'Unknown'}</td>
                      <td>{percent(x.error_upper_95)}<small>{x.reviewed_customer_groups} customer groups</small></td>
                      <td>{x.known_chargebacks}</td>
                    </tr>)
                  }
                </tbody>
              </table>
            </div>
          </div>
          <div className="decision-block">
            <h3>Rule coverage and competing matches</h3>
            <p className="small muted">All enabled rules are evaluated. A matching rule may lose to priority or a policy-wide check. Winner
              attribution is descriptive, not the causal value of removing a rule.</p>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th><MetricHelp label="Rule" /></th>
                    <th><MetricHelp label="Matches" /></th>
                    <th><MetricHelp label="Decisive" /></th>
                    <th><MetricHelp label="Overridden" /></th>
                    <th><MetricHelp label="Unknown" /></th>
                    <th><MetricHelp label={comparison ? "Auto / new" : "Auto Approve"} /></th>
                    <th><MetricHelp label="Proposed money" /></th>
                    <th><MetricHelp label="Excess / referenced" /></th>
                    <th><MetricHelp label="Overlap" /></th>
                  </tr>
                </thead>
                <tbody>
                  {
                    r.rules.map((x: any) => <tr key={x.id}>
                      <td>
                        <strong>{words(x.name)}</strong>
                        <small>Priority {x.priority} · {x.enabled ? 'Enabled' : 'Disabled'}</small>
                      </td>
                      <td>{x.matches}</td>
                      <td>{x.wins}</td>
                      <td>{x.overridden}</td>
                      <td>{x.unknown}</td>
                      <td>{comparison ? `${x.auto_count} / ${x.new_auto}` : x.auto_count}</td>
                      <td>{money(x.payout_cents)}</td>
                      <td>{x.reviewed_auto ? `${x.overpayment_cases} / ${x.reviewed_auto}` : 'Unknown'}</td>
                      <td>
                        {
                          x.overlaps.length ?
                            <details>
                              <summary>{x.overlaps.length} rules</summary>
                              {
                                x.overlaps.map((o: any) => <p key={o.id}>{r.rules.find((rr: any) => rr.id === o.id)?.name || o.id}: {o.count}</p>)
                              }
                            </details> :
                            'None'
                        }
                      </td>
                    </tr>)
                  }
                </tbody>
              </table>
            </div>
          </div>
          {
            comparison &&
            <>
              <div className="decision-block">
                <h3>Routing transitions</h3>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th><MetricHelp label="Current" /></th>
                        <th>{label}</th>
                        <th><MetricHelp label="Requests" /></th>
                        <th><MetricHelp label="Requested amount" /></th>
                      </tr>
                    </thead>
                    <tbody>
                      {
                        r.transitions.map((t: any) => <tr key={t.from + t.to}>
                          <td>{routes[t.from]}</td>
                          <td>{routes[t.to]}</td>
                          <td>{t.count}</td>
                          <td>{money(t.requested_cents)}</td>
                        </tr>)
                      }
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          }
          {
            comparison &&
            <>
              <details className="decision-block">
                <summary>Exact policy changes</summary>
                <p>
                  {r.policy_changes.rules.length} rule changes · {r.policy_changes.settings.length} settings changes</p>
                {r.policy_changes.rules.map((x: any) => <p key={x.id}>{words(x.change)}: {words(x.name)}</p>)}
                {
                  r.policy_changes.settings.map((x: any) => <div key={x.field}>
                    <strong>{words(x.field)}</strong>
                    <pre className="lab-json">{JSON.stringify({ before: x.before, after: x.after }, null, 2)}</pre>
                  </div>)
                }
              </details>
            </>
          }
        </>
      }
      {
        tab === 'cases' &&
        <>
          {
            caseMaps &&
            <p className="small muted">All selected versions on the same cohort. Finding filters and badges refer to {label}.</p>
          }
          <div className="decision-case-tools">
            <label>Cases<select value={filter} onChange={e => setFilter(e.target.value)}>
              <option value="all">All requests</option>
              {comparison && <option value="changed">All changes</option>}
              {
                Object.entries(shownFlags).map(([id, title]) => <option key={id} value={id}>
                  {title} ({r.cases.filter((c: any) => c.flags.includes(id)).length})</option>)
              }
            </select>
            </label>
            <label>Find request<input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Request ID or customer reason"
            />
            </label>
          </div>
          <div className="table-scroll">
            <table className="decision-cases">
              <thead>
                <tr>
                  <th><MetricHelp label="Request" /></th>
                  {comparison && <th>{baselineLabel}</th>}
                  {caseMaps ? caseMaps.map(v => <th key={v.policy_id}>Policy v{v.version}</th>) : <th>{label}</th>}
                  <th><MetricHelp label="Human reference" /></th>
                  <th><MetricHelp label="Findings" /></th>
                </tr>
              </thead>
              <tbody>
                {
                  cases.slice(at * 20, (at + 1) * 20).map((c: any) => <tr key={c.id}>
                    <td>
                      <strong>{c.id}</strong>
                      <small>{money(c.amount_cents)} · {words(c.customer_reason || 'Unknown')}</small>
                    </td>
                    {comparison && <td><PolicyResult evaluation={c.baseline} /></td>}
                    {
                      caseMaps ?
                        caseMaps.map(v => <td key={v.policy_id}><PolicyResult evaluation={(v.casesById.get(c.id) as any)?.candidate} /></td>) :
                        <td><PolicyResult evaluation={c.candidate} /></td>
                    }
                    <td>
                      <HumanReference label={c.reference} />
                      <small>
                        {
                          c.reference_eligible ?
                            (shadow ? 'Prediction preceded this judgment' : 'Historical observation, not ground truth') :
                            'Not eligible for error estimates'
                        }
                      </small>
                      {c.reference?.note && <details><summary>Reference note</summary><p>{c.reference.note}</p></details>}
                    </td>
                    <td>
                      <div className="decision-flags">
                        {
                          c.flags.filter((f: string) => f in shownFlags).map((f: string) => <Badge
                            key={f}
                            tone={['above_reference', 'critical_finding', 'recorded_chargeback'].includes(f) ? 'red' : 'neutral'}
                          >
                            {flagNames[f]}
                          </Badge>)
                        }
                      </div>
                    </td>
                  </tr>)
                }
              </tbody>
            </table>
          </div>
          {!cases.length && <Empty title="No matching cases" detail="Choose another case filter." />}
          <footer className="comparison-pagination">
            <span>{cases.length} cases · page {at + 1} / {pages}</span>
            <div className="button-row">
              <button disabled={!at} onClick={() => setPage(at - 1)}>Previous</button>
              <button disabled={at + 1 >= pages} onClick={() => setPage(at + 1)}>Next</button>
            </div>
          </footer>
          {casesExtra}
        </>
      }
      <details className="decision-method">
        <summary>Definitions, limitations and reproducibility</summary>
        {r.limitations.map((x: string) => <p key={x}>{x}</p>)}
        <p>Targets and statistical assumptions should be agreed before observing results. Zero errors in a small
          sample never means zero risk.</p>
        <pre className="lab-json">{JSON.stringify(meta, null, 2)}</pre>
      </details>
    </div>
  </section>;
}

export function ComparisonEvidence({ data }: { data: any }) { return <MultiPolicyComparison data={data} />; }
