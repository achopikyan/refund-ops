import HistoricalAnalysis from './HistoricalAnalysis';
import { useEffect, useState } from 'react';
import { policyLabel, usePolicyVersions } from './policyIdentity';
import { useQuery } from '@tanstack/react-query';
import { api, money, words, Badge, Metric, Empty } from './components';
import type { Act, Policy } from './components';
import { UiIcon } from './visualLanguage';
import ShadowSetup from './ShadowSetup';
import DecisionReport, { ShadowDecisionReport } from './DecisionReport';

export default function PolicyJourney({ activePolicy, draft, draftId, initialTrialId, act, busy, onBack, stage, setStage }: {
  activePolicy: Policy,
  draft: Policy | null,
  draftId: string | null,
  initialTrialId: string,
  act: Act,
  busy: string,
  onBack: () => void,
  stage: string,
  setStage: (stage: string) => void
}) {
  const [id, setId] = useState(initialTrialId),
    [creating, setCreating] = useState(!!draft),
    [policy, setPolicy] = useState(draft || activePolicy),
    [shadowPending, setShadowPending] = useState(false),
    [reason, setReason] = useState('');
  const { data: trials = [], error } = useQuery({ queryKey: ['trials'], queryFn: () => api<any[]>('/trials') });
  const eid = id || trials.find(t => t.source_policy_id === draftId)?.id;
  const { data: report } = useQuery({
    queryKey: ['trial', eid],
    queryFn: () => api<any>('/trials/' + eid),
    enabled: !!eid,
    refetchInterval: 5000
  });
  const { data: setup } = useQuery({ queryKey: ['backtest-plan'], queryFn: () => api<{ history_count: number }>('/setup') });
  const { data: budget } = useQuery({
    queryKey: ['release-budget'],
    queryFn: () => api<any>('/release-budget'),
    enabled: stage === 'rollout'
  });
  useEffect(() => { if (draft) { setPolicy(draft); setCreating(true) } }, [draft]);
  const trial = report?.experiment, fin = report?.financial;
  const { data: policies = [] } = usePolicyVersions();
  const selectedVersion = policies.find(p => p.id === (creating ? draftId : trial?.source_policy_id || trial?.activated_policy_id));
  const currentVersion = selectedVersion?.status === 'active';
  const canOpenShadow = !!selectedVersion && !currentVersion;
  useEffect(
    () => { if (currentVersion && stage !== 'backtest') setStage('backtest') },
    [currentVersion, stage, setStage]
  );
  const versionLabel = selectedVersion ? policyLabel(selectedVersion.version) : creating ? 'New version' : 'Policy version';
  const stale = !!report?.stale_reasons?.length;
  useEffect(
    () => {
      if (report?.replacement_checks_id) { setId(report.replacement_checks_id); setCreating(false); setStage('backtest') }
    },
    [report?.replacement_checks_id]
  );
  const action = (label: string, suffix: string, body: unknown = {}) => act(label, () => api('/trials/' + eid + '/' + suffix, body));
  return <>
    {stage === 'backtest' && <HistoricalAnalysis analysis={report?.history_analysis} />}
    <>{error && <div className="alert error">{(error as Error).message}</div>}</>
    {
      creating && stage === 'backtest' &&
      <section className="panel padded narrow">
        <h2>Backtest this version</h2>
        <p>
          {versionLabel} · {policy.rules.length} rules. The rules are saved. The checks and release criteria belong to this version.</p>
        <div className="backtest-plan">
          <h3>Historical replay plan</h3>
          <dl>
            <div><dt>Requests</dt><dd>{setup?.history_count ?? 'Loading…'} historical records</dd></div>
            <div><dt>Policy</dt><dd>{versionLabel}</dd></div>
            <div><dt>Rules</dt><dd>Every enabled rule and all policy-wide checks</dd></div>
            <div>
              <dt>Evidence</dt>
              <dd>Full saved LLM extraction for every historical request; outcomes never enter evaluation</dd>
            </div>
            <div>
              <dt>Results</dt>
              <dd>Routing changes, automatic proposals, monetary exposure and rule coverage</dd>
            </div>
          </dl>
          <p className="small muted">This replay makes no payments. Historical approvals are observations, not correctness labels.</p>
        </div>
        <div className="button-row">
          <button
            className="primary"
            disabled={!!busy}
            onClick={
              async () => {
                const value = await act(
                  'create-trial',
                  async () => {
                    const saved = draftId ? { id: draftId } : await api<{ id: string }>('/policies/drafts', policy);
                    const check = await api<any>('/trials', { policy, policy_id: saved.id });
                    await api('/trials/' + check.id + '/backtest', {});
                    return check
                  }
                );
                if (value) { setId((value as any).id); setCreating(false); setStage('backtest') }
              }
            }
          >Run backtest</button>
          <button onClick={onBack}>Cancel</button>
        </div>
      </section>
    }
    {
      creating && canOpenShadow && stage !== 'backtest' &&
      <section className="panel padded">
        <h2>{stage === 'shadow' ? 'Shadow has not started' : 'Release checks have not started'}</h2>
        <p>Run Backtest for {versionLabel} first. After Backtest, start Shadow explicitly when you are ready.</p>
        <button className="primary" onClick={() => setStage('backtest')}>Open Backtest</button>
      </section>
    }
    {
      !creating && trial &&
      <>
        <div className="section-line">
          <div className="button-row"><Badge>{words(trial.status)}</Badge></div>
        </div>
        {
          stale &&
          <div className="alert warning">
            <strong>Updating Backtest automatically</strong>
            <p>The evaluation environment changed. New results will appear here; this policy keeps its rules and version
              number. Shadow will remain off until you start it again.</p>
          </div>
        }
        {
          stage === 'backtest' &&
          <>
            <section className="panel padded">
              <h2>Replay history</h2>
              <p>Evaluate this policy on the historical inputs. Outcomes remain diagnostic context; incomplete evidence
                remains visible.</p>
              <button
                className="primary"
                disabled={
                  !!busy || stale || report.replay_job?.status === 'pending' ||
                  !['draft', 'backtested', 'shadow'].includes(trial.status)
                }
                onClick={() => action('backtest', 'backtest')}
              >
                {stale ? 'Updating automatically' : 'Run historical replay'}
              </button>
            </section>
            {
              report.replay_job?.status === 'pending' &&
              <p role="status">Backtest is queued and will be saved automatically after extraction finishes.</p>
            }
            {report.replay_job?.status === 'failed' && <p className="alert error">{report.replay_job.error}</p>}
            {trial.backtest && <DecisionReport report={trial.backtest.decision_report} label={versionLabel} />}

            {
              canOpenShadow &&
              <div className="next-stage">
                {
                  trial.status === 'backtested' ?
                    <>
                      <p>Backtest is complete. Shadow has not started.</p>
                      <button className="primary" onClick={() => setStage('shadow')}>Set up Shadow<UiIcon name="eye" />
                      </button>
                    </> :
                    <>
                      <p>
                        {
                          trial.backtest ?
                            'Shadow observations are available in the Shadow tab.' :
                            'Complete Backtest before starting Shadow.'
                        }
                      </p>
                      <button disabled={!trial.backtest} onClick={() => setStage('shadow')}>Open Shadow<UiIcon name="arrow" />
                      </button>
                    </>
                }
              </div>
            }
          </>
        }
        {canOpenShadow && stage === 'shadow' && <ShadowSetup trial={trial} onPending={setShadowPending} />}
        {
          canOpenShadow && stage === 'shadow' && trial.status === 'backtested' &&
          <section className="panel padded">
            <h2>Shadow has not started</h2>
            <p>Start observing this policy on incoming requests. It records proposals without making payments.</p>
            <button
              className="primary"
              disabled={!!busy || shadowPending || stale}
              onClick={() => action('start', 'start')}
            >
              <UiIcon name="eye" />Start Shadow</button>
          </section>
        }
        {
          canOpenShadow && stage === 'shadow' && trial.status !== 'backtested' &&
          <>
            <section className="panel padded">
              <h2>Shared requests, one review</h2>
              <p>Current and this version evaluate the same request pool. A normal approval, partial refund or rejection
                in Requests is reused here automatically. This version never executes a refund in Shadow.</p>
              <div className="button-row">
                <button disabled={!!busy || trial.status !== 'shadow'} onClick={() => action('capture', 'capture')}>Refresh comparisons</button>
              </div>
              {
                trial.status === 'shadow' && report.analysis &&
                <p className="small muted" role="status">Evidence analysis: {report.analysis.completed}/{report.analysis.total} open requests complete. {
                  report.analysis.blocked + report.analysis.unavailable + report.analysis.failed > 0 ?
                    'Some requests need attention; check the AI connection in Settings.' :
                    report.analysis.running + report.analysis.pending > 0 ?
                      'Updating automatically.' :
                      'Updates automatically when request data changes.'
                }
                </p>
              }
              <p className="small muted">Comparisons below include existing requests. Release qualification separately uses new arrivals observed
                before the reviewer decision.</p>
            </section>
            <ShadowDecisionReport reports={report.decision_reports} label={versionLabel} />
            <div className="next-stage">
              <p>
                {fin.prospective} new arrivals | {fin.backlog} existing requests | {fin.reviewed_customer_groups} reviewed customer groups from new arrivals</p>
              <button className="primary" onClick={() => setStage('rollout')}>Review release readiness</button>
            </div>
          </>
        }
        {
          canOpenShadow && stage === 'rollout' &&
          <>
            <DecisionReport report={report.decision_reports?.prospective} label={versionLabel} />
            <section className="panel padded">
              <div className="section-line">
                <h2>Release readiness</h2>
                <Badge tone={report.gate.passed ? 'green' : 'amber'}>
                  {report.gate.passed ? 'Ready for decision' : 'More evidence required'}
                </Badge>
              </div>
              <ul className="lab-blockers">{report.gate.blockers.map((b: string) => <li key={b}>{b}</li>)}</ul>
              <details>
                <summary>Economic assumptions and limits</summary>
                <p>{fin.projection_assumption}</p>
                <p>{fin.economic_assumption}</p>
                <p>{fin.unknown_outcome_policy}</p>
                <p>Actual order amount is unavailable. A $25 chargeback fee plus order amount is not treated as proven
                  avoided loss.</p>
                <pre className="lab-json">{JSON.stringify(trial.settings, null, 2)}</pre>
              </details>
              {
                ['draft', 'backtested', 'shadow'].includes(trial.status) &&
                <>
                  <label>Manager reason<textarea
                    value={reason}
                    onChange={e => setReason(e.target.value)}
                    placeholder="Explain the release decision or why the version should stop."
                  />
                  </label>
                  <div className="button-row">
                    <button
                      className="primary"
                      disabled={!!busy || !report.gate.passed || !reason.trim()}
                      onClick={() => action('promote', 'promote', { reason })}
                    >Activate with limits</button>
                    <button disabled={!!busy || !reason.trim()} onClick={() => action('stop', 'stop', { reason })}>Stop this version</button>
                  </div>
                  <p className="small muted">Activation makes this exact version Current. Eligible Auto Approve requests then process automatically
                    within its saved payment limits.</p>
                </>
              }
            </section>
            {
              budget &&
              <section className="panel padded">
                <h2>Active execution budget</h2>
                <div className="metric-grid">
                  <Metric
                    label="Release spend"
                    value={money(budget.release_spent_cents)}
                    detail={'Limit ' + money(budget.settings.release_cents)}
                  />
                  <Metric
                    label="Daily spend"
                    value={money(budget.daily_spent_cents)}
                    detail={'Limit ' + money(budget.settings.daily_cents)}
                  />
                  <Metric
                    label="Operations"
                    value={String(budget.release_count)}
                    detail={'Limit ' + budget.settings.release_count}
                  />
                  <Metric
                    label="Per-customer daily cap"
                    value={money(budget.settings.customer_daily_cents)}
                    detail="Automatic refunds · UTC day"
                  />
                </div>
                <p>Source: {budget.source === 'approved_trial' ? 'Qualified policy version' : 'No qualified version yet'}. Each payment checks the remaining budget atomically. Blocked requests remain available for review.</p>
              </section>
            }
          </>
        }
        <details className="panel padded">
          <summary>Frozen policy, identity and assumptions</summary>
          <pre className="lab-json">
            {
              JSON.stringify(
                {
                  version: selectedVersion?.version,
                  policy: Object.fromEntries(Object.entries(trial.policy).filter(([key]) => key !== 'name')),
                  settings: trial.settings,
                  manifest: trial.manifest
                },
                null,
                2
              )
            }
          </pre>
        </details>
      </>
    }
    {
      !creating && !trial &&
      <Empty title="No version selected" detail="Choose a saved policy version to inspect its checks." />
    }
  </>
}
