import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, PageHeading, Empty, Badge, Modal, money } from './components';
import type { Act, PolicyRecord, Evaluation, ExecutionLimits } from './components';
import { UiIcon, StageTag } from './visualLanguage';
import { policyLabel } from './policyIdentity';
import { usePolicyLibrary, nextStep, stageLabel } from './policyManagement';
import type { ManagedVersion } from './policyManagement';
import { PolicyResult } from './ShadowPolicies';
import PolicySettings from './PolicySettings';
import CreatePolicyDialog from './CreatePolicyDialog';

type Props = {
  workspaceKey: string,
  selectedId: string | null,
  onSelect: (id: string | null) => void,
  onCreate: (p: PolicyRecord, ruleId?: string) => void,
  onScratch: () => void,
  act: Act,
  busy: string
};
export default function PolicyVersions(props: Props) {
  const { data, error, isPending } = usePolicyLibrary();
  const [filter, setFilter] = useState('all');
  const [creating, setCreating] = useState(false);
  const [release, setRelease] = useState<{ version: ManagedVersion, kind: 'activate' | 'rollback' } | null>(null);
  const current = data?.versions.find(v => v.id === data.current_id),
    selected = data?.versions.find(v => v.id === props.selectedId);
  if (error) return <div className="alert error">{(error as Error).message}</div>;
  if (isPending || !data) return <p role="status">Loading policy versions…</p>;
  const rows = data.versions.filter(v => filter === 'all' || v.stage === filter);
  return <>
    {
      selected ?
        <PolicySettings
          workspaceKey={props.workspaceKey}
          key={selected.id}
          version={selected}
          onRollback={() => setRelease({ version: selected, kind: 'rollback' })}
        /> :
        <>

          <div className="manager-page-heading">
            <PageHeading
              title="Policies"
              text="Create a policy from an existing version or start from scratch. Open a version to inspect its rules and tests."
            />
            <button className="primary" disabled={!!props.busy} onClick={() => setCreating(true)}>
              <UiIcon name="branch" />Create policy</button>
          </div>
          {
            current &&
            <section className="manager-section manager-green current-version-card">
              <div className="manager-section-title">
                <span className="manager-icon"><UiIcon name="check" size={24} /></span>
                <div>
                  <div className="eyebrow">CURRENT POLICY</div>
                  <h2>{policyLabel(current.version)}</h2>
                  <p>
                    {current.data.rules.length} {current.data.rules.length === 1 ? 'rule' : 'rules'} serving the review workflow. Changes are saved as a new version.</p>
                </div>
              </div>
              <div className="button-row">
                <button onClick={() => props.onSelect(current.id)}>Open version</button>
              </div>
            </section>
          }
          <section className="panel version-library">
            <div className="padded">
              <div className="section-line">
                <h2>All versions <span className="muted">{data.versions.length}</span></h2>
              </div>
              <div className="tabs" aria-label="Filter policy versions">
                {
                  [
                    ['all', 'All'],
                    ['draft', 'Draft'],
                    ['backtested', 'Backtested'],
                    ['shadow', 'Shadow'],
                    ['current', 'Current'],
                    ['archived', 'Archived'],
                    ['stopped', 'Stopped']
                  ].map(([id, label]) => <button key={id} className={filter === id ? 'selected' : ''} onClick={() => setFilter(id)}>
                    {label}
                  </button>)
                }
              </div>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr><th>Version</th><th>Status</th><th>Rules</th><th>Next step</th><th>Created</th><th /></tr>
                </thead>
                <tbody>
                  {
                    rows.map(v => <tr key={v.id}>
                      <td>
                        <button className="text-button version-link" onClick={() => props.onSelect(v.id)}>
                          {policyLabel(v.version)}
                        </button>
                        {v.parent_id && <small>From v{data.versions.find(p => p.id === v.parent_id)?.version}</small>}
                      </td>
                      <td><VersionStatus version={v} /></td>
                      <td>{v.data.rules.filter(r => r.enabled).length}<small>of {v.data.rules.length} enabled</small></td>
                      <td className="version-next">{nextStep(v)}</td>
                      <td>{formatDate(v.created_at)}</td>
                      <td>
                        <div className="button-row version-row-actions">
                          <button onClick={() => { props.onSelect(v.id) }} aria-label={'Open ' + policyLabel(v.version)}>Open<UiIcon name="arrow" size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>)
                  }
                </tbody>
              </table>
            </div>
            {
              !rows.length &&
              <Empty title="No versions in this state" detail="Choose another filter or create a new version." />
            }
          </section>
          <details className="manager-section manager-slate release-history">
            <summary><UiIcon name="history" />Release history <Badge>{data.history.length}</Badge></summary>
            <p>Each activation and rollback keeps its version numbers and manager explanation.</p>
            {
              data.history.length ?
                data.history.map((h, i) => <div className="release-event" key={i}>
                  <UiIcon name={h.type.includes('rollback') ? 'history' : 'rocket'} />
                  <div>
                    <strong>{h.from_version ? `Policy v${h.from_version} → ` : ''}{policyLabel(h.to_version)}</strong>
                    <p>{h.reason}</p>
                    <small>
                      {h.type.includes('rollback') ? 'Rollback' : 'Activation'} · {formatDate(h.created_at, true)}
                    </small>
                  </div>
                </div>) :
                <p className="muted">The initial version is current. No releases have been made yet.</p>
            }
          </details>
        </>
    }
    {
      creating &&
      <CreatePolicyDialog
        policies={data.versions}
        currentId={data.current_id}
        onExisting={p => props.onCreate(p)}
        onScratch={props.onScratch}
        onClose={() => setCreating(false)}
      />
    }
    {
      release && current &&
      <ReleaseDialog
        version={release.version}
        current={current}
        kind={release.kind}
        act={props.act}
        busy={props.busy}
        onClose={() => setRelease(null)}
        onDone={() => { props.onSelect(release.version.id); setRelease(null) }}
      />
    }
  </>;
}
export function VersionStatus({ version: v }: { version: ManagedVersion }) {
  return v.stale ?
    <span className="semantic-tag tone-amber">
      <UiIcon name="history" size={15} />Updating Backtest</span> :
    v.stage === 'shadow' && v.readiness.passed ?
      <span className="semantic-tag tone-teal"><UiIcon name="rocket" size={15} />{stageLabel(v)}</span> :
      <StageTag stage={v.stage === 'current' ? 'active' : v.stage} />;
}
export const formatDate = (value: string, time = false) => new Date(value).toLocaleString(
  'en-US',
  time ?
    { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' } :
    { month: 'short', day: 'numeric' }
);

type RollbackPreview = {
  id: string;
  eligible: number;
  excluded: number;
  warnings?: string[];
  changes: { id: string; old: Evaluation; new: Evaluation }[]
};
type ReleaseReport = { gate: { passed: boolean; blockers: string[] }; experiment: { settings: ExecutionLimits } };

function ReleaseDialog({ version, current, kind, act, busy, onClose, onDone }: {
  version: ManagedVersion,
  current: ManagedVersion,
  kind: 'activate' | 'rollback',
  act: Act,
  busy: string,
  onClose: () => void,
  onDone: () => void
}) {
  const [reason, setReason] = useState(''),
    [preview, setPreview] = useState<RollbackPreview | null>(null),
    [localError, setLocalError] = useState('');
  const { data: report, error } = useQuery({
    queryKey: ['trial', version.checks_id],
    queryFn: () => api<ReleaseReport>('/trials/' + version.checks_id),
    enabled: kind === 'activate' && !!version.checks_id
  });
  const prepare = async () => {
    setLocalError('');
    try { setPreview(await api<RollbackPreview>('/policies/' + version.id + '/rollback-preview', {})) } catch (e) { setLocalError((e as Error).message) }
  };
  const [preparing, setPreparing] = useState(false);
  const submit = async () => {
    setLocalError('');
    const result = await act(
      kind,
      async () => {
        try {
          return kind === 'activate' ?
            await api('/trials/' + version.checks_id + '/promote', { reason }) :
            await api('/policies/' + version.id + '/rollback', { preview_id: preview!.id, reason })
        } catch (e) { setLocalError((e as Error).message); throw e }
      },
      `${policyLabel(version.version)} is now Current. Eligible Auto Approve requests will process automatically.`
    );
    if (result) onDone(); else if (kind === 'rollback') setPreview(null)
  };
  const ready = kind === 'rollback' ? !!preview : report?.gate.passed;
  return <Modal
    title={
      kind === 'activate' ?
        'Activate ' + policyLabel(version.version) :
        'Rollback to ' + policyLabel(version.version)
    }
    onClose={() => { if (!busy) onClose() }}
  >
    <div className="release-switch">
      <span>{policyLabel(current.version)}<small>Current now</small></span>
      <UiIcon name="arrow" />
      <span>{policyLabel(version.version)}<small>Current after confirmation</small></span>
    </div>
    <p>Open requests that are ready for review will be evaluated again. Recorded decisions and payments stay
      unchanged. Eligible Auto Approve requests will process automatically within the payment limits of this
      version.</p>
    {
      (localError || error) && <div className="alert error">{localError || (error as Error).message}</div>
    }
    {
      kind === 'activate' && report &&
      <>
        <Badge tone={ready ? 'green' : 'amber'}>
          {ready ? 'Release checks passed' : 'More evidence required'}
        </Badge>
        <ul>{report.gate.blockers.map((b: string) => <li key={b}>{b}</li>)}</ul>
        <div className="release-limits">
          <div>Per payment<strong>{money(report.experiment.settings.max_single_cents)}</strong></div>
          <div>Release budget<strong>{money(report.experiment.settings.release_cents)}</strong></div>
          <div>Daily budget<strong>{money(report.experiment.settings.daily_cents)}</strong></div>
        </div>
        <p className="small muted">Other Shadow versions will need fresh checks against this new Current.</p>
      </>
    }
    {
      kind === 'rollback' && !preview &&
      <button
        disabled={preparing || !!busy}
        onClick={async () => { setPreparing(true); await prepare(); setPreparing(false) }}
      >
        {preparing ? 'Preparing preview…' : 'Preview rollback impact'}
      </button>
    }
    {
      preview &&
      <>
        <div className="release-limits">
          <div>Ready requests<strong>{preview.eligible}</strong></div>
          <div>Changed routing<strong>{preview.changes.length}</strong></div>
          <div>Excluded<strong>{preview.excluded}</strong></div>
        </div>
        {preview.warnings?.map((w: string) => <p className="small" key={w}>{w}</p>)}
        {
          !!preview.changes.length &&
          <details>
            <summary>Request changes ({preview.changes.length})</summary>
            <div className="table-scroll">
              <table>
                <thead><tr><th>Request</th><th>Before</th><th>After</th></tr></thead>
                <tbody>
                  {
                    preview.changes.map(r => <tr key={r.id}>
                      <td>{r.id}</td>
                      <td><PolicyResult evaluation={r.old} /></td>
                      <td><PolicyResult evaluation={r.new} /></td>
                    </tr>)
                  }
                </tbody>
              </table>
            </div>
          </details>
        }
        <p className="small muted">Previously spent budgets are preserved. The preview must still match the current workspace when you
          confirm.</p>
      </>
    }
    <label>Decision note<textarea
      aria-label="Release decision note"
      value={reason}
      onChange={e => setReason(e.target.value)}
      placeholder="Why should this version become Current?"
    />
    </label>
    <div className="modal-actions">
      <button disabled={!!busy} onClick={onClose}>Cancel</button>
      <button className="primary" disabled={!!busy || !ready || !reason.trim()} onClick={submit}>
        {busy ? 'Saving…' : kind === 'activate' ? 'Confirm activation' : 'Confirm rollback'}
      </button>
    </div>
  </Modal>;
}
