import type { ReactNode } from 'react';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, Badge, Icon, money, words, SourceText } from './components';
import type { RequestRecord } from './components';

export function RequestSection({ id, title, icon, subtitle, children, collapsible = false }: {
  id: string,
  title: string,
  icon: string,
  subtitle?: string,
  children: ReactNode,
  collapsible?: boolean
}) {
  const heading = <>
    <span className="section-icon"><Icon name={icon} /></span>
    <div><h3>{title}</h3>{subtitle && <p>{subtitle}</p>}</div>
  </>;
  return <section id={id} className="request-section" aria-label={title}>
    {
      collapsible ?
        <details className="section-disclosure">
          <summary className="request-section-title">
            {heading}
            <span className="section-disclosure-arrow">⌄</span>
          </summary>
          {children}
        </details> :
        <><div className="request-section-title">{heading}</div>{children}</>
    }
  </section>;
}

export function EvidenceAnalysis({ request: r, children }: { request: RequestRecord, children: ReactNode }) {
  const analysis = r.analysis;
  const extracted = analysis?.status === 'completed' && analysis.evidence ? analysis.evidence : r.evidence;
  const facts = {
    ...extracted.facts,
    ...Object.fromEntries(Object.entries(r.evidence.facts).filter(([, f]) => f.source === 'human'))
  };
  const evidence = { ...extracted, facts };
  const status = analysis?.status || 'pending';
  const label = status === 'completed' ?
    'Analysis complete' :
    status === 'running' ?
      'Analysing notes…' :
      status === 'blocked' ?
        'Analysis paused' :
        status === 'failed' ?
          'Analysis needs attention' :
          status === 'unavailable' ? 'Analysis unavailable' : 'Analysis queued';
  return <RequestSection
    id="case-evidence"
    title="Evidence analysis"
    icon="spark"
    subtitle="Request context, extracted facts and their supporting sources."
  >
    <div className={'analysis-state ' + (status === 'completed' ? 'is-complete' : '')} role="status">
      <Badge tone={status === 'completed' ? 'green' : 'amber'}>{label}</Badge>
      <span>
        {
          status === 'completed' ?
            'Prepared automatically' :
            status === 'running' || status === 'pending' ?
              'Runs automatically; this section updates when ready.' :
              analysis?.error?.replaceAll('Policy Manager', 'Refund Operations Manager')
        }
        {
          analysis?.retrying && analysis.retry_at &&
          <small className="analysis-retry">Next automatic attempt: {new Date(analysis.retry_at * 1000).toLocaleTimeString()}.</small>
        }
      </span>
    </div>
    <div className="evidence-source-grid">
      {
        [['customer_note', 'Customer note'], ['support_note', 'Support note']].map(([source, label]) => <div className="source-note" key={source}>
          <span>{label}</span>
          <p>
            <SourceText
              text={r.data[source as 'customer_note' | 'support_note']}
              source={source}
              evidence={evidence}
            />
          </p>
        </div>)
      }
    </div>
    <div className="evidence-findings">
      <h4>{status === 'completed' ? 'Analysis findings' : 'Available evidence'}</h4>
      <p>{evidence.summary}</p>
      {
        status !== 'completed' &&
        <p className="small muted">An unfinished automatic analysis is not treated as a completed LLM review.</p>
      }
      {
        Object.values(facts).map(f => <div className="fact" key={f.name}>
          <div>
            <strong>{words(f.name.replace('semantic.', ''))}</strong>
            <Badge tone={f.value === 'unknown' ? 'amber' : 'neutral'}>{f.value}</Badge>
          </div>
          <blockquote>{f.quote}</blockquote>
          <small>
            {f.source === 'human' ? 'Verified by staff' : words(f.source)}
            {f.note ? ' · ' + f.note : ''}
          </small>
          {
            f.context && Object.keys(f.context).length > 0 &&
            <p className="small muted">
              {
                Object.entries(f.context).map(([key, value]) => words(key) + ': ' + (key === 'amount_cents' ? money(value as number) : value == null ? 'Unknown' : String(value))).join(' · ')
              }
            </p>
          }
        </div>)
      }
      {evidence.issues.map((x, i) => <p className="amber-text" key={i}>{x}</p>)}
      {
        r.evidence.reviewed_by &&
        <p className="staff-confirmation">
          <Icon name="check" />Notes reviewed by {r.evidence.reviewed_by}
        </p>
      }
    </div>
    {children}
  </RequestSection>;
}

type Cohort = {
  total: number,
  chargebacks: number,
  confirmed_clean: number,
  unknown: number,
  recorded_rate: number | null,
  examples: { request_id: string, amount_cents: number, note: string }[]
};
type Scenario = {
  order_amount_cents: number | null,
  fee_cents: number,
  probability: number | null,
  stress_probability: number | null,
  review_minutes: number,
  hourly_cents: number,
  prevention_fraction: number,
  assumptions: string[],
  review_time_source: string
};
type Risk = {
  level: string,
  segment: string,
  amount_band: string,
  as_of: string,
  cohort: Cohort,
  baseline: Cohort,
  explanation: string,
  financial_note: string,
  refund_cents: number | null,
  chargeback_fee_cents: number,
  limitations: string[],
  scenario?: Scenario
};
const percent = (v: number | null) => v == null ? 'N/A' : (v * 100).toFixed(1) + '%';

function FinancialScenario({ scenario: s }: { scenario: Scenario }) {
  const initial = {
    order: s.order_amount_cents == null ? '' : String(s.order_amount_cents / 100),
    probability: s.probability == null ? '' : String(s.probability * 100),
    stress: s.stress_probability == null ? '' : String(s.stress_probability * 100),
    minutes: String(s.review_minutes),
    hourly: String(s.hourly_cents / 100),
    prevention: String(s.prevention_fraction * 100)
  };
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const inputs = { ...initial, ...overrides };
  const n = (field: keyof typeof initial) => inputs[field].trim() === '' ? null : Number(inputs[field]);
  const order = n('order'),
    p = n('probability'),
    stress = n('stress'),
    minutes = n('minutes'),
    hourly = n('hourly'),
    prevention = n('prevention');
  const valid = order != null && order >= 0 && p != null && p >= 0 && p <= 100 && stress != null && stress >= p &&
    stress <= 100 &&
    minutes != null &&
    minutes >= 0 &&
    hourly != null &&
    hourly >= 0 &&
    prevention != null &&
    prevention > 0 &&
    prevention <= 100 &&
    Object.values(inputs).every(v => Number.isFinite(Number(v)));
  const exposure = valid ? Math.round(order! * 100) + s.fee_cents : null;
  const review = valid ? Math.round(minutes! / 60 * hourly! * 100) : null;
  const expected = exposure == null ? null : Math.round(exposure * p! / 100),
    high = exposure == null ? null : Math.round(exposure * stress! / 100);
  const threshold = exposure && review != null ? review / (exposure * prevention! / 100) : null;
  return <div className="financial-scenario">
    <div className="section-line">
      <h4><Icon name="money" />Financial scenario</h4>
      <Badge tone="amber">Assumptions, not a forecast</Badge>
    </div>
    <div className="scenario-metrics">
      <div>
        <strong>{money(expected)}</strong>
        <span>Estimated loss</span>
        <small>Probability × chargeback exposure</small>
      </div>
      <div><strong>{money(high)}</strong><span>Stress loss</span><small>Higher-rate scenario</small></div>
      <div>
        <strong>{money(review)}</strong>
        <span>Review cost</span>
        <small>Minutes × hourly cost</small>
      </div>
      <div>
        <strong>{percent(threshold)}</strong>
        <span>Break-even rate</span>
        <small>Review cost ÷ avoidable exposure</small>
      </div>
    </div>
    {
      valid &&
      <div className="scenario-rates">
        {
          [
            ['Expected scenario', p! / 100],
            ['Stress scenario', stress! / 100],
            ['Break-even', threshold || 0]
          ].map(([label, rate]) => <div key={String(label)}>
            <span>{label}</span>
            <div><i style={{ width: Math.min(100, Number(rate) * 100) + '%' }} /></div>
            <strong>{percent(Number(rate))}</strong>
          </div>)
        }
      </div>
    }
    <p className="small">Exposure per chargeback: <strong>{money(exposure)}</strong>, including the {money(s.fee_cents)} fee. The order value initially uses the requested refund as a proxy.</p>
    <p className="small muted">The initial rates describe recorded outcomes. Missing outcomes can make actual losses higher. Review
      savings depend on how many chargebacks review can prevent.</p>
    <details className="scenario-assumptions">
      <summary>Adjust scenario assumptions</summary>
      <p className="small muted">These values only change this calculation. They do not edit the request, route or policy.</p>
      <div className="scenario-inputs">
        {
          ([
            ['order', 'Order value (USD)', 0, 10000000, '.01'],
            ['minutes', 'Review time (minutes)', 0, 120, '.1'],
            ['hourly', 'Reviewer cost (USD / hour)', 0, 10000, '.01'],
            ['probability', 'Expected scenario (%)', 0, 100, '.1'],
            ['stress', 'Stress scenario (%)', 0, 100, '.1'],
            ['prevention', 'Chargebacks prevented by review (%)', .1, 100, '.1'],
          ] as const).map(([key, label, min, max, step]) => <label key={key}>
            {label}
            <input
              type="number"
              value={inputs[key]}
              min={min}
              max={max}
              step={step}
              onChange={e => setOverrides(old => ({ ...old, [key]: e.target.value }))}
            />
          </label>)
        }
      </div>
      {
        !valid &&
        <p className="amber-text">Enter valid amounts and rates. The stress rate must be at least the expected rate.</p>
      }
      <p className="small muted">{s.review_time_source}.</p>
      {s.assumptions.map(a => <p className="small muted" key={a}>{a}</p>)}
      <button className="text-button" onClick={() => setOverrides({})}>Reset assumptions</button>
    </details>
  </div>;
}
export function ChargebackRisk({ request: r }: { request: RequestRecord }) {
  const { data, error } = useQuery({
    queryKey: ['chargeback-risk', r.id, r.version],
    queryFn: () => api<Risk>('/requests/' + r.id + '/chargeback-risk')
  });
  return <RequestSection
    id="case-risk"
    title="Chargeback risk"
    icon="shield"
    subtitle="Historical context for your judgment. This assessment does not change the route."
  >
    {
      error ?
        <p className="alert error">Could not load historical risk context.</p> :
        !data ?
          <p>Loading risk context…</p> :
          <>
            <div className="section-line">
              <Badge tone={data.level === 'Elevated observed signal' ? 'amber' : 'neutral'}>{data.level}</Badge>
              <small className="muted">As of {data.as_of}</small>
            </div>
            <p>{data.segment} · {data.amount_band}</p>
            <div className="case-stat-grid">
              <div>
                <strong>{percent(data.cohort.recorded_rate)}</strong>
                <span>Recorded chargeback rate</span>
                <small>{data.cohort.chargebacks} of {data.cohort.total} similar approvals</small>
              </div>
              <div>
                <strong>{percent(data.baseline.recorded_rate)}</strong>
                <span>All historical approvals</span>
                <small>{data.baseline.chargebacks} of {data.baseline.total} approvals</small>
              </div>
              <div>
                <strong>{data.cohort.unknown}</strong>
                <span>Unknown outcomes</span>
                <small>{data.cohort.confirmed_clean} explicitly confirmed clean</small>
              </div>
            </div>
            <p className="small muted">{data.explanation}</p>
            {data.scenario && <FinancialScenario scenario={data.scenario} />}
            <div className="risk-financial">
              <Icon name="money" />
              <div>
                <strong>Financial exposure</strong>
                <p>Requested refund: {money(data.refund_cents)} · Chargeback fee: {money(data.chargeback_fee_cents)}
                </p>
                <p className="small muted">{data.financial_note}</p>
              </div>
            </div>
            <details>
              <summary>How this assessment is calculated</summary>
              {data.limitations.map(x => <p className="small muted" key={x}>{x}</p>)}
              {
                data.cohort.examples.map(x => <div className="fact" key={x.request_id}>
                  <strong>{x.request_id} · {money(x.amount_cents)}</strong>
                  <p>{x.note}</p>
                </div>)
              }
            </details>
          </>
    }
  </RequestSection>;
}

export function CustomerHistory({ request: r }: { request: RequestRecord }) {
  const { data, error } = useQuery({
    queryKey: ['customer-history', r.id, r.version],
    queryFn: () => api<{ historical: any[], current: RequestRecord[], caution: string }>('/requests/' + r.id + '/history')
  });
  const history = data?.historical.filter(h => h.request_id !== r.external_id).sort((a, b) => b.requested_at.localeCompare(a.requested_at)) ||
    [];
  const approved = history.filter(h => h.decision === 'approved').length;
  return <RequestSection
    id="case-customer"
    title="Customer history"
    icon="user"
    subtitle={'Customer ' + r.data.customer_id + ' · requests and refund history'}
  >
    {
      error ?
        <p className="alert error">Customer history could not be loaded.</p> :
        !data ?
          <p>Loading customer history…</p> :
          <>
            <div className="case-stat-grid">
              <div><strong>{r.data.tenure_months ?? 'N/A'}</strong><span>Months as a customer</span></div>
              <div>
                <strong>{r.data.prior_refunds_12m ?? 'N/A'}</strong>
                <span>Prior refunds in 12 months</span>
                <small>Reported in this request</small>
              </div>
              <div>
                <strong>{history.length + data.current.length}</strong>
                <span>Other requests on file</span>
                <small>{approved} historical full approvals</small>
              </div>
            </div>
            <p className="small muted">{data.caution}</p>
            {r.data.context_issues?.map(issue => <p className="alert warning" key={issue}>{issue}</p>)}
            {
              history.map(h => <div className="customer-event" key={h.request_id}>
                <Icon name="history" />
                <div>
                  <strong>{h.request_id}</strong>
                  <p>{h.requested_at} · {words(h.stated_reason)} · Requested {money(h.amount_cents)}</p>
                  <small>{h.outcome_note || 'Outcome unknown'}</small>
                </div>
                <Badge>{words(h.decision)}</Badge>
              </div>)
            }
            {
              data.current.map(h => <div className="customer-event" key={h.id}>
                <Icon name="file" />
                <div>
                  <strong>{h.external_id}</strong>
                  <p>{h.data.requested_at} · Requested {money(h.data.amount_cents)}</p>
                  <small>{h.decision?.reason || 'No decision recorded'}</small>
                </div>
                <Badge>{words(h.decision?.action || h.status)}</Badge>
              </div>)
            }
            {!history.length && !data.current.length && <p>No other requests in the imported records.</p>}
          </>
    }
  </RequestSection>;
}

