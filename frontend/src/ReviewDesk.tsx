import { useState } from 'react';
import { Empty, Icon, money, words, ReasonBadge, RequestDrawer } from './components';
import type { Act, RequestRecord } from './components';
import { ActionTag } from './visualLanguage';

export default function ReviewDesk({ requests, selected, onSelect, act, busy }: {
  requests: RequestRecord[],
  selected: string | null,
  onSelect: (id: string | null) => void,
  act: Act,
  busy: string
}) {
  const [search, setSearch] = useState(''),
    [scope, setScope] = useState('all'),
    [editing, setEditing] = useState(false);
  const visible = requests.filter(r => (scope === 'all' ?
    true :
    scope === 'waiting' ?
      (r.status.startsWith('waiting') || r.status === 'on_hold') :
      scope === 'completed' ?
        r.status === 'resolved' :
        scope === 'fraud' ? r.queue === 'fraud' && r.status !== 'resolved' : r.status !== 'resolved') &&
    [r.external_id, r.data.customer_id, r.data.stated_reason].join(' ').toLowerCase().includes(search.toLowerCase()));
  const current = requests.find(r => r.id === selected) || visible[0];
  const next = current ? visible[visible.findIndex(r => r.id === current.id) + 1] : visible[0];
  return <div className="review-desk">
    <section className="review-queue" aria-label="Request queue">
      <header>
        <div><strong>Request queue</strong><span>{visible.length}</span></div>
        <label className="search">
          <Icon name="search" />
          <input
            disabled={editing}
            aria-label="Search review queue"
            placeholder="Request or customer"
            value={search}
            onChange={e => { setSearch(e.target.value); onSelect(null) }}
          />
        </label>
        <select
          disabled={editing}
          aria-label="Review queue filter"
          value={scope}
          onChange={e => { setScope(e.target.value); onSelect(null) }}
        >
          <option value="all">All</option>
          <option value="open">Open</option>
          <option value="fraud">Fraud Review</option>
          <option value="waiting">Waiting</option>
          <option value="completed">Completed</option>
        </select>
      </header>
      <div className="review-queue-items">
        {
          visible.map(r => <button
            disabled={editing && r.id !== current?.id}
            className={'review-queue-item ' + (r.id === current?.id ? 'selected' : '')}
            key={r.id}
            aria-label={'Review ' + r.external_id}
            aria-pressed={r.id === current?.id}
            onClick={() => onSelect(r.id)}
          >
            <span className="review-queue-line">
              <strong>{r.external_id}</strong>
              <b>{money(r.data.amount_cents)}</b>
            </span>
            <span className="review-queue-customer">{r.data.customer_id} · {words(r.data.stated_reason)}</span>
            <span className="review-queue-labels">
              <ActionTag action={r.evaluation.action} route />
              <ReasonBadge code={r.evaluation.reason_code} label={r.evaluation.reason_label} />
            </span>
            {r.status !== 'ready' && <small>{words(r.status)}</small>}
          </button>)
        }
        {!visible.length && <div className="review-queue-empty">No requests in this view.</div>}
      </div>
    </section>
    <div className="review-case">
      {
        current ?
          <RequestDrawer
            key={current.id}
            request={current}
            embedded
            onNext={next && !editing ? () => onSelect(next.id) : undefined}
            onEditingChange={setEditing}
            onClose={() => onSelect(null)}
            act={act}
            busy={busy}
          /> :
          <Empty title="Queue complete" detail="Choose another filter to review more requests." />
      }
    </div>
  </div>;
}
