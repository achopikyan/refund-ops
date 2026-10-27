import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, Modal, RuleReasonBadge, words } from './components';
import type { Policy, Rule } from './components';
import { ActionTag, UiIcon } from './visualLanguage';
import RuleConditions from './RuleConditions';

type Proposal = { rule: Rule | null, issues: string[] };
export default function AddRuleDialog({ policy, onAdd, onClose }: { policy: Policy, onAdd: (rule: Rule) => void, onClose: () => void }) {
  const [mode, setMode] = useState('manual'),
    [description, setDescription] = useState(''),
    [proposal, setProposal] = useState<Proposal | null>(null),
    [pending, setPending] = useState(false),
    [error, setError] = useState('');
  const { data: catalog = {} } = useQuery({ queryKey: ['catalog'], queryFn: () => api<Record<string, { label: string }>>('/field-catalog') });
  const manual = () => onAdd({
    id: 'rule-' + crypto.randomUUID(),
    name: 'New rule',
    priority: Math.max(0, Math.min(...policy.rules.map(r => r.priority), 1000) - 1),
    conditions: [{ field: 'amount_cents', op: 'gt', value: 30000 }],
    match: 'all',
    action: 'review',
    reason_code: 'policy_rule',
    reason: '',
    enabled: true
  });
  const generate = async () => {
    setPending(true);
    setError('');
    setProposal(null);
    try { setProposal(await api<Proposal>('/policies/propose-rule', { instruction: description, policy })) } catch (e) { setError((e as Error).message) } finally { setPending(false) }
  };
  return <Modal title="Add rule" onClose={() => { if (!pending) onClose() }}>
    <p>Choose how to create a rule for this version.</p>
    <div className="policy-create-options" role="group" aria-label="Rule creation method">
      <button
        disabled={pending}
        className={mode === 'manual' ? 'selected' : ''}
        aria-pressed={mode === 'manual'}
        onClick={() => setMode('manual')}
      >
        <UiIcon name="edit" size={23} />
        <strong>Build manually</strong>
        <span>Create a rule, then change its fields directly in the list.</span>
      </button>
      <button
        disabled={pending}
        className={mode === 'ai' ? 'selected' : ''}
        aria-pressed={mode === 'ai'}
        onClick={() => setMode('ai')}
      >
        <UiIcon name="spark" size={23} />
        <strong>Describe with AI</strong>
        <span>Describe your intent and review a proposed rule before adding it.</span>
      </button>
    </div>
    {
      mode === 'ai' &&
      <>
        <label>Describe your rule<textarea
          rows={4}
          maxLength={4000}
          disabled={pending}
          value={description}
          placeholder="Send requests above $300 to Review because they need a high-value check."
          onChange={e => { setDescription(e.target.value); setProposal(null); setError('') }}
        />
        </label>
        <p className="small muted">Include when the rule applies and the desired route. The AI only receives this description and the rule
          configuration.</p>
        <button disabled={pending || !description.trim()} onClick={generate}>
          <UiIcon name="spark" />
          {pending ? 'Preparing rule…' : proposal ? 'Generate again' : 'Generate rule'}
        </button>
        {error && <p className="alert error" role="alert">{error}</p>}
        {
          !!proposal?.issues.length &&
          <div className="alert error" role="alert">
            <strong>This proposal needs correction</strong>
            <ul>{proposal.issues.map(issue => <li key={issue}>{issue}</li>)}</ul>
            <p>Update the description or use Build manually.</p>
          </div>
        }
        {
          proposal?.rule &&
          <section className="rule-ai-preview" aria-label="Proposed rule">
            <header>
              <UiIcon name="branch" />
              <h3>{words(proposal.rule.name)}</h3>
              <small>Priority {proposal.rule.priority}</small>
            </header>
            <RuleConditions rule={proposal.rule} catalog={catalog} />
            <div><h4>Because</h4><RuleReasonBadge rule={proposal.rule} /></div>
            <div><h4>Route</h4><ActionTag action={proposal.rule.action} route /></div>
            <p className="small muted">Review this proposal. After adding it, you can adjust its fields directly in Rules.</p>
          </section>
        }
      </>
    }
    <div className="modal-actions">
      <button disabled={pending} onClick={onClose}>Cancel</button>
      {
        mode === 'manual' ?
          <button className="primary" onClick={manual}>Add rule<UiIcon name="arrow" /></button> :
          <button
            className="primary"
            disabled={pending || !proposal?.rule || !!proposal.issues.length}
            onClick={() => { if (proposal?.rule) onAdd(proposal.rule) }}
          >Add rule<UiIcon name="arrow" />
          </button>
      }
    </div>
  </Modal>;
}
