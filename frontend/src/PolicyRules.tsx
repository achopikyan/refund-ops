import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, ConditionEditor, RuleReasonBadge, Empty, words } from './components';
import type { Rule } from './components';
import { ActionTag, UiIcon, actionStyles, reasonStyles } from './visualLanguage';
import RuleConditions from './RuleConditions';
import type { ManagedVersion } from './policyManagement';
import { usePolicyAutosave } from './policyAutosave';
import AutosaveStatus from './AutosaveStatus';
import BadgeSelect from './BadgeSelect';
import AddRuleDialog from './AddRuleDialog';

export default function PolicyRules({ version, workspaceKey }: { version: ManagedVersion, workspaceKey: string }) {
  const autosave = usePolicyAutosave(version, workspaceKey), p = autosave.policy;
  const [adding, setAdding] = useState(false),
    [removed, setRemoved] = useState<{ rule: Rule, index: number } | null>(null);
  const { data: catalog = {} } = useQuery({ queryKey: ['catalog'], queryFn: () => api<Record<string, { label: string }>>('/field-catalog') });
  const { data: reasons = {} } = useQuery({ queryKey: ['rule-reasons'], queryFn: () => api<Record<string, string>>('/rule-reasons') });
  const conditionCatalog = {
    ...catalog,
    ...Object.fromEntries(p.criteria.map(c => ['facts.semantic.' + c.id, { label: c.question }]))
  };
  const fields = Object.keys(conditionCatalog);
  const edit = (id: string, patch: Partial<Rule>) => autosave.change({ ...p, rules: p.rules.map(r => r.id === id ? { ...r, ...patch } : r) });
  const remove = (rule: Rule) => {
    setRemoved({ rule, index: p.rules.indexOf(rule) });
    autosave.change({ ...p, rules: p.rules.filter(r => r.id !== rule.id) })
  };
  return <section className="panel inline-rules">
    <header className="inline-rules-heading">
      <div>
        <h2>Rules <span>{p.rules.length}</span></h2>
        <p>All enabled rules are evaluated. Higher priority resolves competing matches; policy-wide checks still
          apply.</p>
      </div>
      <div className="inline-rule-tools">
        <AutosaveStatus state={autosave} />
        {
          !autosave.locked &&
          <button className="primary" onClick={() => setAdding(true)}><UiIcon name="plus" />Add rule</button>
        }
      </div>
    </header>
    {
      removed && !p.rules.some(r => r.id === removed.rule.id) && !autosave.locked &&
      <div className="rule-removed-status" role="status">
        <span>Rule removed</span>
        <button
          onClick={
            () => {
              const rules = [...p.rules];
              rules.splice(Math.min(removed.index, rules.length), 0, removed.rule);
              autosave.change({ ...p, rules });
              setRemoved(null)
            }
          }
        >Undo</button>
      </div>
    }
    {
      p.rules.length ?
        <div className="inline-rule-table">
          <div className="inline-rule-columns">
            <span>Rule</span>
            <span>Conditions</span>
            <span>Reason</span>
            <span>Route</span>
            <span className="enabled-column-heading">Enabled</span>
            <span aria-hidden="true" />
          </div>
          {
            p.rules.map(rule => <article
              className={'inline-rule ' + (autosave.locked ? 'is-readonly ' : '') + (!rule.enabled ? 'is-disabled' : '')}
              key={rule.id}
              aria-label={'Rule ' + rule.name}
            >
              <div className="inline-rule-identity">
                {
                  autosave.locked ?
                    <><h3>{words(rule.name)}</h3><small>Priority {rule.priority}</small></> :
                    <>
                      <label>
                        <span className="inline-column-label">Rule name</span>
                        <input value={rule.name} onChange={e => edit(rule.id, { name: e.target.value })} />
                      </label>
                      <div className="inline-rule-options">
                        <label>Priority<input
                          type="number"
                          min="0"
                          max="1000"
                          value={rule.priority}
                          onChange={e => edit(rule.id, { priority: Number(e.target.value) })}
                        />
                        </label>
                      </div>
                    </>
                }
              </div>
              <div className="inline-rule-conditions">
                {
                  autosave.locked ?
                    <RuleConditions compact rule={rule} catalog={conditionCatalog} /> :
                    <>
                      <label>
                        <span className="inline-column-label">Match conditions</span>
                        <select
                          aria-label="Match conditions"
                          value={rule.match}
                          onChange={e => edit(rule.id, { match: e.target.value as 'all' | 'any' })}
                        >
                          <option value="all">All conditions (AND)</option>
                          <option value="any">Any condition (OR)</option>
                        </select>
                      </label>
                      {
                        rule.conditions.map((condition, i) => <ConditionEditor
                          key={i}
                          condition={condition}
                          fields={fields}
                          update={value => edit(rule.id, { conditions: rule.conditions.map((c, j) => j === i ? value : c) })}
                          remove={() => edit(rule.id, { conditions: rule.conditions.filter((_, j) => j !== i) })}
                        />)
                      }
                      <button
                        className="text-button"
                        onClick={
                          () => edit(
                            rule.id,
                            { conditions: [...rule.conditions, { field: 'amount_cents', op: 'lte', value: 5000 }] }
                          )
                        }
                      >
                        <UiIcon name="plus" size={13} />Add condition</button>
                    </>
                }
              </div>
              <div className="inline-rule-reason">
                {
                  autosave.locked ?
                    <><RuleReasonBadge rule={rule} /></> :
                    <>
                      <BadgeSelect
                        hideLabel
                        label="Reason"
                        value={rule.reason_code && reasons[rule.reason_code] ? rule.reason_code : 'policy_rule'}
                        onChange={value => edit(rule.id, { reason_code: value })}
                        options={
                          Object.entries(reasons).map(([value, label]) => ({ value, label, ...(reasonStyles[value] || reasonStyles.policy_rule) }))
                        }
                      />
                    </>
                }
              </div>
              <div className="inline-rule-route">
                {
                  autosave.locked ?
                    <ActionTag action={rule.action} route /> :
                    <BadgeSelect
                      hideLabel
                      label="Route"
                      value={rule.action === 'auto_approve' || rule.action === 'fraud' ? rule.action : 'review'}
                      onChange={value => edit(rule.id, { action: value })}
                      options={['auto_approve', 'review', 'fraud'].map(value => ({ value, ...actionStyles[value] }))}
                    />
                }
              </div>
              <div className="inline-rule-enabled">
                <label className="lab-check">
                  <input
                    type="checkbox"
                    aria-label="Enabled"
                    checked={rule.enabled}
                    disabled={autosave.locked}
                    onChange={e => edit(rule.id, { enabled: e.target.checked })}
                  />
                  <span className="inline-column-label">Enabled</span>
                </label>
              </div>
              <div className="inline-rule-delete">
                {
                  !autosave.locked &&
                  <button
                    type="button"
                    className="icon-button remove-inline-rule"
                    aria-label={'Remove ' + rule.name}
                    title="Remove rule"
                    onClick={() => remove(rule)}
                  >
                    <UiIcon name="trash" size={18} />
                  </button>
                }
              </div>
            </article>)
          }
        </div> :
        <Empty title="No rules yet" detail="Use Add rule to create one manually or describe it with AI." />
    }
    {
      adding &&
      <AddRuleDialog
        policy={p}
        onClose={() => setAdding(false)}
        onAdd={rule => { autosave.change({ ...p, rules: [...p.rules, rule] }); setAdding(false) }}
      />
    }
  </section>;
}
