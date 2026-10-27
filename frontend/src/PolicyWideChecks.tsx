import { useQuery } from '@tanstack/react-query';
import { api, money } from './components';
import type { Policy, ExecutionLimits } from './components';
import type { ManagedVersion } from './policyManagement';
import { usePolicyAutosave } from './policyAutosave';
import AutosaveStatus from './AutosaveStatus';
import { UiIcon } from './visualLanguage';
import { defaultExecutionLimits, executionFields, dataChecks, businessChecks, approvalChecks } from './policyChecksConfig';
import type { FixedCheck } from './policyChecksConfig';

function FixedRows({ checks, values = {}, change }: {
  checks: FixedCheck[],
  values?: Record<string, boolean>,
  change?: (key: string, value: boolean) => void
}) {
  return <div className="wide-check-rows">
    {
      checks.map(([title, condition, outcome, key]) => <div className="wide-check-row" key={title}>
        <div>
          <strong>{title}</strong>
          {
            key &&
            <label className="policy-check-toggle">
              <input
                aria-label={title + ' enabled'}
                type="checkbox"
                checked={values[key] !== false}
                disabled={!change}
                onChange={e => change?.(key, e.target.checked)}
              />
              {values[key] === false ? 'Disabled' : 'Enabled'}
            </label>
          }
        </div>
        <p>{condition}</p>
        <span className="wide-check-outcome"><UiIcon name="arrow" size={14} />{outcome}</span>
      </div>)
    }
  </div>;
}

export default function PolicyWideChecks({ version: v, workspaceKey }: { version: ManagedVersion, workspaceKey: string }) {
  const { data: standard = [] } = useQuery({
    queryKey: ['evidence-questions'],
    queryFn: () => api<{ id: string, question: string, confirmation_source: string | null, values: string[] }[]>('/evidence-questions')
  });
  const autosave = usePolicyAutosave(v, workspaceKey),
    locked = autosave.locked,
    editing = !locked,
    p = autosave.policy;
  const limits = p.execution_limits || v.execution_limits || defaultExecutionLimits;
  const change = (patch: Partial<Policy>) => autosave.change({ ...p, ...patch });
  const changeCheck = (key: string, value: boolean) => change({ checks: { ...p.checks, [key]: value } });
  const toggle = (key: string, label: string) => <label className="policy-check-toggle">
    <input
      aria-label={label + ' enabled'}
      type="checkbox"
      checked={p.checks?.[key] !== false}
      disabled={!editing}
      onChange={e => changeCheck(key, e.target.checked)}
    />
    {p.checks?.[key] === false ? 'Disabled' : 'Enabled'}
  </label>;
  const changeLimit = (key: keyof ExecutionLimits, value: string) => change({
    execution_limits: { ...limits, [key]: key === 'release_count' ? Number(value) : Math.round(Number(value) * 100) }
  });
  return <div className="policy-wide-checks" role="region" aria-label="Policy-wide checks">
    {!locked && <div className="policy-checks-status"><AutosaveStatus state={autosave} /></div>}
    <details className="panel wide-check-group checks-blue" open>
      <summary>
        <UiIcon name="shield" />Data and payment safety<span>{dataChecks.length} checks</span>
      </summary>
      <FixedRows checks={dataChecks} values={p.checks} change={editing ? changeCheck : undefined} />
    </details>
    <details className="panel wide-check-group checks-amber" open>
      <summary><UiIcon name="file" />Business conditions<span>Version settings</span></summary>
      <div className="wide-check-rows">
        <div className="wide-check-row">
          <div>
            <strong>Change-of-mind window</strong>
            {toggle('change_mind_window', 'Change-of-mind window')}
          </div>
          <div>
            {
              editing ?
                <label>Return window (days)<input
                  type="number"
                  min="0"
                  max="365"
                  value={p.change_mind_days ?? 14}
                  onChange={e => change({ change_mind_days: Number(e.target.value) })}
                />
                </label> :
                <p>Delivery interval is unknown or exceeds <strong>{p.change_mind_days ?? 14} days</strong> for a changed-mind return</p>
            }
          </div>
          <span className="wide-check-outcome"><UiIcon name="arrow" size={14} />Review</span>
        </div>
        <div className="wide-check-row">
          <div>
            <strong>Damage photo requirement</strong>
            {toggle('damage_photo', 'Damage photo requirement')}
          </div>
          <div>
            {
              editing ?
                <label>Photo required above (USD)<input
                  type="number"
                  min="0"
                  step=".01"
                  value={(p.damage_photo_above_cents ?? 5000) / 100}
                  onChange={e => change({ damage_photo_above_cents: Math.round(Number(e.target.value) * 100) })}
                />
                </label> :
                <p>Damage claim exceeds <strong>{money(p.damage_photo_above_cents ?? 5000)}</strong> without a confirmed photo</p>
            }
          </div>
          <span className="wide-check-outcome"><UiIcon name="arrow" size={14} />Review · request photo</span>
        </div>
      </div>
      <FixedRows checks={businessChecks} values={p.checks} change={editing ? changeCheck : undefined} />
    </details>
    <details className="panel wide-check-group checks-green" open>
      <summary>
        <UiIcon name="check" />Rule resolution and approval<span>{approvalChecks.length} checks</span>
      </summary>
      <FixedRows checks={approvalChecks} values={p.checks} change={editing ? changeCheck : undefined} />
    </details>
    <details className="panel wide-check-group checks-amber" open>
      <summary><UiIcon name="money" />Execution limits<span>5 configurable limits</span></summary>
      <p className="wide-check-note">Automatic payments only. Exceeding a limit blocks that payment. Other eligible requests continue within
        their limits. Recorded spending survives rollback.</p>
      <div className="wide-check-rows">
        {
          executionFields.map(([key, label, condition]) => <div className="wide-check-row" key={key}>
            <div><strong>{label}</strong></div>
            <p>{condition}</p>
            <div className="wide-check-limit">
              {
                editing ?
                  <label>
                    {label}
                    {key === 'release_count' ? '' : ' (USD)'}
                    <input
                      type="number"
                      min={key === 'release_count' ? 1 : .01}
                      max={key === 'release_count' ? 1000000 : 10000000}
                      step={key === 'release_count' ? 1 : .01}
                      value={key === 'release_count' ? limits[key] : limits[key] / 100}
                      onChange={e => changeLimit(key, e.target.value)}
                    />
                  </label> :
                  <strong>{key === 'release_count' ? limits[key] + ' operations' : money(limits[key])}</strong>
              }
            </div>
          </div>)
        }
      </div>
    </details>
    <details className="panel wide-check-group checks-purple" open>
      <summary>
        <UiIcon name="spark" />Evidence questions<span>{standard.length} standard · {p.criteria.length} additional</span>
      </summary>
      <p className="wide-check-note">Questions produce facts for rules; they do not decide refunds. Changes trigger automatic analysis on
        the request pool.</p>
      <div className="standard-evidence-questions">
        <h3>Standard questions</h3>
        <p className="wide-check-note">Extracted from customer and support notes with the request fields as context. Facts require a verified
          source quote; missing evidence stays unknown.</p>
        <div className="wide-check-rows">
          {
            standard.map(q => <div className="wide-check-row standard-question" key={q.id}>
              <div><strong>{q.question}</strong></div>
              <p>
                {
                  q.confirmation_source ?
                    'A positive confirmation must come from the support note.' :
                    'Customer note or support note.'
                }
              </p>
              <div className="standard-fact">
                <code>{q.id}</code>
                <small>
                  {
                    q.id === 'location' ?
                      'Named location' :
                      q.id === 'effective_reason' ? 'Supported refund reason' : 'Yes / No / Unknown'
                  }
                </small>
              </div>
            </div>)
          }
        </div>
      </div>
      <h3 className="additional-questions-title">Additional policy questions</h3>
      {
        !p.criteria.length &&
        <p className="wide-check-note">No additional questions. Standard evidence analysis still runs automatically.</p>
      }
      {
        p.criteria.map((c, i) => <div className="wide-criterion" key={i}>
          <div className="section-line"><strong>{editing ? 'Question ' + (i + 1) : c.question}</strong></div>
          {
            editing ?
              <>
                <div className="form-grid">
                  <label>Criterion ID<input
                    value={c.id}
                    onChange={e => change({ criteria: p.criteria.map((x, j) => j === i ? { ...x, id: e.target.value } : x) })}
                  />
                  </label>
                  <label>Question<textarea
                    value={c.question}
                    onChange={
                      e => change({ criteria: p.criteria.map((x, j) => j === i ? { ...x, question: e.target.value } : x) })
                    }
                  />
                  </label>
                </div>
                <div className="button-row">
                  {
                    ['customer_note', 'support_note'].map(source => <label className="lab-check" key={source}>
                      <input
                        type="checkbox"
                        checked={c.sources.includes(source)}
                        onChange={
                          e => change({
                            criteria: p.criteria.map((x, j) => j === i ?
                              { ...x, sources: e.target.checked ? [...x.sources, source] : x.sources.filter(s => s !== source) } :
                              x)
                          })
                        }
                      />
                      {source === 'customer_note' ? 'Customer note' : 'Support note'}
                    </label>)
                  }
                  <button onClick={() => change({ criteria: p.criteria.filter((_, j) => j !== i) })}>Remove question</button>
                </div>
              </> :
              <p>
                {c.id} · {c.sources.map(s => s === 'customer_note' ? 'Customer note' : 'Support note').join(', ')}
              </p>
          }
        </div>)
      }
      {
        editing &&
        <button
          className="wide-add-question"
          onClick={
            () => {
              let n = p.criteria.length + 1;
              while (p.criteria.some(c => c.id === 'criterion_' + n)) n++;
              change({
                criteria: [...p.criteria, { id: 'criterion_' + n, question: '', sources: ['customer_note', 'support_note'] }]
              })
            }
          }
        >
          <UiIcon name="plus" />Add question</button>
      }
    </details>
  </div>;
}
