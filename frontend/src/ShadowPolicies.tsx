import { useState } from 'react';
import { policyLabel, usePolicyVersions } from './policyIdentity';
import { useQuery } from '@tanstack/react-query';
import { api, money, PageHeading, Metric, Empty } from './components';
import type { Act } from './components';
import { ActionTag, UiIcon } from './visualLanguage';

export const routeAction = (ev: any) => ev.action === 'auto_approve' ? 'auto_approve' : ev.queue === 'fraud' ? 'fraud' : 'review';
const percent = (value: number | null) => value === null ? 'N/A' : (value * 100).toFixed(1) + '%';
export function HumanReference({ label }: { label: any }) {
  return label ?
    <>
      <strong>
        {
          label.allowed_cents === null ?
            'Insufficient evidence' :
            label.action === 'rejected' ? 'Rejected · $0.00' : money(label.allowed_cents)
        }
      </strong>
      <small>
        {
          label.source === 'human_decision' ?
            'Reviewer decision' :
            label.source === 'historical_decision' ? 'Historical decision' : 'Recorded assessment'
        } · {label.actor}
      </small>
    </> :
    <span className="muted">Awaiting review</span>;
}
export function PolicyResult({ evaluation }: { evaluation: any }) {
  return evaluation ?
    <>
      <ActionTag action={routeAction(evaluation)} route />
      {
        evaluation.action === 'auto_approve' &&
        <strong className="shadow-amount">{money(evaluation.proposed_amount_cents)}</strong>
      }
      <small>{evaluation.explanation}</small>
    </> :
    <span className="muted">No comparable observation</span>;
}

export default function ShadowPolicies({ act, busy, onOpen }: { act: Act, busy: string, onOpen: (id: string) => void }) {
  const { data, error } = useQuery({
    queryKey: ['shadow-policies'],
    queryFn: () => api<any>('/shadow-policies'),
    refetchInterval: 5000
  });
  const [filter, setFilter] = useState('all');
  const { data: policies = [] } = usePolicyVersions();
  const label = (v: any) => policyLabel(v.version ?? policies.find(p => p.id === v.policy_id)?.version);
  if (error) return <div className="alert error">{(error as Error).message}</div>;
  if (!data) return <p role="status">Loading shared comparisons…</p>;
  const versions = data.versions.filter((v: any) => !v.stale);
  const rows = data.requests.filter((r: any) => filter === 'all' || filter === 'reviewed' && r.label?.allowed_cents != null ||
    filter === 'waiting' && r.label?.allowed_cents == null ||
    filter === 'different' &&
    Object.values(r.candidates).some((e: any) => routeAction(e) !== routeAction(r.baseline) ||
      (e.proposed_amount_cents || 0) !== (r.baseline.proposed_amount_cents || 0)));
  const metricsRows = [
    {
      id: data.current.id,
      label: policyLabel(data.current.version),
      metrics: data.current.metrics,
      current: true
    },
    ...versions.map((v: any) => ({ ...v, label: label(v) }))
  ];
  return <>
    <PageHeading
      title="Shadow policies"
      text="One request pool. One reviewer decision. Compare every checked policy with Current."
    />
    <section className="panel padded shadow-explainer">
      <UiIcon name="eye" size={25} />
      <div>
        <h2>Review requests once</h2>
        <p>Start Shadow manually after reviewing the Backtest results. Current handles the real workflow; all Shadow
          versions evaluate the same requests without executing refunds. Approve, partial refund or reject in
          Requests updates every comparison here.</p>
      </div>
    </section>
    <div className="metric-grid">
      <Metric
        label="Shared requests"
        value={String(data.compared_requests)}
        detail={
          data.excluded_requests ?
            `${data.excluded_requests} requests await comparable observations` :
            'Same cases for every policy below'
        }
      />
      <Metric
        label="Human decisions"
        value={String(data.reviewed_requests)}
        detail="Reused across all Shadow versions"
      />
      <Metric
        label="Shadow versions"
        value={String(versions.length)}
        detail="Running after successful backtests"
      />
      <Metric
        label="Awaiting review"
        value={String(data.compared_requests - data.reviewed_requests)}
        detail="Automatic payouts never assess themselves"
      />
    </div>
    {
      data.versions.filter((v: any) => v.stale).map((v: any) => <section className="panel padded shadow-stale" key={v.id}>
        <div>
          <h3>{label(v)}</h3>
          <p>Checks need updating after a change to Current, the model or the engine. Previous evidence is retained;
            it is excluded from this live comparison.</p>
        </div>
        <button
          disabled={!!busy}
          onClick={
            async () => {
              const r = await act(
                'recheck-shadow',
                () => api<any>('/trials/' + v.id + '/recheck', {}),
                'Backtest complete. This version is observing the shared request pool again.'
              );
              if (r) onOpen((r as any).experiment.id)
            }
          }
        >Recheck this version</button>
      </section>)
    }
    <section className="panel">
      <div className="padded">
        <h2>Policy comparison</h2>
        <p>All numbers use the same {data.compared_requests} requests, including existing backlog. Agreement compares automatic amounts with human decisions; it
          is not proof of a correct financial outcome.</p>
      </div>
      <div className="table-scroll">
        <table className="shadow-comparison">
          <thead>
            <tr>
              <th>Policy</th>
              <th>Review</th>
              <th>Fraud Review</th>
              <th>Auto Approve</th>
              <th>Auto amount</th>
              <th>Compared with reviewer</th>
              <th>Above reviewer amount</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {
              metricsRows.map((v: any) => {
                const m = v.metrics;
                return <tr key={v.id}>
                  <td><strong>{v.label}</strong><small>{v.current ? 'Current' : 'Shadow · no payments'}</small></td>
                  <td>{m.routes.review}</td>
                  <td>{m.routes.fraud}</td>
                  <td>{m.auto_count}<small>{percent(m.auto_rate)} of shared requests</small></td>
                  <td>{money(m.payout_cents)}</td>
                  <td>
                    {m.auto_reviewed ? `${m.auto_agreed} / ${m.auto_reviewed}` : 'No reviewed auto proposals'}
                    <small>
                      {m.auto_reviewed ? percent(m.agreement_rate) + ' same amount' : m.unreviewed_auto + ' await review'}
                    </small>
                  </td>
                  <td>{money(m.overpayment_cents)}<small>{m.overpayment_cases} cases · potential excess</small></td>
                  <td>{!v.current && <button onClick={() => onOpen(v.id)}>Open checks</button>}</td>
                </tr>
              })
            }
          </tbody>
        </table>
      </div>
    </section>
    {
      !data.versions.length &&
      <Empty
        title="No Shadow versions yet"
        detail="Save a policy version and run its backtest. It will join this shared comparison automatically."
      />
    }
    <section className="panel">
      <div className="padded">
        <h2>Same request, different policies</h2>
        <p>Each row has one human reference. No duplicate reviews are needed for additional policies.</p>
        <div className="tabs">
          {
            [
              ['all', 'All requests'],
              ['different', 'Policies differ'],
              ['reviewed', 'Reviewed'],
              ['waiting', 'Awaiting review']
            ].map(([id, label]) => <button className={filter === id ? 'selected' : ''} onClick={() => setFilter(id)} key={id}>
              {label}
            </button>)
          }
        </div>
      </div>
      <div className="table-scroll">
        <table className="shadow-case-matrix">
          <thead>
            <tr>
              <th>Request</th>
              <th>Reviewer decision</th>
              <th>{policyLabel(data.current.version)}<small>Current</small></th>
              {versions.map((v: any) => <th key={v.id}>{label(v)}</th>)}
            </tr>
          </thead>
          <tbody>
            {
              rows.map((r: any) => <tr key={r.request_id}>
                <td><strong>{r.external_id}</strong><small>{money(r.amount_cents)}</small></td>
                <td><HumanReference label={r.label} /></td>
                <td><PolicyResult evaluation={r.baseline} /></td>
                {versions.map((v: any) => <td key={v.id}><PolicyResult evaluation={r.candidates[v.id]} /></td>)}
              </tr>)
            }
          </tbody>
        </table>
      </div>
      {
        !rows.length &&
        <Empty
          title="No requests in this view"
          detail="Change the filter or import requests through Data."
        />
      }
    </section>
    <p className="small muted">
      {data.note} Open a version's release readiness to see its prospective cohort and qualification gates.</p>
  </>;
}
