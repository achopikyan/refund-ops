import { useState } from 'react';
import { api, money } from './components';
import type { Act, RequestRecord } from './components';
import { UiIcon } from './visualLanguage';

const fields = [
  { key: 'customer_id', label: 'Customer ID', type: 'text' },
  { key: 'requested_at', label: 'Requested date', type: 'date' },
  { key: 'amount_usd', label: 'Requested refund (USD)', type: 'number', step: '.01', min: '.01' },
  {
    key: 'category',
    label: 'Category',
    options: [['apparel', 'Apparel'], ['home', 'Home'], ['electronics', 'Electronics']]
  },
  {
    key: 'payment_method',
    label: 'Payment method',
    options: [['card', 'Card'], ['paypal', 'PayPal']]
  },
  {
    key: 'stated_reason',
    label: 'Customer reason',
    options: [
      ['wrong_size', 'Wrong size'],
      ['changed_mind', 'Changed mind'],
      ['arrived_damaged', 'Arrived damaged'],
      ['wrong_item', 'Wrong item'],
      ['never_arrived', 'Never arrived'],
      ['late_delivery', 'Late delivery']
    ]
  },
  { key: 'tenure_months', label: 'Customer tenure (months)', type: 'number', step: '1', min: '0' },
  {
    key: 'prior_refunds_12m',
    label: 'Prior refunds in 12 months',
    type: 'number',
    step: '1',
    min: '0'
  },
  { key: 'days_since_delivery', label: 'Days since delivery', type: 'number', step: '1', min: '0' },
  {
    key: 'fraud_flag',
    label: 'Payment risk',
    options: [['', 'Unknown'], ['no', 'Not flagged'], ['yes', 'Flagged']]
  },
];
const values = (r: RequestRecord): Record<string, string> => ({
  ...Object.fromEntries(fields.map(f => [f.key, String((r.data as any)[f.key] ?? '')])),
  amount_usd: r.data.amount_cents == null ? '' : (r.data.amount_cents / 100).toFixed(2),
  fraud_flag: r.data.fraud_flag === null ? '' : r.data.fraud_flag ? 'yes' : 'no',
  customer_note: r.data.customer_note,
  support_note: r.data.support_note,
});

export default function RequestDetails({ request: r, act, busy, editing, onEditingChange }: {
  request: RequestRecord,
  act: Act,
  busy: string,
  editing: boolean,
  onEditingChange: (value: boolean) => void
}) {
  const [draft, setDraft] = useState<Record<string, string>>({}),
    [original, setOriginal] = useState<Record<string, string>>({}),
    [version, setVersion] = useState(r.version),
    [note, setNote] = useState('');
  const begin = () => {
    const initial = values(r);
    setDraft(initial);
    setOriginal(initial);
    setVersion(r.version);
    setNote('');
    onEditingChange(true)
  };
  const change = (key: string, value: string) => setDraft(prev => ({ ...prev, [key]: value }));
  const changes = Object.fromEntries(Object.entries(draft).filter(([key, value]) => value !== original[key]));
  const changed = Object.keys(changes).length, stale = editing && version !== r.version;
  const display = values(r);
  return <section
    className={'request-details-card' + (editing ? ' is-editing' : '')}
    aria-labelledby={'request-details-' + r.id}
  >
    <div className="request-details-heading">
      <h3 id={'request-details-' + r.id}><UiIcon name="file" size={18} />Request details</h3>
      {
        r.status !== 'resolved' && !editing &&
        <button className="request-edit-button" aria-label="Edit request" disabled={!!busy} onClick={begin}>
          <UiIcon name="edit" size={15} />Edit</button>
      }
      {editing && <span className="request-edit-state">Editing</span>}
    </div>
    {
      editing ?
        <form
          onSubmit={
            async e => {
              e.preventDefault();
              if (!changed || !note.trim() || stale) return;
              const result = await act(
                'edit-request',
                () => api('/requests/' + r.id + '/correct', { version, changes, note }),
                'Request updated.'
              );
              if (result) onEditingChange(false)
            }
          }
        >
          <div className="request-fields-grid">
            {
              fields.map(f => <label key={f.key}>
                {f.label}
                {
                  f.options ?
                    <select value={draft[f.key] ?? ''} onChange={e => change(f.key, e.target.value)}>
                      {
                        !f.options.some(([v]) => v === draft[f.key]) &&
                        <option value={draft[f.key]}>{draft[f.key] || 'Unknown'}</option>
                      }
                      {f.options.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select> :
                    <input
                      autoFocus={f.key === 'customer_id'}
                      type={f.type}
                      min={f.min}
                      step={f.step}
                      value={draft[f.key] ?? ''}
                      required={['customer_id', 'requested_at', 'amount_usd'].includes(f.key)}
                      onChange={e => change(f.key, e.target.value)}
                    />
                }
              </label>)
            }
          </div>
          <div className="request-notes-grid">
            <label>Customer note<textarea
              rows={3}
              value={draft.customer_note ?? ''}
              onChange={e => change('customer_note', e.target.value)}
            />
            </label>
            <label>Support note<textarea
              rows={3}
              value={draft.support_note ?? ''}
              onChange={e => change('support_note', e.target.value)}
            />
            </label>
          </div>
          <label className="request-update-note">Update note<textarea
            rows={2}
            required
            value={note}
            onChange={e => setNote(e.target.value)}
            placeholder="What changed, and what did you verify?"
          />
          </label>
          {
            stale &&
            <p className="alert warning" role="alert">This request changed while you were editing. Cancel and reopen Edit to use the latest details.</p>
          }
          <div className="request-edit-footer">
            <p>
              {changed ? `${changed} ${changed === 1 ? 'field' : 'fields'} changed` : 'No changes yet'}
              <small>Updates are saved to the request history.</small>
            </p>
            <div className="button-row">
              <button type="button" disabled={!!busy} onClick={() => onEditingChange(false)}>Cancel</button>
              <button className="primary" type="submit" disabled={!!busy || !changed || !note.trim() || stale}>Save request</button>
            </div>
          </div>
        </form> :
        <>
          <div className="request-total">
            <div><span className="muted">Requested refund</span><h2>{money(r.data.amount_cents)}</h2></div>
          </div>
          <dl className="request-details-grid">
            {
              fields.filter(f => f.key !== 'amount_usd').map(f => <div key={f.key}>
                <dt>{f.label}</dt>
                <dd>
                  {f.options?.find(([value]) => value === display[f.key])?.[1] || display[f.key] || 'Unknown'}
                </dd>
              </div>)
            }
          </dl>
        </>
    }
    {
      !editing &&
      <details className="request-raw-data">
        <summary>Original normalized data</summary>
        <pre className="lab-json">{JSON.stringify(r.data, null, 2)}</pre>
      </details>
    }
  </section>;
}
