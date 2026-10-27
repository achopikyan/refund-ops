import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import CurrentMonitoring from './CurrentMonitoring';
import { api, Metric, money, Badge, ReasonBadge } from './components';
import { UiIcon, ActionTag } from './visualLanguage';

export default function CurrentPerformance({ onPolicy, policyId }: { onPolicy: (id: string) => void, policyId: string }) {
  const [tab, setTab] = useState('queue');
  const { data, error } = useQuery({
    queryKey: ['policy-performance', policyId],
    queryFn: () => api<any>('/policies/' + policyId + '/performance'),
    refetchInterval: 5000
  });
  if (error) return <div className="alert error">{(error as Error).message}</div>;
  if (!data) return <p role="status">Loading Current performance…</p>;
  const { queue, budget } = data, o = data.operations;
  const complete = queue.ready - queue.analysis_attention,
    running = data.mode === 'simulate',
    isCurrent = data.policy.is_current;
  const section = isCurrent ? tab : 'results';
  return <>
    <section className="panel current-dashboard" aria-label="Policy performance">
      <header className="current-dashboard-header">
        <div>
          <h2>Performance</h2>
          <p>
            {
              isCurrent ?
                'Live queue and recorded results of this policy.' :
                'Recorded results from this version’s active periods. The live queue belongs to Current.'
            }
          </p>
        </div>
        {
          isCurrent &&
          <Badge tone={running ? 'green' : 'amber'}>
            {running ? 'Automatic execution on' : 'Server update needed'}
          </Badge>
        }
      </header>
      {
        isCurrent &&
        <nav className="decision-tabs" aria-label="Performance sections">
          {
            [
              ['queue', 'queue', 'Queue now'],
              ['results', 'chart', 'Decisions & outcomes'],
              ['execution', 'shield', 'Execution & limits']
            ].map(([id, icon, label]) => <button
              key={id}
              aria-pressed={tab === id}
              className={tab === id ? 'selected' : ''}
              onClick={() => setTab(id)}
            >
              <UiIcon name={icon} />
              {label}
            </button>)
          }
        </nav>
      }
      <div className="decision-body">
        {
          section === 'queue' &&
          <>
            <div className="current-scope">
              <strong>Live snapshot</strong>
              <span>Open requests only. Completed decisions are in Decisions & outcomes.</span>
            </div>
            <div className="decision-stats">
              <Metric
                label="Open requests"
                value={String(queue.open)}
                detail={`${queue.ready} ready · ${queue.waiting} waiting or on hold`}
              />
              <Metric
                label="Auto Approve pending"
                value={String(queue.routes.auto_approve)}
                detail="Proposals awaiting automatic processing; no payment yet"
              />
              <Metric
                label="Needs review"
                value={String(queue.routes.review + queue.routes.fraud)}
                detail={`${queue.routes.review} Review · ${queue.routes.fraud} Fraud Review`}
              />
              <Metric
                label="Evidence complete"
                value={`${complete} / ${queue.ready}`}
                detail="Ready queue only; extraction completeness is not factual accuracy"
              />
            </div>
            <div className="decision-two">
              <section className="decision-block current-routing">
                <h3>Where ready requests go</h3>
                <p className="small muted">Each of the {queue.ready} ready requests has one route.</p>
                {
                  ['auto_approve', 'review', 'fraud'].map(route => <div className={'performance-route route-' + route} key={route}>
                    <ActionTag action={route} route />
                    <div className="performance-track">
                      <i style={{ width: (queue.routes[route] / Math.max(1, queue.ready) * 100) + '%' }} />
                    </div>
                    <strong>{queue.routes[route]}</strong>
                    <span>{queue.ready ? Math.round(queue.routes[route] / queue.ready * 100) + '%' : 'N/A'}</span>
                  </div>)
                }
                {!queue.ready && <p>No requests are ready for processing.</p>}
              </section>
              <section className="decision-block">
                <h3>Why requests take these routes</h3>
                <p className="small muted">One primary routing reason per ready request.</p>
                {
                  queue.reasons.map((r: any) => <div className="performance-reason" key={r.code || r.label}>
                    <ReasonBadge code={r.code} label={r.label} />
                    <strong>{r.count}</strong>
                  </div>)
                }
                {!queue.reasons.length && <p className="muted">No ready requests.</p>}
              </section>
            </div>
            <div className="decision-two">
              <section className="decision-block">
                <h3>Waiting and evidence</h3>
                <dl className="decision-definitions">
                  <div><dt>Waiting or on hold</dt><dd>{queue.waiting}</dd></div>
                  <div><dt>Ready requests with incomplete evidence</dt><dd>{queue.analysis_attention}</dd></div>
                  <div>
                    <dt>Automatic proposals blocked by execution checks</dt>
                    <dd>{queue.execution_blocked ?? 'Unknown'}</dd>
                  </div>
                </dl>
                <p className="small muted">Analysis runs automatically. Requests blocked by payment checks remain available for staff review.</p>
              </section>
              <section className="decision-block">
                <h3>Time in the open queue</h3>
                <dl className="decision-definitions">
                  {
                    ['Under 1 hour', '1 to 24 hours', '1 to 7 days', 'Over 7 days'].map(band => <div key={band}><dt>{band}</dt><dd>{o.queue_age_bands[band] || 0}</dd></div>)
                  }
                </dl>
                <p className="small muted">Since import into this application, including waiting and holds. Oldest: {o.oldest_open_hours == null ? 'none' : o.oldest_open_hours.toFixed(1) + ' hours'}. This does not measure reviewer work time.</p>
              </section>
            </div>
          </>
        }
        {section === 'results' && <CurrentMonitoring data={data} />}
        {
          section === 'execution' &&
          <>
            <section className="current-execution">
              <span className="manager-icon"><UiIcon name="check" /></span>
              <div>
                <h3>Automatic execution <Badge tone={running ? 'green' : 'amber'}>{running ? 'On' : 'Server update needed'}</Badge>
                </h3>
                <p>Current processes eligible Auto Approve requests automatically after evidence analysis. Shadow versions
                  never make payments.</p>
                <p className="small muted">Each payment rechecks the current policy, evidence, duplicate protection and remaining budgets. A blocked
                  request goes to Review; other eligible requests keep processing.</p>
              </div>
            </section>
            <section className="decision-block">
              <div className="section-line">
                <div>
                  <h3>Current policy limits</h3>
                  <p className="small muted">Automatic refunds only. Daily limits use UTC; previous spend survives a rollback.</p>
                </div>
                <button onClick={() => onPolicy(data.policy.id)}>View policy settings<UiIcon name="arrow" />
                </button>
              </div>
              <div className="table-scroll">
                <table className="current-limits">
                  <thead><tr><th>Limit</th><th>Used</th><th>Maximum</th><th>Remaining</th></tr></thead>
                  <tbody>
                    <tr>
                      <th>This version · refund amount</th>
                      <td>{money(budget.release_spent_cents)}</td>
                      <td>{money(budget.settings.release_cents)}</td>
                      <td>{money(Math.max(0, budget.settings.release_cents - budget.release_spent_cents))}</td>
                    </tr>
                    <tr>
                      <th>This version · payments</th>
                      <td>{budget.release_count}</td>
                      <td>{budget.settings.release_count}</td>
                      <td>{Math.max(0, budget.settings.release_count - budget.release_count)}</td>
                    </tr>
                    <tr>
                      <th>Today · all versions</th>
                      <td>{money(budget.daily_spent_cents)}</td>
                      <td>{money(budget.settings.daily_cents)}</td>
                      <td>{money(Math.max(0, budget.settings.daily_cents - budget.daily_spent_cents))}</td>
                    </tr>
                    <tr>
                      <th>Single payment</th>
                      <td>Per request</td>
                      <td>{money(budget.settings.max_single_cents)}</td>
                      <td>Checked before payment</td>
                    </tr>
                    <tr>
                      <th>Customer · per day, all versions</th>
                      <td>Per customer</td>
                      <td>{money(budget.settings.customer_daily_cents)}</td>
                      <td>Checked before payment</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
            <p className="small muted">All payments are local simulations. No real money moves.</p>
          </>
        }
      </div>
      <footer className="current-dashboard-footer">
        <span>Snapshot {new Date(data.provenance.as_of).toLocaleTimeString()} · updates every 5 seconds</span>
        <span>History and Shadow results are excluded.</span>
      </footer>
    </section>
  </>;
}