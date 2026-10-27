import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, money, words, Icon, ReasonBadge, Empty, PageHeading, Metric, RequestDrawer, SettingsPanel, ImportModal } from './components';
import type { Act, RequestRecord, PolicyRecord, Policy, Settings } from './components';
import PolicyJourney from './PolicyJourney';
import { ActionTag } from './visualLanguage';
import PolicyVersions from './PolicyVersions';
import VersionCompare from './VersionCompare';
import CurrentPerformance from './CurrentPerformance';
import PolicyRules from './PolicyRules';
import CostSettings from './CostSettings';
import { flushPolicyDraft } from './policyAutosave';
import ReviewDesk from './ReviewDesk';
import RuleCandidates from './RuleCandidates';
import PolicyVersionNav from './PolicyVersionNav';
import { usePolicyLibrary, editingLocked } from './policyManagement';
import { blankPolicy, scratchId } from './policyWorkingCopy';

type Setup = { history_count: number, draft_count: number };
export default function Workspace() {
  const [role, setRole] = useState(sessionStorage.getItem('refund-role') || ''),
    [page, setPage] = useState(''),
    [selected, setSelected] = useState<string | null>(null),
    [filter, setFilter] = useState('all'),
    [reason, setReason] = useState(''),
    [search, setSearch] = useState(''),
    [error, setError] = useState(''),
    [notice, setNotice] = useState(''),
    [busy, setBusy] = useState(''),
    [modal, setModal] = useState(false),
    [candidate, setCandidate] = useState<Policy | null>(null);
  const [reviewView, setReviewView] = useState(localStorage.getItem('refund-review-view') || 'list');
  const changeReviewView = (view: string) => { localStorage.setItem('refund-review-view', view); setReviewView(view); setSelected(null) };
  const [versionId, setVersionId] = useState<string | null>(null);
  const [candidateBaseId, setCandidateBaseId] = useState<string | null>(null),
    [journeyStage, setJourneyStage] = useState('backtest');
  const [candidateId, setCandidateId] = useState<string | null>(null),
    [trialId, setTrialId] = useState('');
  const qc = useQueryClient(),
    manager = role === 'manager',
    current = page || (manager ? 'policies' : 'requests');
  const { data: library } = usePolicyLibrary(manager);
  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: () => api<{ capabilities: string[], workspace_id: string, state?: Record<string, string>, ai: Settings }>('/health'),
    refetchInterval: 3000,
    enabled: !!role
  });
  const outdated = !!health && !health.capabilities.includes(manager ? 'automatic_rechecks' : 'request_sections');
  const { data: requests = [], error: loadError, isPending: requestsPending } = useQuery({
    queryKey: ['requests', role],
    queryFn: () => api<RequestRecord[]>('/requests'),
    enabled: !!role,
    refetchInterval: 3000
  });
  const { data: policies = [] } = useQuery({ queryKey: ['policies', role], queryFn: () => api<PolicyRecord[]>('/policies'), enabled: manager });
  const { data: settings } = useQuery({
    queryKey: ['settings', role],
    queryFn: () => api<Settings>('/settings/llm'),
    enabled: manager && current === 'settings',
    refetchInterval: 3000
  });
  const { data: setup } = useQuery({ queryKey: ['setup', role], queryFn: () => api<Setup>('/setup'), enabled: manager });
  const refresh = () => qc.invalidateQueries();
  const act: Act = async (label, fn, message) => {
    if (outdated) {
      setError('Open START.cmd again to update the running server, then refresh this page. Your existing data is preserved.');
      return null
    }
    setBusy(label);
    setError('');
    setNotice('');
    try { const result = await fn(); await refresh(); if (message) setNotice(message); return result } catch (e) { setError((e as Error).message); return null } finally { setBusy('') }
  };
  const navigate = (p: string) => { setPage(p); setSelected(null); setError(''); setNotice('') };
  const editVersion = async (p: PolicyRecord, _ruleId?: string, isNew = false) => {
    if (isNew) {
      const data = {
        ...p.data,
        name: 'Policy version',
        automation_enabled: true,
        execution_limits: p.data.execution_limits || p.execution_limits || blankPolicy().data.execution_limits
      };
      const saved = await act(
        'create-version',
        () => api<PolicyRecord>(
          p.id === scratchId ? '/policies/drafts?from_scratch=true' : '/policies/drafts?parent_id=' + p.id,
          data
        )
      );
      if (saved) { setVersionId((saved as PolicyRecord).id); navigate('rules') }
    }
    else { setVersionId(p.id); navigate('rules') }
  };
  const createScratch = () => { void editVersion(blankPolicy(), undefined, true) };
  const checkVersion = (p: PolicyRecord, stage = 'backtest') => {
    if (stage === 'shadow' && p.status === 'active') return;
    const version = library?.versions.find(v => v.id === p.id);
    setCandidate(version?.checks_id ? null : p.data);
    setCandidateId(p.id);
    setTrialId(version?.checks_id || '');
    setJourneyStage(stage);
    navigate('journey')
  };
  const findCandidates = (p: PolicyRecord) => {
    const managed = library?.versions.find(v => v.id === p.id);
    if (p.id === scratchId || managed && editingLocked(managed)) { setError('Save your new version first, then open Discovery in that version.'); return }
    setCandidateBaseId(p.id);
    navigate('candidates')
  };
  const allPolicies = () => { setVersionId(null); navigate('policies') };
  const choose = (r: string) => {
    sessionStorage.setItem('refund-role', r);
    qc.clear();
    setRole(r);
    setPage('');
    setSelected(null);
    setCandidate(null);
    setVersionId(null);
    setCandidateBaseId(null);
    setError('');
    setNotice('')
  };

  const active = policies.find(p => p.status === 'active');
  const contextId = current === 'journey' ?
    candidateId :
    current === 'candidates' ?
      candidateBaseId :
      ['policies', 'rules', 'performance'].includes(current) ? versionId : null;
  const contextVersion = library?.versions.find(v => v.id === contextId);
  const selectedRequest = requests.find(r => r.id === selected);
  const nav = manager ?
    [['policies', 'Policies', 'policy'], ['compare', 'Compare versions', 'split']] :
    [['requests', 'Requests', 'queue']];
  if (!role) return <div className="role-entry">
    <div className="eyebrow">REFUND OPERATIONS</div>
    <h1>Good decisions.<br />Clear responsibility.</h1>
    <p>Choose your workspace to begin.</p>
    <div className="role-cards">
      <button onClick={() => choose('reviewer')}>
        <Icon name="queue" size={30} />
        <h2>Reviewer</h2>
        <p>Resolve requests, check evidence<br />using evidence and the current policy.</p>
        <span>Open requests →</span>
      </button>
      <button onClick={() => choose('manager')}>
        <Icon name="policy" size={30} />
        <h2>Refund Operations Manager</h2>
        <p>Develop rules, measure risk<br />and decide when to release.</p>
        <span>Open policies →</span>
      </button>
    </div>
    <small>Local interview demo · declared roles, no authentication · payments are simulated</small>
  </div>;
  const base = requests.filter(r => (filter === 'all' || filter === 'open' && r.status !== 'resolved' ||
    filter === 'fraud' && r.queue === 'fraud' && r.status !== 'resolved' ||
    filter === 'waiting' && (r.status.startsWith('waiting') || r.status === 'on_hold') ||
    filter === 'completed' && r.status === 'resolved' ||
    filter === 'followup' && r.follow_up && !r.follow_up.closed) &&
    JSON.stringify([r.external_id, r.data.customer_id, r.data.stated_reason, r.data.customer_note, r.data.support_note]).toLowerCase().includes(search.toLowerCase()));
  const reasons = Array.from(new Set(base.map(r => r.evaluation.reason_label))).sort(),
    filtered = base.filter(r => !reason || r.evaluation.reason_label === reason);
  return <div className="shell">
    <aside className="sidebar">
      <button className="brand" onClick={() => navigate(manager ? 'policies' : 'requests')}>
        <span className="brand-mark">r↗</span>
        <span>refund<span className="brand-light">operations</span></span>
      </button>
      <div className="workspace-label">{manager ? 'REFUND OPERATIONS MANAGER' : 'REVIEWER'}</div>
      <nav>
        {
          nav.map(([id, label, icon]) => <button
            key={id}
            className={
              'nav-item ' + (current === id ||
                id === 'policies' && ['journey', 'candidates', 'rules', 'performance'].includes(current) ?
                'active' :
                '')
            }
            onClick={() => id === 'policies' ? allPolicies() : navigate(id)}
          >
            <Icon name={icon} />
            {label}
          </button>)
        }
      </nav>
      {
        !manager &&
        <div className="review-view-switch">
          <span>WORKSPACE VIEW</span>
          <button
            className={reviewView === 'list' ? 'selected' : ''}
            aria-pressed={reviewView === 'list'}
            onClick={() => { navigate('requests'); changeReviewView('list') }}
          >
            <Icon name="queue" />List view</button>
          <button
            className={reviewView === 'desk' ? 'selected' : ''}
            aria-pressed={reviewView === 'desk'}
            onClick={() => { navigate('requests'); changeReviewView('desk') }}
          >
            <Icon name="split" />Review view</button>
        </div>
      }
      <div className="sidebar-bottom">
        {
          manager &&
          <>
            <button className="nav-item" onClick={() => navigate('data')}><Icon name="upload" />Data</button>
            <button className="nav-item" onClick={() => navigate('settings')}>
              <Icon name="settings" />Settings</button>
          </>
        }
        <button className="profile" onClick={() => choose('')} title="Switch workspace">
          <span className="avatar">{manager ? 'RM' : 'AM'}</span>
          <div>{manager ? 'Refund Operations Manager' : 'Alex Morgan'}<small>Switch workspace ↗</small></div>
        </button>
      </div>
    </aside>
    <main aria-busy={requestsPending}>
      <header className="topbar">
        <span>
          {manager ? 'Refund Operations Manager' : 'Reviewer'} <span className="slash">/</span> {
            current === 'journey' ?
              'Policy version' :
              current === 'policies' ?
                'Policies' :
                current === 'candidates' ?
                  'Discovery' :
                  current === 'compare' ?
                    'Compare versions' :
                    current === 'performance' ? 'Performance' : words(current)
          }
        </span>
        <div className="topbar-simulation" title="Every decision is recorded. No real money moves.">
          <span>
            <span className="status-dot" />
            {health?.state?.demo_scenario ? 'Synthetic scenario' : 'Local simulation'}
          </span>
          <small>
            {
              health?.state?.demo_scenario ?
                'Separate demo workspace. No real money moves.' :
                'Every decision is recorded. No real money moves.'
            }
          </small>
        </div>
      </header>
      <div className="content">
        {
          outdated &&
          <div className="alert warning" role="alert">
            <Icon name="history" />
            <div>
              <strong>The running server needs an update</strong>
              <p>Open START.cmd again. It will replace the older server and open the current app. Existing policies and
                decisions are preserved.</p>
            </div>
          </div>
        }
        {
          (error || loadError) &&
          <div className="alert error" role="alert">
            {error || (loadError as Error)?.message}
            <button onClick={() => { setError(''); void refresh() }}>Retry</button>
          </div>
        }
        {
          notice &&
          <div className="alert success" role="status">
            {notice}
            <button onClick={() => setNotice('')}>×</button>
          </div>
        }
        {
          !manager && current === 'requests' && reviewView === 'desk' &&
          <>
            <PageHeading
              title="Review workspace"
              text="Move through your queue with the request and its evidence side by side."
            />
            <ReviewDesk requests={requests} selected={selected} onSelect={setSelected} act={act} busy={busy} />
          </>
        }
        {
          !manager && current === 'requests' && reviewView === 'list' &&
          <>
            <PageHeading
              title="Requests"
              text="Your requests, ready to review. Check the evidence and record your decision."
            />
            <div className="metric-grid">
              <Metric
                label="Open requests"
                value={String(requests.filter(r => r.status !== 'resolved').length)}
                detail="Across the review queues"
              />
              <Metric
                label="Ready for review"
                value={String(requests.filter(r => ['ready', 'in_review'].includes(r.status)).length)}
                detail="All visible requests are yours to review"
              />
              <Metric
                label="Waiting for a reply"
                value={String(requests.filter(r => r.status.startsWith('waiting')).length)}
                detail="Verify new facts before resuming"
              />
              <Metric
                label="Completed"
                value={String(requests.filter(r => r.status === 'resolved').length)}
                detail="Decision and payment recorded separately"
              />
            </div>
            <section className="panel">
              <div className="table-toolbar">
                <div className="tabs">
                  {
                    [
                      ['all', 'All'],
                      ['open', 'Open'],
                      ['fraud', 'Fraud Review'],
                      ['waiting', 'Waiting'],
                      ['completed', 'Completed'],
                      ['followup', 'Follow-up']
                    ].map(([id, label]) => <button
                      key={id}
                      className={filter === id ? 'selected' : ''}
                      onClick={() => { setFilter(id); setReason('') }}
                    >
                      {label}
                    </button>)
                  }
                </div>
              </div>
              <div className="queue-filters">
                <label className="search">
                  <Icon name="search" />
                  <input
                    aria-label="Search requests"
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    placeholder="Request or customer…"
                  />
                </label>
                <label>Routing reason<select aria-label="Routing reason" value={reason} onChange={e => setReason(e.target.value)}>
                  <option value="">All reasons ({base.length})</option>
                  {
                    reasons.map(x => <option key={x} value={x}>{x} ({base.filter(r => r.evaluation.reason_label === x).length})</option>)
                  }
                </select>
                </label>
              </div>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Request / customer</th>
                      <th>Customer reason</th>
                      <th>Amount</th>
                      <th>Route</th>
                      <th>Reason</th>
                      <th>Work state</th>
                    </tr>
                  </thead>
                  <tbody>
                    {
                      filtered.map(r => <tr
                        key={r.id}
                        tabIndex={0}
                        aria-label={'Open ' + r.external_id}
                        onClick={() => setSelected(r.id)}
                        onKeyDown={e => { if (e.key === 'Enter') setSelected(r.id) }}
                      >
                        <td><strong>{r.external_id}</strong><small>{r.data.customer_id}</small></td>
                        <td>{words(r.data.stated_reason)}</td>
                        <td className="amount">{money(r.data.amount_cents)}</td>
                        <td>
                          <ActionTag
                            action={
                              r.evaluation.route === 'auto_approve' ?
                                'auto_approve' :
                                r.evaluation.route === 'fraud_reviewer' ? 'fraud' : 'review'
                            }
                            route
                          />
                        </td>
                        <td className="reason-cell">
                          <ReasonBadge
                            code={r.evaluation.reason_code}
                            label={r.evaluation.reason_label || words(r.evaluation.reason_code)}
                            explanation={r.evaluation.explanation}
                          />
                        </td>
                        <td>
                          {
                            r.ledger ?
                              'Paid · simulated' :
                              r.decision ?
                                words(r.decision.action) :
                                r.execution_state === 'would_approve' ?
                                  'Would approve' :
                                  r.execution_state === 'ready_to_execute' ?
                                    'Ready to execute' :
                                    r.status === 'ready' ? 'Awaiting review' : words(r.status)
                          }
                          {r.follow_up && !r.follow_up.closed && <small>Follow-up review</small>}
                        </td>
                      </tr>)
                    }
                  </tbody>
                </table>
              </div>
              {
                !filtered.length &&
                <Empty title="No requests in this view" detail="Choose another state or routing reason." />
              }
              <footer className="table-footer">
                {filtered.length} requests · USD · route is a recommendation, not a payment</footer>
            </section>
          </>
        }
        {
          manager && contextVersion &&
          <PolicyVersionNav
            baseVersion={library?.versions.find(v => v.id === contextVersion?.parent_id)}
            onBack={allPolicies}
            version={contextVersion}
            active={
              current === 'rules' ?
                'rules' :
                current === 'journey' ?
                  (journeyStage === 'rollout' ? 'shadow' : journeyStage) :
                  current === 'candidates' ? 'candidates' : current === 'performance' ? 'performance' : 'settings'
            }
            onChange={
              async view => {
                if (!contextVersion) return;
                let target = contextVersion;
                if (['backtest', 'shadow', 'candidates'].includes(view)) {
                  const saved = await flushPolicyDraft(health?.workspace_id || 'local', contextVersion);
                  if (!saved) { setError('Complete or correct the unsaved fields before starting checks or discovery.'); return }
                  target = { ...contextVersion, data: saved };
                  await refresh();
                }
                if (view === 'settings') { setVersionId(contextVersion.id); navigate('policies') } else if (view === 'rules') { setVersionId(contextVersion.id); navigate('rules') } else if (view === 'performance') { setVersionId(contextVersion.id); navigate('performance') } else if (view === 'candidates') findCandidates(target); else checkVersion(target, view)
              }
            }
          />
        }
        {
          manager && current === 'policies' &&
          <PolicyVersions
            workspaceKey={health?.workspace_id || 'local'}
            selectedId={versionId}
            onSelect={setVersionId}
            act={act}
            busy={busy}
            onCreate={(p, id) => editVersion(p, id, true)}
            onScratch={createScratch}
          />
        }
        {
          manager && current === 'rules' && contextVersion &&
          <PolicyRules
            key={contextVersion.id}
            version={contextVersion}
            workspaceKey={health?.workspace_id || 'local'}
          />
        }
        {
          manager && current === 'candidates' && health?.workspace_id &&
          <RuleCandidates
            policies={policies}
            baseId={candidateBaseId}
            workspaceKey={health.workspace_id}
            historyCount={setup?.history_count ?? 0}
            act={act}
            busy={busy}
            onEdit={(p, id) => editVersion(p, id)}
          />
        }
        {
          manager && current === 'compare' &&
          <VersionCompare initialId={null} onOpen={id => { setVersionId(id); navigate('policies') }} />
        }
        {
          manager && current === 'journey' && active &&
          <>
            <PolicyJourney
              onBack={allPolicies}
              key={candidateId || trialId}
              draftId={candidateId}
              initialTrialId={trialId}
              activePolicy={active.data}
              draft={candidate}
              act={act}
              busy={busy}
              stage={journeyStage}
              setStage={stage => { if (candidateId === active.id && stage !== 'backtest') return; setJourneyStage(stage) }}
            />
          </>
        }
        {
          manager && current === 'performance' && contextVersion &&
          <CurrentPerformance
            key={contextVersion.id}
            policyId={contextVersion.id}
            onPolicy={id => { setVersionId(id); navigate('policies') }}
          />
        }
        {
          manager && current === 'settings' && settings &&
          <><SettingsPanel settings={settings} act={act} busy={busy} /><CostSettings /></>
        }
        {
          manager && current === 'data' &&
          <>
            <PageHeading
              title="Data"
              text="Import records deliberately. Existing decisions and active policies are preserved."
            />
            <section className="panel padded">
              <h2>Historical and incoming requests</h2>
              <p>History: {setup?.history_count ?? 0} unique requests. Operational queue: {requests.length} requests.</p>
              <button className="primary" onClick={() => setModal(true)}>Import CSV</button>
              <p className="small muted">Imports preview duplicates, conflicting versions and invalid fields before changing the workspace.</p>
            </section>
          </>
        }
      </div>
    </main>
    {
      selectedRequest && !manager && reviewView === 'list' &&
      <RequestDrawer
        key={selectedRequest.id}
        request={selectedRequest}
        onClose={() => setSelected(null)}
        act={act}
        busy={busy}
      />
    } {modal && manager && <ImportModal onClose={() => setModal(false)} act={act} />}
  </div>
}
