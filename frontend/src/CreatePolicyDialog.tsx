import { useState } from 'react';
import { Modal } from './components';
import type { PolicyRecord } from './components';
import { UiIcon } from './visualLanguage';
import { policyLabel } from './policyIdentity';

export default function CreatePolicyDialog({ policies, currentId, onExisting, onScratch, onClose }: {
  policies: PolicyRecord[],
  currentId: string,
  onExisting: (p: PolicyRecord) => void,
  onScratch: () => void,
  onClose: () => void
}) {
  const [mode, setMode] = useState('existing'), [baseId, setBaseId] = useState(currentId);
  const base = policies.find(p => p.id === baseId);
  return <Modal title="Create policy" onClose={onClose}>
    <p>Choose how to start your new version.</p>
    <div className="policy-create-options" role="group" aria-label="Policy starting point">
      <button
        className={mode === 'existing' ? 'selected' : ''}
        aria-pressed={mode === 'existing'}
        onClick={() => setMode('existing')}
      >
        <UiIcon name="copy" size={23} />
        <strong>From existing version</strong>
        <span>Copy its rules and settings.</span>
      </button>
      <button
        className={mode === 'scratch' ? 'selected' : ''}
        aria-pressed={mode === 'scratch'}
        onClick={() => setMode('scratch')}
      >
        <UiIcon name="file" size={23} />
        <strong>From scratch</strong>
        <span>Start with an empty rule set.</span>
      </button>
    </div>
    {
      mode === 'existing' ?
        <label>Base version<select aria-label="Base policy version" value={baseId} onChange={e => setBaseId(e.target.value)}>
          {
            policies.map(p => <option key={p.id} value={p.id}>
              {policyLabel(p.version)}
              {p.id === currentId ? ' · Current' : ''} · {p.data.rules.length} rules</option>)
          }
        </select>
          <small>The saved source version and its checks stay unchanged.</small>
        </label> :
        <p className="creation-note">No rules or semantic questions are copied. Standard evidence checks remain in effect. Automatic approval
          requires an explicit matching rule.</p>
    }
    <div className="modal-actions">
      <button onClick={onClose}>Cancel</button>
      <button
        className="primary"
        disabled={mode === 'existing' && !base}
        onClick={() => { if (mode === 'scratch') onScratch(); else if (base) onExisting(base); onClose() }}
      >Create version</button>
    </div>
  </Modal>;
}
