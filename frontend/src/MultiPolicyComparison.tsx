import { useEffect, useState } from 'react';
import { Badge, Empty, money, words } from './components';
import MetricHelp from './MetricHelp';
import { UiIcon } from './visualLanguage';
import { PolicyResult, HumanReference } from './ShadowPolicies';

const pct = (v: number | null) => v == null ? 'Unknown' : (v * 100).toFixed(1) + '%';
const num = (v: number | null) => v == null ? 'Unknown' : new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(v);
const flags: Record<string, string> = {
  new_auto: 'New Auto Approve',
  returned_to_review: 'Returned to review',
  less_fraud_review: 'Leaves Fraud Review',
  above_reference: 'Above reference',
  unreviewed_auto: 'No eligible reference',
  recorded_chargeback: 'Recorded chargeback',
  overturned_appeal: 'Overturned appeal',
  data_issue: 'Data issue',
  incomplete_evidence: 'Incomplete evidence',
  critical_finding: 'Critical finding'
};
type MetricRow = [string, (r: any) => string];
const groups: Record<string, MetricRow[]> = {
  summary: [
    ['Comparable requests', r => num(r.quality.total)],
    ['Auto Approve', r => `${r.candidate.auto_count} (${pct(r.candidate.auto_rate)})`],
    ['Review', r => num(r.candidate.routes.review)],
    ['Fraud Review', r => num(r.candidate.routes.fraud)],
    ['Automatic proposed money', r => money(r.candidate.payout_cents)],
    [
      'New automatic / returned to review',
      r => `${r.changes.new_auto} / ${r.changes.returned_to_review}`
    ],
    ['Reason or rule changes only', r => num(r.changes.reason_or_rule_only)],
    ['Complete evidence', r => `${r.quality.complete_evidence} / ${r.quality.total}`],
    ['Automatic reference coverage', r => `${r.candidate.reviewed_auto} / ${r.candidate.auto_count}`],
    [
      'Excess above reference',
      r => r.candidate.reviewed_auto ? money(r.candidate.overpayment_cents) : 'Unknown'
    ],
    ['Unreviewed automatic exposure', r => money(r.candidate.unreviewed_cents)],
    ['Upper group error rate · 95%', r => pct(r.candidate.error_upper_95)]
  ],
  safety: [
    ['Eligible references', r => `${r.quality.reference_count} / ${r.quality.total}`],
    ['Reference coverage on automatic', r => `${r.candidate.reviewed_auto} / ${r.candidate.auto_count}`],
    ['Exact amount agreement', r => pct(r.candidate.agreement_rate)],
    [
      'Excess cases / reviewed proposals',
      r => `${r.candidate.overpayment_cases} / ${r.candidate.reviewed_auto}`
    ],
    [
      'Excess above reference',
      r => r.candidate.reviewed_auto ? money(r.candidate.overpayment_cents) : 'Unknown'
    ],
    ['Excess / reviewed proposed money', r => pct(r.candidate.excess_share_of_reviewed_payout)],
    ['Below reference amount', r => `${r.candidate.underpayment_cases} / ${r.candidate.reviewed_auto}`],
    ['Upper group error rate · 95%', r => pct(r.candidate.error_upper_95)],
    ['Fully reviewed customer groups', r => num(r.candidate.reviewed_customer_groups)],
    [
      'New Auto Approve: excess cases',
      r => `${r.newly_automatic.overpayment_cases} / ${r.newly_automatic.reviewed_auto}`
    ],
    ['New Auto Approve: 95% upper error bound', r => pct(r.newly_automatic.error_upper_95)],
    [
      'Paired excess change vs Current',
      r => r.safety.paired_auto_reference_count ? money(r.safety.paired_excess_delta_cents) : 'Unknown'
    ],
    ['Chargeback cases routed to auto', r => num(r.candidate.chargeback_cases_on_auto)],
    ['Chargeback cases newly automatic', r => num(r.safety.new_auto_chargebacks)],
    ['Critical findings', r => num(r.safety.critical)],
    ['Complete evidence', r => `${r.quality.complete_evidence} / ${r.quality.total}`],
    ['Invalid / conflicting inputs', r => `${r.quality.invalid} / ${r.quality.conflicts}`],
    ['Unknown outcomes', r => `${r.quality.unknown_outcomes} / ${r.quality.total}`],
    ['Proposals above payment cap', r => num(r.candidate.cap_exceedances)]
  ],
  money: [
    ['Automatic proposed money', r => money(r.candidate.payout_cents)],
    ['Unreviewed automatic exposure', r => money(r.candidate.unreviewed_cents)],
    [
      'Excess above reference',
      r => r.candidate.reviewed_auto ? money(r.candidate.overpayment_cents) : 'Unknown'
    ],
    ['Time freed by new automation', r => num(r.workload.saved) + ' min'],
    ['Time added by returned reviews', r => num(r.workload.added) + ' min'],
    ['Net reviewer minutes · scenario', r => num(r.workload.net_minutes_freed)],
    [
      'Recorded-time inputs: freed / added',
      r => `${num(r.workload.recorded_saved)} / ${num(r.workload.recorded_added)} min`
    ],
    [
      'Cases using assumed time: freed / added',
      r => `${r.workload.estimated_saved_cases} / ${r.workload.estimated_added_cases}`
    ],
    ['Operating margin change · scenario', r => money(r.money.operating_margin_cents)],
    ['Shared extraction cost', r => money(r.money.shared_ai_cost_cents)],
    ['Additional candidate extraction', r => money(r.money.extra_ai_cost_cents)],
    ['Audit cost change', r => money(r.money.audit_delta_cents)],
    ['Future stress · saved assumptions', r => money(r.money.stress_loss_cents)],
    ['New-auto break-even error rate', r => pct(r.money.new_auto_break_even_error_rate)],
    ['Review minutes · assumption', r => num(r.money.assumptions.review_minutes)],
    ['Hourly cost · assumption', r => money(r.money.assumptions.hourly_cost_cents)],
    ['AI cost per extraction · assumption', r => money(r.money.assumptions.ai_cost_cents)],
    ['Audit fraction · assumption', r => pct(r.money.assumptions.audit_fraction)],
    ['Audit cost · assumption', r => money(r.money.assumptions.audit_cost_cents)],
    ['Stress projection · approvals', r => num(r.money.assumptions.projection_cases)],
    ['Single-payment cap', r => money(r.money.assumptions.max_single_cents)]
  ]
};
const dimensions: Record<string, string> = {
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
const segmentMetrics: Record<string, string> = {
  auto: 'Auto Approve',
  money: 'Proposed refunds',
  excess: 'Excess / referenced',
  uncertainty: '95% upper error bound'
};

export default function MultiPolicyComparison({ data }: { data: any }) {
  const [scope, setScope] = useState('prospective'),
    [tab, setTab] = useState('summary'),
    [dimension, setDimension] = useState('amount_band'),
    [segmentMetric, setSegmentMetric] = useState('auto');
  const [filter, setFilter] = useState('all'),
    [search, setSearch] = useState(''),
    [page, setPage] = useState(0);
  useEffect(() => setPage(0), [scope, filter, search]);
  const shadow = data.mode === 'shadow';
  const versions = [
    {
      ...data.current,
      decision_report: data.current_decision_report,
      decision_reports: data.current_decision_reports
    },
    ...data.versions.filter((v: any) => v.available).sort((a: any, b: any) => a.version - b.version)
  ]
    .map(v => ({ ...v, report: shadow ? v.decision_reports?.[scope] : v.decision_report })).filter(v => v.report);
  if (!versions.length) return <Empty
    title="No comparable results yet"
    detail="Run Backtest or start Shadow for the selected versions."
  />;
  const title = (v: any) => `Policy v${v.version}${v.policy_id === data.current.policy_id ? ' · Current' : ''}`;
  const first = versions[0].report;
  const maps = versions.map(v => new Map(v.report.cases.map((c: any) => [c.id, c])));
  const allRows = first.cases.map((c: any) => ({ ...c, versions: maps.map(m => m.get(c.id) as any) }));
  const flagged = (c: any) => [...new Set<string>(c.versions.flatMap((v: any) => v?.flags || []))];
  const rows = allRows.filter((c: any) => (filter === 'all' || filter === 'changed' && c.versions.some((v: any) => v?.changed) ||
    flagged(c).includes(filter)) &&
    (!search || (c.id + ' ' + c.customer_reason).toLowerCase().includes(search.toLowerCase())));
  const pages = Math.max(1, Math.ceil(rows.length / 20)), at = Math.min(page, pages - 1);
  const headings = <>{versions.map(v => <th key={v.policy_id}>{title(v)}</th>)}</>;
  const table = (metrics: MetricRow[]) => <div className="table-scroll">
    <table className="decision-comparison multi-policy-table">
      <thead><tr><th>Metric</th>{headings}</tr></thead>
      <tbody>
        {
          metrics.map(([label, read]) => <tr key={label}>
            <th><MetricHelp label={label} /></th>
            {versions.map(v => <td key={v.policy_id}>{read(v.report)}</td>)}
          </tr>)
        }
      </tbody>
    </table>
  </div>;
  const segments = [
    ...new Set<string>(versions.flatMap(v => v.report.segments.filter((x: any) => x.dimension === dimension).map((x: any) => x.value)))
  ];
  const rules = [
    ...new Map(versions.flatMap(v => v.report.rules.map((r: any) => [r.id, r] as [string, any]))).values()
  ];
  const exportAll = () => {
    const blob = new Blob([
      JSON.stringify(
        {
          mode: data.mode,
          scope: shadow ? scope : 'history',
          versions: versions.map(v => ({ policy_id: v.policy_id, version: v.version, report: v.report }))
        },
        null,
        2
      )
    ], { type: 'application/json' });
    const url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url;
    link.download = 'policy-comparison.json';
    link.click();
    URL.revokeObjectURL(url)
  };
  return <>
    {
      shadow &&
      <div className="decision-scope">
        <strong>Shared cohort</strong>
        <div className="tabs" aria-label="Comparison cohort">
          {
            [['prospective', 'New arrivals'], ['backlog', 'Existing requests'], ['all', 'All observations']].map(([key, label]) => <button
              key={key}
              className={scope === key ? 'selected' : ''}
              aria-pressed={scope === key}
              onClick={() => setScope(key)}
            >
              {label}
            </button>)
          }
        </div>
        <p className="small muted">New arrivals must follow every selected Shadow start. Human references must follow every compared prediction.</p>
      </div>
    }
    <section className="panel decision-report" aria-label="Version comparison">
      <header className="decision-report-header">
        <div>
          <h2>Compare {versions.length} versions</h2>
          <p>
            {first.quality.total} shared requests · {first.quality.distinct_customers} customers · {shadow ? 'Shadow observations' : 'Historical replay'}
          </p>
        </div>
        <button onClick={exportAll}><UiIcon name="download" />Export comparison</button>
      </header>
      <nav className="decision-tabs" aria-label="Comparison sections">
        {
          [
            ['summary', 'chart', 'Decision'],
            ['safety', 'shield', 'Safety & evidence'],
            ['money', 'money', 'Workload & money'],
            ['segments', 'split', 'Segments & rules'],
            ['cases', 'file', 'Cases']
          ].map(([key, icon, label]) => <button
            key={key}
            aria-pressed={tab === key}
            className={tab === key ? 'selected' : ''}
            onClick={() => setTab(key)}
          >
            <UiIcon name={icon} />
            {label}
          </button>)
        }
      </nav>
      <div className="decision-body">
        {
          tab === 'summary' &&
          <>
            <div className="decision-objective">
              <UiIcon name="target" />
              <div>
                <h3>Decision context</h3>
                <p>All selected versions stay side by side. Current is a baseline, not a correctness label. Read workload,
                  exposure and uncertainty together; this report does not choose a winner.</p>
              </div>
            </div>
            {table(groups.summary)}
          </>
        }
        {
          tab === 'safety' &&
          <>
            <p className="small muted">Human references are fallible. Missing references and outcomes stay unknown. Counts use the same cohort;
              percentages keep their own explicit denominators.</p>
            {table(groups.safety)}
            <p className="small muted">The 95% bound groups repeated customers and uses fully referenced groups only. It does not cover systematic
              extraction errors or unseen populations. Chargeback counts do not establish a chargeback rate or avoided
              loss.</p>
          </>
        }
        {
          tab === 'money' &&
          <>
            <p className="small muted">Changes are relative to Current. Capacity and costs are scenarios, not measured savings. Each column
              uses its saved assumptions, listed below.</p>
            {table(groups.money)}
            <p className="small muted">Shared extraction cancels in the delta. Additional candidate questions assume extra extraction. Future
              stress uses the upper group error bound × projected approvals × the payment cap. Customer harm, full
              chargeback losses and causal ROI remain unknown.</p>
          </>
        }
        {
          tab === 'segments' &&
          <>
            <div className="decision-case-tools">
              <label>Segment dimension<select value={dimension} onChange={e => setDimension(e.target.value)}>
                {Object.entries(dimensions).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select>
              </label>
              <label>Segment metric<select value={segmentMetric} onChange={e => setSegmentMetric(e.target.value)}>
                {
                  Object.entries(segmentMetrics).map(([key, label]) => <option key={key} value={key}>{String(label)}</option>)
                }
              </select>
              </label>
            </div>
            <div className="table-scroll">
              <table className="multi-policy-table">
                <thead><tr><th>Segment</th>{headings}</tr></thead>
                <tbody>
                  {
                    segments.map(value => <tr key={value}>
                      <th>{words(String(value))}</th>
                      {
                        versions.map(v => {
                          const x = v.report.segments.find((s: any) => s.dimension === dimension && s.value === value);
                          return <td key={v.policy_id}>
                            {
                              !x ?
                                'Not present' :
                                segmentMetric === 'auto' ?
                                  `${x.candidate_auto} / ${x.total}` :
                                  segmentMetric === 'money' ?
                                    money(x.payout_cents) :
                                    segmentMetric === 'uncertainty' ?
                                      pct(x.error_upper_95) :
                                      x.reviewed_auto ?
                                        `${x.overpayment_cases} / ${x.reviewed_auto} · ${money(x.overpayment_cents)}` :
                                        'Unknown'
                            }
                            {
                              x &&
                              <small>
                                {x.total} requests{segmentMetric === 'uncertainty' ? ` · ${x.reviewed_customer_groups} reviewed customer groups` : ''}
                              </small>
                            }
                          </td>
                        })
                      }
                    </tr>)
                  }
                </tbody>
              </table>
            </div>
            <p className="small muted">A routing-reason segment can contain different requests in different versions. Other segments share
              request attributes. Small samples remain uncertain.</p>
            <h3>Rule coverage by version</h3>
            <p className="small muted">Each cell shows decisive / matching requests, automatic proposals and reference excess. Missing rules
              are shown explicitly; priority and policy-wide checks can override matches.</p>
            <div className="table-scroll">
              <table className="multi-policy-table">
                <thead><tr><th>Rule identity</th>{headings}</tr></thead>
                <tbody>
                  {
                    rules.map((rule: any) => <tr key={rule.id}>
                      <th>{words(rule.name)}<small>{rule.id}</small></th>
                      {
                        versions.map(v => {
                          const r = v.report.rules.find((x: any) => x.id === rule.id);
                          return <td key={v.policy_id}>
                            {
                              r ?
                                <>
                                  <strong>{r.wins} / {r.matches}</strong>
                                  <small>{words(r.name)} · priority {r.priority} · {r.enabled ? 'Enabled' : 'Disabled'}</small>
                                  <small>{r.auto_count} Auto Approve · {money(r.payout_cents)}</small>
                                  <small>Excess: {r.reviewed_auto ? `${r.overpayment_cases} / ${r.reviewed_auto}` : 'Unknown'}</small>
                                  <small>{r.overridden} overridden · {r.unknown} unknown</small>
                                </> :
                                'Not present'
                            }
                          </td>
                        })
                      }
                    </tr>)
                  }
                </tbody>
              </table>
            </div>
          </>
        }
        {
          tab === 'cases' &&
          <>
            <div className="decision-case-tools">
              <label>Cases<select value={filter} onChange={e => setFilter(e.target.value)}>
                <option value="all">All requests</option>
                <option value="changed">Any difference from Current</option>
                {
                  Object.entries(flags).map(([key, label]) => <option key={key} value={key}>
                    {label} ({allRows.filter((c: any) => flagged(c).includes(key)).length})</option>)
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
            <p className="small muted">Filters match any selected version. Findings stay inside the version’s cell. Every row uses the same
              request and eligible human reference.</p>
            <div className="table-scroll">
              <table className="multi-policy-table multi-policy-cases">
                <thead><tr><th>Request</th>{headings}<th>Human reference</th></tr></thead>
                <tbody>
                  {
                    rows.slice(at * 20, (at + 1) * 20).map((c: any) => <tr key={c.id}>
                      <th>
                        <strong>{c.id}</strong>
                        <small>{money(c.amount_cents)} · {words(c.customer_reason || 'Unknown')}</small>
                      </th>
                      {
                        c.versions.map((v: any, i: number) => <td key={versions[i].policy_id}>
                          <PolicyResult evaluation={v?.candidate} />
                          <div className="decision-flags">
                            {
                              v?.flags.map((f: string) => <Badge
                                key={f}
                                tone={['above_reference', 'critical_finding', 'recorded_chargeback'].includes(f) ? 'red' : 'neutral'}
                              >
                                {flags[f] || words(f)}
                              </Badge>)
                            }
                          </div>
                        </td>)
                      }
                      <td>
                        <HumanReference label={c.reference} />
                        <small>
                          {
                            c.reference_eligible ?
                              (shadow ? 'Prediction preceded judgment' : 'Historical observation, not ground truth') :
                              'Not eligible for error estimates'
                          }
                        </small>
                        {c.reference?.note && <details><summary>Reference note</summary><p>{c.reference.note}</p></details>}
                      </td>
                    </tr>)
                  }
                </tbody>
              </table>
            </div>
            {
              !rows.length &&
              <Empty title="No matching cases" detail="Choose another filter or observation cohort." />
            }
            <footer className="comparison-pagination">
              <span>{rows.length} cases · page {at + 1} / {pages}</span>
              <div className="button-row">
                <button disabled={!at} onClick={() => setPage(at - 1)}>Previous</button>
                <button disabled={at + 1 >= pages} onClick={() => setPage(at + 1)}>Next</button>
              </div>
            </footer>
          </>
        }
        {
          !first.quality.total && tab !== 'cases' &&
          <Empty
            title="No observations in this cohort"
            detail="Existing requests remain in their own cohort. New arrivals count after every selected version starts Shadow."
          />
        }
        <details className="decision-block">
          <summary>Scope and interpretation</summary>
          <p>All columns use the same request cohort and reference eligibility. A blank outcome is unknown, and a
            human approval does not establish that automation was safe. Existing and shared Shadow cohorts are diagnostic;
            release requirements are checked on each version’s own prospective cohort.</p>
          <p>Use the policy’s Backtest or Shadow page for its own detailed findings and release requirements. This
            comparison does not activate or qualify a version.</p>
        </details>
      </div>
    </section>
  </>;
}
