import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, Empty, RuleReasonBadge, money, words } from './components';
import type { Act, PolicyRecord } from './components';
import { UiIcon, ActionTag } from './visualLanguage';
import { conditionText } from './policyConditions';
import RuleConditions from './RuleConditions';
import { policyLabel } from './policyIdentity';
import { discoveryKey, readDiscovery, readWorkingCopy, workingCopyKey, includedCandidates } from './policyWorkingCopy';
import type { Discovery } from './policyWorkingCopy';

type Props = {
  policies: PolicyRecord[],
  baseId: string | null,
  workspaceKey: string,
  historyCount: number,
  act: Act,
  busy: string,
  onEdit: (p: PolicyRecord, ruleId?: string) => void
};
export default function RuleCandidates(props: Props) {
  const base = props.policies.find(p => p.id === props.baseId) || props.policies.find(p => p.status === 'active');
  return <>

    {base && <DiscoveryWorkspace key={base.id} {...props} base={base} />}
  </>;
}
function DiscoveryWorkspace({ base, workspaceKey, historyCount, act, busy, onEdit }: Props & { base: PolicyRecord }) {
  const [report, setReport] = useState(() => readDiscovery(workspaceKey, base)),
    [work, setWork] = useState(() => readWorkingCopy(workspaceKey, base));
  const [selection, setSelection] = useState<string[]>([]),
    [filter, setFilter] = useState('available'),
    [search, setSearch] = useState(''),
    [message, setMessage] = useState(''),
    [error, setError] = useState('');
  const [generating, setGenerating] = useState(false);
  const [limit, setLimit] = useState(12);
  useEffect(() => setLimit(12), [filter, search, report?.id]);
  const [hourly, setHourly] = useState(30),
    [loss, setLoss] = useState(5),
    [support, setSupport] = useState(5);
  const { data: latest } = useQuery({ queryKey: ['discovery'], queryFn: () => api<Discovery | null>('/rule-discovery') });
  const { data: catalog = {} } = useQuery({ queryKey: ['catalog'], queryFn: () => api<Record<string, { label: string }>>('/field-catalog') });
  useEffect(
    () => {
      if (!report && !generating && latest?.base_id === base.id &&
        (!base.hash || latest.base_hash === base.hash)) {
        setReport(latest);
        try { localStorage.setItem(discoveryKey(workspaceKey, base.id), JSON.stringify(latest)) } catch { }
      }
    },
    [latest?.id, generating]
  );
  const candidates = report?.candidates || [], included = new Set(work.policy.rules.map(r => r.id));
  const pending = selection.filter(id => candidates.some(c => c.id === id && !included.has(c.rule.id)));
  const pinned = includedCandidates(work).length > 0;
  const visible = candidates.filter(c => (filter === 'all' || (filter === 'included') === included.has(c.rule.id)) &&
    (c.rule.name + ' ' + c.rule.conditions.map(x => conditionText(x, catalog)).join(' ')).toLowerCase().includes(search.toLowerCase()));
  const generate = async () => {
    setError('');
    setMessage('');
    setGenerating(true);
    const result = await act(
      'discover',
      () => api<Discovery>(
        '/rule-discovery',
        {
          base_id: base.id,
          hourly_cents: Math.round(hourly * 100),
          adverse_bps: Math.round(loss * 100),
          min_support: support
        }
      )
    );
    if (result) {
      const next = result as Discovery;
      setReport(next);
      setSelection([]);
      try { localStorage.setItem(discoveryKey(workspaceKey, base.id), JSON.stringify(next)) } catch {
        setError('Browser storage is unavailable. Keep this page open until you add your selected rules.')
      }
    }
    setGenerating(false);
  };
  const add = async () => {
    if (!report) return;
    setError('');
    const fresh = { policy: structuredClone(base.data), basePolicy: base.data, discovery: null };
    const rules = [...fresh.policy.rules],
      added = candidates.filter(c => pending.includes(c.id) && !rules.some(r => r.id === c.rule.id));
    for (const c of added) {
      const priority = Math.max(0, Math.min(...rules.filter(r => r.enabled).map(r => r.priority), 1000) - 1);
      rules.push({ ...structuredClone(c.rule), priority })
    }
    const next = { ...fresh, policy: { ...fresh.policy, rules }, discovery: report };
    const saved = await act(
      'add-candidates',
      () => api<PolicyRecord>(
        '/rule-discovery/' + report.id + '/draft',
        {
          candidate_ids: added.map(c => c.id),
          policy: next.policy,
          target_id: base.id,
          expected_policy: base.data
        }
      )
    );
    if (saved) {
      const record = saved as PolicyRecord;
      try { localStorage.removeItem(workingCopyKey(workspaceKey, base.id)) } catch { }
      setWork({ policy: record.data, basePolicy: record.data, discovery: null });
      setSelection([]);
      setMessage(`${added.length} rules added to ${policyLabel(base.version)} and saved. You can adjust them directly in Rules.`)
    }

  };
  return <>
    <section className="manager-section manager-blue">
      <div className="section-line">
        <div>
          <h2>Discover from history</h2>
          <p>{historyCount} historical requests · suggestions for {policyLabel(base.version)}</p>
          <p className="small muted">Rules already covered by this version are excluded. Selected candidates are saved to this version and
            can be adjusted directly in Rules.</p>
        </div>
        <button
          className="primary"
          disabled={!!busy || generating || !historyCount || pinned}
          onClick={generate}
        >
          <UiIcon name="spark" />
          {busy === 'discover' ? 'Generating…' : report ? 'Generate fresh candidates' : 'Generate candidates'}
        </button>
      </div>
      <div className="discovery-search-settings">
        <h3>Search scope and financial assumptions</h3>
        <p>Search combinations of customer reason, amount, tenure and past refunds. These are rule hypotheses,
          not confirmed safe automation.</p>
        <div className="form-grid">
          <label>Reviewer cost · USD/hour<input
            type="number"
            min="0"
            max="10000"
            value={hourly}
            onChange={e => setHourly(Number(e.target.value))}
          />
          </label>
          <label>Hypothetical loss · %<input
            type="number"
            min="0"
            max="100"
            value={loss}
            onChange={e => setLoss(Number(e.target.value))}
          />
          </label>
          <label>Minimum matching cases<input
            type="number"
            min="2"
            max="1000"
            value={support}
            onChange={e => setSupport(Number(e.target.value))}
          />
          </label>
        </div>
      </div>
      {
        pinned &&
        <p className="small muted">Unsaved candidate changes are kept in this browser. Open Rules to finish them before generating a fresh
          search.</p>
      }
    </section>
    {error && <div className="alert error" role="alert">{error}</div>}
    {
      message &&
      <div className="candidate-added" role="status">
        <UiIcon name="check" />
        <div><strong>Added to this version</strong><p>{message}</p></div>
        <button className="primary" onClick={() => onEdit(base)}>Open Rules<UiIcon name="arrow" /></button>
      </div>
    }
    {
      report ?
        <>
          <section className="panel candidate-library">
            <div className="padded">
              <div className="section-line">
                <div>
                  <h2>{candidates.length} candidate rules</h2>
                  <p>
                    {report.training_count} discovery records · {report.later_count} later diagnostic records · {report.excluded_existing} already covered</p>
                </div>
                <button onClick={() => onEdit(base)}><UiIcon name="edit" />Open Rules</button>
              </div>
              <div className="composer-candidate-tools">
                <div className="candidate-scope" role="group" aria-label="Candidate status">
                  {
                    [['available', 'Available'], ['included', 'In this version'], ['all', 'All candidates']].map(([id, label]) => <button
                      key={id}
                      className={filter === id ? 'selected' : ''}
                      aria-pressed={filter === id}
                      onClick={() => setFilter(id)}
                    >
                      {label}
                    </button>)
                  }
                </div>
                <input
                  aria-label="Search candidate rules"
                  placeholder="Search candidates"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                />
              </div>
            </div>
            <div className="candidate-library-grid">
              {
                visible.slice(0, limit).map(c => {
                  const added = included.has(c.rule.id), picked = pending.includes(c.id);
                  return <article
                    className={'composer-candidate ' + (added ? 'included' : picked ? 'is-picked' : '')}
                    key={c.id}
                    data-candidate-id={c.id}
                  >
                    <div className="candidate-mainline">
                      <div><h3>{words(c.rule.name)}</h3><ActionTag action={c.rule.action} route /></div>
                      <label className="candidate-select">
                        <input
                          type="checkbox"
                          aria-label={'Select candidate ' + c.id}
                          checked={added || pending.includes(c.id)}
                          disabled={added || generating}
                          onChange={
                            e => {
                              const checked = e.currentTarget.checked;
                              setSelection(ids => checked ? [...ids, c.id] : ids.filter(id => id !== c.id))
                            }
                          }
                        />
                        {added ? 'In this version' : picked ? 'Selected' : 'Select'}
                      </label>
                    </div>
                    <RuleConditions rule={c.rule} catalog={catalog} />
                    <RuleReasonBadge rule={c.rule} />
                    <div className="candidate-quick-stats">
                      <span><strong>{c.training.support}</strong> matching cases</span>
                      <span><strong>{c.training.historical_manual}</strong> manual reviews</span>
                      <span><strong>{money(c.training.manual_requested_cents)}</strong> requested exposure</span>
                      <span><strong>{c.training.unknown_outcomes}</strong> unknown outcomes</span>
                    </div>
                    <details>
                      <summary>Historical evidence and financial scenario</summary>
                      <p>Later matching cases: {c.later_diagnostic.support}. Known chargebacks in discovery data: {c.training.known_chargebacks}.</p>
                      <p>Labor opportunity {money(c.training.labor_opportunity_cents)} at {money(report.assumptions.hourly_cost_cents)}/hour. Hypothetical loss {money(c.training.loss_scenario_cents)} at {report.assumptions.hypothetical_error_bps / 100}%. Scenario net {money(c.scenario_net_cents)}.</p>
                      <p>This is a scenario, not a predicted loss rate or proven savings.</p>
                      <p>Supporting requests: {c.support_ids.join(', ')}</p>
                    </details>
                    {
                      added &&
                      <button className="text-button" onClick={() => onEdit(base, c.rule.id)}>Edit included rule<UiIcon name="arrow" />
                      </button>
                    }
                  </article>
                })
              }
            </div>
            {
              visible.length > 0 &&
              <div className="candidate-more">
                <span>Showing {Math.min(limit, visible.length)} of {visible.length} candidates</span>
                {
                  limit < visible.length &&
                  <button onClick={() => setLimit(n => n + 12)}>Show more candidates</button>
                }
              </div>
            }
            {
              !visible.length &&
              <Empty
                title="No candidates in this view"
                detail="Change the filter or search. Existing rules can be edited in Rules."
              />
            }
          </section>
          <details className="manager-section manager-slate">
            <summary>Evidence limitations</summary>
            {report.limitations.map(note => <p className="small muted" key={note}>{note}</p>)}
          </details>
          <footer className={'candidate-selection-bar ' + (pending.length ? 'has-selection' : '')}>
            <div>
              <strong>{pending.length} selected</strong>
              <small>Destination: {policyLabel(base.version)} · Draft</small>
            </div>
            <button className="primary" disabled={!pending.length || !!busy} onClick={add}>
              <UiIcon name="arrow" />Add selected to version</button>
          </footer>
        </> :
        <Empty
          title="Generate new rule candidates"
          detail="The system will search historical requests for rules missing from the selected policy. Review the evidence, select candidates and add them to this version."
        />
    }
  </>;
}
