import React, { useEffect, useState, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import './styles.css';
import RequestDetails from './RequestDetails';
import PolicyEvaluation from './PolicyEvaluation';
import { RequestSection, EvidenceAnalysis, CustomerHistory, ChargebackRisk } from './RequestSections';
import { uiIconPaths, UiIcon, reasonStyles } from './visualLanguage';


export type Fact = {
  name: string,
  value: string,
  source: string,
  quote: string,
  note?: string,
  context?: Record<string, unknown>
};
export type Evidence = {
  facts: Record<string, Fact>,
  summary: string,
  method: string | null,
  complete: boolean,
  issues: string[],
  reviewed_by?: string
};
export type Evaluation = {
  action: string,
  queue: string,
  reason_code: string,
  reason_label: string,
  next_action: string,
  supporting_signals: string[],
  route: string,
  explanation: string,
  rule_id: string | null,
  trace: { rule: string, matched: boolean | null, priority: number }[]
};
export type Data = {
  context_issues?: string[],
  request_id: string,
  customer_id: string,
  requested_at: string,
  amount_cents: number | null,
  category: string,
  payment_method: string,
  tenure_months: number | null,
  prior_refunds_12m: number | null,
  days_since_delivery: number | null,
  fraud_flag: boolean | null,
  stated_reason: string,
  customer_note: string,
  support_note: string,
  errors: string[],
  warnings: string[]
};
export type RequestRecord = {
  analysis?: {
    status: string,
    error?: string,
    error_code?: string,
    retrying?: boolean,
    retry_at?: number | null,
    updated_at?: string,
    evidence?: Evidence
  },
  execution_state?: string,
  follow_up?: { note: string, closed: number } | null,
  id: string,
  external_id: string,
  data: Data,
  evidence: Evidence,
  evaluation: Evaluation,
  status: string,
  queue: string,
  owner: string | null,
  version: number,
  conflict: number,
  versions: { normalized: Data, raw: Record<string, string>, hash: string }[],
  decision: { action: string, amount_cents: number | null, reason: string, actor: string } | null,
  ledger: { status: string } | null
};
export type Condition = { field: string, op: string, value: string | number | boolean | string[] | number[] | null };
export type Rule = {
  reason_code?: string,
  reason?: string,
  id: string,
  name: string,
  priority: number,
  conditions: Condition[],
  match: 'all' | 'any',
  action: string,
  enabled: boolean
};
export type ExecutionLimits = {
  max_single_cents: number,
  daily_cents: number,
  customer_daily_cents: number,
  release_cents: number,
  release_count: number
};
export type Policy = {
  checks?: Record<string, boolean>,
  execution_limits?: ExecutionLimits | null,
  automation_enabled?: boolean,
  name: string,
  change_mind_days?: number,
  damage_photo_above_cents?: number,
  rules: Rule[],
  criteria: { id: string, question: string, sources: string[] }[]
};
export type PolicyRecord = {
  execution_limits?: ExecutionLimits,
  hash?: string,
  id: string,
  name: string,
  data: Policy,
  status: string,
  created_at: string,
  version?: number,
  parent_id?: string | null
};
export type Settings = {
  provider?: 'openai' | 'openrouter',
  base_url?: string,
  configured: boolean,
  source: string,
  model: string,
  checked: boolean,
  enabled: boolean,
  budget_usd: number,
  analysis_mode?: 'saved_demo' | 'live' | 'unavailable',
  saved_analysis_provider?: string | null,
  saved_analysis_model?: string | null
};
export type Metrics = {
  requests: number,
  resolved: number,
  ready_auto: number,
  review: number,
  conflicts: number,
  refund_cents: number,
  refund_count: number,
  policy: string,
  state: { mode: string, as_of: string },
  baseline: {
    requests: number,
    auto: number,
    manual: number,
    manual_approved: number,
    review_minutes: number,
    chargebacks: number,
    unknown_outcomes: number
  },
  ai: {
    calls: number,
    cost_usd: number,
    unknown_cost_calls: number,
    failures: number,
    p95_latency_seconds: number | null
  },
  quality: {
    outcomes: Record<string, number>,
    decisions: number,
    automatic_decisions: number,
    waiting: number
  }
};
export type Audit = {
  id: number,
  type: string,
  actor: string,
  object_id: string,
  detail: Record<string, unknown>,
  created_at: string
};
export type ImportReport = {
  id: string,
  name: string,
  kind: string,
  row_count: number,
  unique_ids: number,
  exact_duplicates: number,
  conflicts: string[],
  committed: boolean,
  issues: { line: number, id: string, errors: string[], warnings: string[] }[]
};
export const money = (n: number | null | undefined) => n == null ?
  'Unknown' :
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(n / 100);
export const plainText = (s: string) => s.replace(/\s*(?:\u2014|--+)\s*/g, ': ').replaceAll('\u2013', '-');
export const words = (s: string) => plainText(s).replaceAll('_', ' ');
export function ReasonBadge({ label, explanation, code = 'policy_rule' }: { label: string, explanation?: string, code?: string }) {
  const style = reasonStyles[code] || reasonStyles.policy_rule;
  return <span
    className={'reason-badge tone-' + style.tone}
    data-reason={code}
    aria-label={plainText(label)}
    title={plainText(explanation || label)}
  >
    <UiIcon name={style.icon} size={16} />
    <span className="reason-badge-value">{plainText(label)}</span>
  </span>
}
export function RuleReasonBadge({ rule }: { rule: Rule }) {
  const { data: reasons = {} } = useQuery({ queryKey: ['routing-reasons'], queryFn: () => api<Record<string, string>>('/reason-catalog') });
  let code = rule.reason_code || 'policy_rule';
  return <ReasonBadge
    code={code}
    label={reasons[code] || 'General'}
    explanation={rule.reason || rule.name}
  />;
}
export function SourceText({ text, source, evidence }: { text: string, source: string, evidence: Evidence }) {
  const ranges = Object.values(evidence.facts).filter(f => f.source === source && f.quote && text.includes(f.quote)).map(f => [text.indexOf(f.quote), text.indexOf(f.quote) + f.quote.length]).sort((a, b) => a[0] - b[0]);
  const parts: React.ReactNode[] = [];
  let at = 0;
  for (const [start, end] of ranges) {
    if (start < at) continue;
    parts.push(text.slice(at, start), <mark key={start}>{text.slice(start, end)}</mark>);
    at = end
  }
  parts.push(text.slice(at));
  return <>{text ? parts : 'No note provided.'}</>
}
function ResponsePreview({ request: r }: { request: RequestRecord }) {
  const [copied, setCopied] = useState(false);
  const message = r.decision ?
    r.decision.action === 'rejected' ?
      `Your refund request ${r.external_id} was reviewed. We are unable to approve it. Reason: ${r.decision.reason}` :
      `Your refund request ${r.external_id} was reviewed. The approved amount is ${money(r.decision.amount_cents)}. Reason: ${r.decision.reason}` :
    r.status === 'waiting_for_customer' ?
      `To continue reviewing request ${r.external_id}, please provide the information requested by our support team. No refund has been issued yet.` :
      r.status === 'waiting_for_fraud' ?
        `Request ${r.external_id} is with our specialist team. We will update you after the review. No refund has been issued yet.` :
        `We are reviewing request ${r.external_id}. No refund decision has been made yet.`;
  return <details className="subsection">
    <summary>Customer response preview</summary>
    <p className="small muted">Template only. Review the wording before use; nothing is sent from this demo.</p>
    <blockquote>{message}</blockquote>
    <button onClick={async () => { await navigator.clipboard.writeText(message); setCopied(true) }}>
      {copied ? 'Copied' : 'Copy draft response'}
    </button>
  </details>
}
export async function api<T>(path: string, body?: unknown, method?: string): Promise<T> {
  const response = await fetch(
    '/api' + path,
    {
      method: method || (body === undefined ? 'GET' : 'POST'),
      headers: {
        ...(body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        'X-Demo-Role': sessionStorage.getItem('refund-role') || ''
      },
      body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body)
    }
  );
  let value: unknown;
  try { value = await response.json() }
  catch { throw new Error('The server could not complete this request. Try again.') }
  if (!response.ok) {
    const detail = value && typeof value === 'object' && 'detail' in value ? value.detail : undefined;
    throw new Error(detail === 'API route not found' || response.status === 405 ?
      'This API is unavailable on the running server. Restart using START.cmd (Windows) or START.command (macOS), then refresh this page.' :
      typeof detail === 'string' ? detail : 'The request could not be completed.');
  }
  return value as T;
}
const iconPaths: Record<string, string> = {
  queue: 'M4 5h16M4 12h16M4 19h16M8 5v14',
  policy: 'M12 3l8 4v5c0 5-8 9-8 9S4 17 4 12V7l8-4zm-4 9 3 3 5-6',
  chart: 'M4 20V4m0 16h16M8 16v-4m4 4V8m4 8V5',
  activity: 'M3 12h4l3-8 4 16 3-8h4',
  settings: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8m0-5v3m0 12v3M3 12h3m12 0h3M6 6l2 2m8 8 2 2M6 18l2-2m8-8 2-2',
  upload: 'M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5',
  arrow: 'M5 12h14m-5-5 5 5-5 5',
  check: 'M5 12l4 4L19 6',
  close: 'M6 6l12 12M6 18 18 6',
  search: 'M10 4a6 6 0 1 0 0 12 6 6 0 0 0 0-12m5 11 5 5',
  spark: 'M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3'
};
export function Icon({ name, size = 18 }: { name: string, size?: number }) {
  return <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d={uiIconPaths[name] || iconPaths[name] || iconPaths.queue} />
  </svg>
}
export function Badge({ children, tone = 'neutral' }: { children: React.ReactNode, tone?: string }) { return <span className={'badge ' + tone}>{children}</span> }
export function Empty({ title, detail }: { title: string, detail: string }) {
  return <div className="empty"><Icon name="check" size={28} /><h3>{title}</h3><p>{detail}</p></div>
}
function useDialog(onClose: () => void, enabled = true) {
  const ref = useRef<HTMLElement>(null), close = useRef(onClose);
  close.current = onClose;
  useEffect(
    () => {
      if (!enabled) return;
      const before = document.activeElement as HTMLElement;
      const root = ref.current;
      if (!root) return;
      const focusable = () => Array.from(root.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href],[tabindex="0"]')).filter(x => x.getClientRects().length);
      queueMicrotask(() => focusable()[0]?.focus());
      const key = (e: KeyboardEvent) => {
        const dialogs = document.querySelectorAll('[role="dialog"]');
        if (dialogs[dialogs.length - 1] !== root) return;
        if (e.key === 'Escape') { e.preventDefault(); close.current() }
        if (e.key === 'Tab') {
          const list = focusable(), first = list[0], last = list[list.length - 1];
          if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus() } else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus() }
        }
      };
      document.addEventListener('keydown', key);
      return () => { document.removeEventListener('keydown', key); if (before?.isConnected) before.focus() }
    },
    [enabled]
  );
  return ref;
}
export function Modal({ title, children, onClose }: { title: string, children: React.ReactNode, onClose: () => void }) {
  const ref = useDialog(onClose);
  return <div className="scrim" onMouseDown={onClose}>
    <section
      ref={ref}
      className="modal"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onMouseDown={e => e.stopPropagation()}
    >
      <header>
        <h2>{title}</h2>
        <button className="icon-button" onClick={onClose} aria-label="Close dialog">
          <Icon name="close" />
        </button>
      </header>
      {children}
    </section>
  </div>
}
export type Act = (label: string, fn: () => Promise<unknown>, message?: string) => Promise<unknown>;
export function PageHeading({ title, text }: { title: string, text: string }) {
  return <div className="page-heading">
    <div className="eyebrow">REFUND OPERATIONS</div>
    <h1>{title}</h1>
    <p>{text}</p>
  </div>
}
export function Metric({ label, value, detail, accent = false, amber = false }: { label: string, value: string, detail: string, accent?: boolean, amber?: boolean }) {
  return <div className={'metric ' + (accent ? 'accent' : '')}>
    <div>{label}<span className={amber ? 'amber-text' : 'muted'}>{amber ? '◉' : '↗'}</span></div>
    <strong>{value}</strong>
    <p>{detail}</p>
  </div>
}
export function RequestDrawer({ request: r, onClose, act, busy, embedded = false, onNext, onEditingChange }: {
  request: RequestRecord,
  onClose: () => void,
  act: Act,
  busy: string,
  embedded?: boolean,
  onNext?: () => void,
  onEditingChange?: (editing: boolean) => void
}) {
  const ref = useDialog(onClose, !embedded);
  const [editingRequest, setEditingRequest] = useState(false);
  useEffect(() => { onEditingChange?.(editingRequest) }, [editingRequest, onEditingChange]);
  const [action, setAction] = useState(''),
    [reason, setReason] = useState(''),
    [amount, setAmount] = useState(''),
    [factName, setFactName] = useState('photo'),
    [factValue, setFactValue] = useState('yes'),
    [evidenceNote, setEvidenceNote] = useState(''),
    [conflictNote, setConflictNote] = useState(''),
    [followUpNote, setFollowUpNote] = useState(''),
    [outcomeNote, setOutcomeNote] = useState(''),
    [outcomeType, setOutcomeType] = useState(''),
    [versionIndex, setVersionIndex] = useState(0);
  const { data: events = [] } = useQuery({
    queryKey: ['request-audit', r.id, r.version],
    queryFn: () => api<Audit[]>('/requests/' + r.id + '/audit')
  });
  const closeAction = () => { setAction(''); setReason(''); setAmount('') };
  const submit = async () => {
    const value = await act(
      'decision',
      () => api(
        '/requests/' + r.id + '/decisions',
        {
          version: r.version,
          action,
          amount_cents: action === 'rejected' ?
            null :
            action === 'partial' ? Math.round(Number(amount) * 100) : r.data.amount_cents,
          reason,
          idempotency_key: crypto.randomUUID()
        }
      ),
      'Decision saved.'
    );
    if (value) closeAction()
  };
  const workflow = (a: string, n = '') => act(
    a,
    () => api('/requests/' + r.id + '/workflow', { version: r.version, action: a, note: n }),
    'Request updated.'
  );
  return <div
    className={embedded ? "request-inline" : "drawer-scrim"}
    onMouseDown={embedded ? undefined : onClose}
  >
    <aside
      ref={ref}
      className={"drawer" + (embedded ? " request-inline-panel" : "")}
      role={embedded ? "region" : "dialog"}
      aria-modal={embedded ? undefined : true}
      aria-label={'Request ' + r.external_id}
      onMouseDown={e => e.stopPropagation()}
    >
      <header className="drawer-header">
        <div><div className="eyebrow">REQUEST DETAIL</div><h2>{r.external_id}</h2></div>
        <div className="button-row">
          {
            embedded ?
              <button disabled={!onNext || editingRequest || !!busy} onClick={onNext}>Next request<Icon name="arrow" />
              </button> :
              <button className="icon-button" aria-label="Close request" onClick={onClose}>
                <Icon name="close" />
              </button>
          }
        </div>
      </header>
      <nav className="request-jump-nav" aria-label="Request sections">
        {
          [
            ["case-details", "Request"],
            ["case-policy", "Policy"],
            ["case-evidence", "Evidence"],
            ["case-risk", "Risk"],
            ["case-customer", "Customer"],
            ["case-activity", "Activity"]
          ].map(([id, label]) => <a
            key={id}
            href={"#" + id}
            onClick={
              e => {
                e.preventDefault();
                document.getElementById(id)?.scrollIntoView({ behavior: "instant", block: "start" })
              }
            }
          >
            {label}
          </a>)
        }
      </nav>
      <div className="drawer-body">
        <div id="case-details">
          <RequestDetails
            request={r}
            act={act}
            busy={busy}
            editing={editingRequest}
            onEditingChange={setEditingRequest}
          />
        </div>
        <PolicyEvaluation request={r} />

        {r.data.errors.length > 0 && <div className="alert error">{r.data.errors.join('; ')}</div>}
        {
          r.conflict > 0 && r.status !== 'resolved' &&
          <section className="subsection conflict-box">
            <h3>Resolve conflicting versions</h3>
            {
              r.versions.map((v, i) => <label className="radio" key={i}>
                <input
                  type="radio"
                  name="version"
                  checked={i === versionIndex}
                  onChange={() => setVersionIndex(i)}
                />
                {v.normalized.requested_at} · {money(v.normalized.amount_cents)}
                <small>{v.normalized.customer_note}</small>
              </label>)
            }
            <textarea
              aria-label="Conflict resolution reason"
              placeholder="Explain which version and amount you accepted"
              value={conflictNote}
              onChange={e => setConflictNote(e.target.value)}
            />
            <button
              disabled={!!busy || !conflictNote.trim()}
              onClick={
                () => act(
                  'resolve',
                  () => api(
                    '/requests/' + r.id + '/resolve',
                    { version: r.version, index: versionIndex, note: conflictNote }
                  ),
                  'Canonical version saved.'
                )
              }
            >Accept selected version</button>
          </section>
        }
        <EvidenceAnalysis request={r}>
          {
            r.status !== 'resolved' &&
            <details className="subsection evidence-form">
              <summary>Record staff evidence or complete note review</summary>
              <p>Record what you actually checked. This creates a new evidence snapshot.</p>
              <div className="form-row">
                <select aria-label="Evidence fact" value={factName} onChange={e => setFactName(e.target.value)}>
                  {
                    [
                      'photo',
                      'fraud_confirmed',
                      'our_error',
                      'already_refunded',
                      'investigation',
                      'proof_delivery',
                      'cosmetic',
                      'matches_order',
                      'delivered',
                      'reason_conflict'
                    ].map(x => <option value={x} key={x}>{words(x)}</option>)
                  }
                </select>
                <select aria-label="Evidence value" value={factValue} onChange={e => setFactValue(e.target.value)}>
                  {['yes', 'no', 'unknown'].map(x => <option key={x}>{x}</option>)}
                </select>
              </div>
              <textarea
                aria-label="Evidence review note"
                placeholder="Source and result of your review"
                value={evidenceNote}
                onChange={e => setEvidenceNote(e.target.value)}
              />
              <div className="button-row">
                <button
                  disabled={!evidenceNote.trim() || !!busy}
                  onClick={
                    () => act(
                      'evidence',
                      () => api(
                        '/requests/' + r.id + '/evidence',
                        { version: r.version, facts: { [factName]: factValue }, note: evidenceNote }
                      ),
                      'Staff evidence saved.'
                    )
                  }
                >Save fact & review</button>
                <button
                  disabled={!evidenceNote.trim() || !!busy}
                  onClick={
                    () => act(
                      'review',
                      () => api('/requests/' + r.id + '/evidence', { version: r.version, facts: {}, note: evidenceNote }),
                      'Notes marked reviewed.'
                    )
                  }
                >Mark notes reviewed</button>
              </div>
            </details>
          }
        </EvidenceAnalysis>
        <ChargebackRisk request={r} />
        <CustomerHistory request={r} />
        <RequestSection
          id="case-activity"
          title="Activity"
          icon="history"
          collapsible
          subtitle="Changes, staff checks and decisions in chronological order."
        >
          <div className="timeline">
            {
              events.map(a => <details className="timeline-item" key={a.id}>
                <summary>
                  <strong>{words(a.type)}</strong>
                  <small>{a.actor} / {new Date(a.created_at).toLocaleString()}</small>
                </summary>
                <pre className="lab-json">{JSON.stringify(a.detail, null, 2)}</pre>
              </details>)
            }
          </div>
        </RequestSection>

        <ResponsePreview request={r} />
        {
          r.decision &&
          <div className="resolved-card">
            <Icon name="check" />
            <h3>{words(r.decision.action)} · {money(r.decision.amount_cents)}</h3>
            <p>{r.decision.reason}</p>
            <small>
              {
                r.ledger ? 'Simulated refund recorded once to original payment method.' : 'No payment was created.'
              }
            </small>
            <details>
              <summary>
                {r.follow_up && !r.follow_up.closed ? 'Close follow-up review' : 'Reopen for follow-up'}
              </summary>
              <p>The original decision and payment stay locked. This cannot create a second refund.</p>
              <textarea
                aria-label="Follow-up reason"
                value={followUpNote}
                onChange={e => setFollowUpNote(e.target.value)}
              />
              <button
                disabled={!followUpNote.trim() || !!busy}
                onClick={
                  () => act(
                    'reopen',
                    () => api(
                      '/requests/' + r.id + '/reopen',
                      {
                        version: r.version,
                        note: followUpNote,
                        action: r.follow_up && !r.follow_up.closed ? 'close' : 'reopen'
                      }
                    ),
                    'Follow-up state saved. Original payment remains locked.'
                  )
                }
              >
                {r.follow_up && !r.follow_up.closed ? 'Close follow-up' : 'Reopen for review'}
              </button>
            </details>
            <details>
              <summary>Record follow-up outcome</summary>
              <select
                aria-label="Outcome type"
                value={outcomeType}
                onChange={e => setOutcomeType(e.target.value)}
              >
                <option value="">Select outcome</option>
                {['chargeback', 'appeal', 'audit_pass', 'audit_fail'].map(x => <option key={x}>{x}</option>)}
              </select>
              <textarea
                aria-label="Outcome note"
                value={outcomeNote}
                onChange={e => setOutcomeNote(e.target.value)}
              />
              <button
                disabled={!outcomeNote.trim() || !outcomeType || !!busy}
                onClick={
                  () => act(
                    'outcome',
                    () => api('/requests/' + r.id + '/outcomes', { type: outcomeType, note: outcomeNote }),
                    'Outcome recorded separately from the original evidence.'
                  )
                }
              >Record outcome</button>
            </details>
          </div>
        }
      </div>
      {
        r.status !== 'resolved' &&
        <footer className="drawer-footer">
          {
            editingRequest &&
            <p className="request-edit-hint">Save or cancel your edits before making a decision.</p>
          }
          <div className="button-row">
            <button
              disabled={
                !!busy || editingRequest || !!r.conflict || r.status.startsWith('waiting') || r.status === 'on_hold' ||
                r.evaluation.action === 'hold'
              }
              className="primary"
              onClick={() => setAction('approved')}
            >Approve {money(r.data.amount_cents)}
            </button>
            <button
              disabled={
                !!busy || editingRequest || !!r.conflict || r.status.startsWith('waiting') || r.status === 'on_hold' ||
                r.evaluation.action === 'hold'
              }
              onClick={() => setAction('partial')}
            >Partial refund</button>
            <button
              disabled={
                !!busy || editingRequest || r.status.startsWith('waiting') || r.status === 'on_hold' ||
                r.evaluation.action === 'hold'
              }
              onClick={() => setAction('rejected')}
            >Reject</button>
          </div>
          <div className="button-row secondary-actions">
            <button
              className="text-button"
              disabled={!!busy || editingRequest}
              onClick={() => setAction('information')}
            >Request information</button>
            <button
              className="text-button"
              disabled={!!busy || editingRequest}
              onClick={() => setAction('fraud')}
            >Escalate to fraud</button>
            <button
              className="text-button"
              disabled={!!busy || editingRequest}
              onClick={() => setAction('hold')}
            >Place on hold</button>
            {
              (r.status.startsWith('waiting') || r.status === 'on_hold') &&
              <button
                className="text-button"
                disabled={!!busy || editingRequest}
                onClick={() => setAction('resume')}
              >Resume after verification</button>
            }
          </div>
        </footer>
      }
      {
        action &&
        <Modal
          title={
            ['information', 'fraud', 'hold', 'resume'].includes(action) ?
              words(action === 'fraud' ?
                'Escalate to fraud' :
                action === 'hold' ?
                  'Place on hold' :
                  action === 'resume' ? 'Resume after verification' : 'Request information') :
              words(action) + ' refund'
          }
          onClose={closeAction}
        >
          <p>Record the reason. This action will be saved to the request history.</p>
          {
            action === 'partial' &&
            <label>Refund amount in USD<input
              type="number"
              min=".01"
              max={(r.data.amount_cents || 0) / 100}
              step=".01"
              value={amount}
              onChange={e => setAmount(e.target.value)}
            />
            </label>
          }
          <label>Reason<textarea
            autoFocus
            value={reason}
            onChange={e => setReason(e.target.value)}
            placeholder="What did you check, and why is this the right action?"
          />
          </label>
          <div className="modal-actions">
            <button onClick={closeAction}>Cancel</button>
            <button
              className="primary"
              disabled={!!busy || !reason.trim() || action === 'partial' && !amount}
              onClick={
                async () => {
                  if (['information', 'fraud', 'hold', 'resume'].includes(action)) { if (await workflow(action, reason)) closeAction() } else await submit()
                }
              }
            >Confirm {
                action === 'approved' ?
                  'approval' :
                  action === 'partial' ? 'partial refund' : action === 'rejected' ? 'rejection' : 'request'
              }
            </button>
          </div>
        </Modal>
      }
    </aside>
  </div>
}
const fieldLabels: Record<string, string> = {
  amount_cents: 'Refund amount (USD)',
  tenure_months: 'Customer tenure (months)',
  prior_refunds_12m: 'Prior refunds in 12 months',
  days_since_delivery: 'Days since delivery',
  fraud_flag: 'Payment risk flagged',
  stated_reason: 'Customer-selected reason',
  category: 'Product category',
  payment_method: 'Payment method',
  'facts.fraud_confirmed': 'Stolen card confirmed by fraud team',
  'facts.fraud_reported': 'Stolen card reported',
  'facts.our_error': 'Our fulfilment error confirmed',
  'facts.location': 'Location mentioned',
  'facts.investigation': 'Carrier investigation confirmed',
  'facts.photo': 'Photo received by support',
  'facts.proof_delivery': 'Delivery proof recorded',
  'facts.already_refunded': 'Previous refund reported',
  'facts.cosmetic': 'Cosmetic damage',
  'facts.matches_order': 'Item matches the order',
  'facts.reason_conflict': 'Reason conflicts with notes'
};
export function ConditionEditor({ condition: c, fields, update, remove }: { condition: Condition, fields: string[], update: (c: Condition) => void, remove: () => void }) {
  const { data: catalog = {} } = useQuery({
    queryKey: ['catalog'],
    queryFn: () => api<Record<string, { label: string, type: string }>>('/field-catalog')
  });
  const numeric = ['amount_cents', 'tenure_months', 'prior_refunds_12m', 'days_since_delivery'].includes(c.field),
    dollars = c.field === 'amount_cents';
  const display = Array.isArray(c.value) ?
    c.value.map(x => dollars ? Number(x) / 100 : x).join(', ') :
    dollars && typeof c.value === 'number' ? c.value / 100 : String(c.value ?? '');
  const operators: Record<string, string> = {
    eq: 'is',
    ne: 'is not',
    gt: 'is more than',
    gte: 'is at least',
    lt: 'is less than',
    lte: 'is at most',
    in: 'is one of'
  };
  return <div className="condition">
    <select
      aria-label="Condition field"
      value={c.field}
      onChange={
        e => update({
          ...c,
          field: e.target.value,
          value: e.target.value === 'fraud_flag' ? false : e.target.value === 'amount_cents' ? 30000 : ''
        })
      }
    >
      {
        [...new Set([...fields, c.field])].map(f => <option key={f} value={f}>
          {catalog[f]?.label || fieldLabels[f] || 'Note criterion: ' + f.replace('facts.semantic.', '')}
        </option>)
      }
    </select>
    <select aria-label="Operator" value={c.op} onChange={e => update({ ...c, op: e.target.value })}>
      {
        Object.entries(operators).map(([value, label]) => <option key={value} value={value}>{label}</option>)
      }
    </select>
    {
      c.field === 'fraud_flag' ?
        <select
          aria-label="Condition value"
          value={String(c.value)}
          onChange={e => update({ ...c, value: e.target.value === 'true' })}
        >
          <option value="true">Flagged</option>
          <option value="false">Not flagged</option>
        </select> :
        <input
          aria-label="Condition value"
          value={display}
          placeholder={c.field.startsWith('facts.') ? 'yes / no / unknown' : ''}
          onChange={
            e => {
              const raw = e.target.value;
              const value = raw.trim() === '' ?
                '' :
                c.op === 'in' ?
                  (numeric ?
                    raw.split(',').map(x => Math.round(Number(x.trim()) * (dollars ? 100 : 1))) :
                    raw.split(',').map(x => x.trim())) :
                  numeric ? Math.round(Number(raw) * (dollars ? 100 : 1)) : raw;
              update({ ...c, value })
            }
          }
        />
    }
    <button className="icon-button" aria-label="Remove condition" onClick={remove}>×</button>
  </div>
}
export function SettingsPanel({ settings: s, act, busy }: { settings: Settings, act: Act, busy: string }) {
  const { data: metrics } = useQuery({ queryKey: ['ai-usage'], queryFn: () => api<Metrics>('/metrics'), refetchInterval: 3000 });
  const activeProvider = s.provider || 'openrouter';
  const [key, setKey] = useState(''),
    [provider, setProvider] = useState(activeProvider),
    [model, setModel] = useState(s.model),
    [models, setModels] = useState<{ id: string, name: string }[]>([]);
  useEffect(
    () => { setModel(s.model); setProvider(s.provider || 'openrouter') },
    [s.model, s.provider]
  );
  const label = provider === 'openai' ? 'OpenAI' : 'OpenRouter',
    unchangedProvider = provider === activeProvider;
  const chooseProvider = (value: 'openai' | 'openrouter') => {
    setProvider(value);
    setKey('');
    setModels([]);
    setModel(value === activeProvider ? s.model : value === 'openai' ? 'gpt-6.1-sol' : 'openai/gpt-6.1-sol')
  };
  return <>
    <PageHeading
      title="AI connection"
      text="Connect OpenAI directly or use OpenRouter. Credentials stay on the local backend."
    />
    <section className="panel padded settings-panel">
      <div className="section-line">
        <h2>AI provider</h2>
        <Badge
          tone={unchangedProvider && s.checked ? 'green' : unchangedProvider && s.configured ? 'amber' : 'neutral'}
        >
          {
            unchangedProvider && s.checked ?
              'Connection verified' :
              unchangedProvider && s.configured ? 'Key configured · not verified' : 'Not connected'
          }
        </Badge>
      </div>
      <p>AI extracts evidence and prepares rule drafts. The Python policy engine controls routes, limits and
        payments.</p>
      {
        s.analysis_mode === 'saved_demo' &&
        <div className="alert info" role="status">
          <div>
            <strong>Using saved live analysis</strong>
            <p>
              {s.saved_analysis_provider === 'openrouter' ? 'OpenRouter' : s.saved_analysis_provider} · {s.saved_analysis_model}
            </p>
            <p>The supplied records reuse their original completed analysis. Connect the selected provider to analyze
              new or edited requests. Saved evidence keeps its original model and source.</p>
          </div>
        </div>
      }
      <label>Provider<select
        aria-label="AI provider"
        value={provider}
        onChange={e => chooseProvider(e.target.value as 'openai' | 'openrouter')}
      >
        <option value="openai">OpenAI</option>
        <option value="openrouter">OpenRouter</option>
      </select>
      </label>
      <p className="small muted">
        {provider === 'openai' ? 'Direct OpenAI API: api.openai.com' : 'OpenRouter API: openrouter.ai'}. Both use the official OpenAI Python client.</p>
      <label>API key<input
        aria-label="API key"
        type="password"
        autoComplete="off"
        spellCheck={false}
        value={key}
        onChange={e => setKey(e.target.value)}
        placeholder={
          unchangedProvider && s.configured ?
            'A key is configured. Paste to replace it.' :
            'Paste your ' + label + ' API key'
        }
      />
        <small>Keys entered here stay in backend memory. Use .env to keep your configuration across restarts.</small>
      </label>
      <label>Model<input aria-label="Model" list="models" value={model} onChange={e => setModel(e.target.value)} />
        <datalist id="models">
          {models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
        </datalist>
        <small>
          {
            provider === 'openai' ?
              'Native model ID, such as gpt-6.1-sol.' :
              'Provider/model ID, such as openai/gpt-6.1-sol.'
          }
        </small>
      </label>
      <div className="button-row">
        <button
          className="primary"
          disabled={!!busy}
          onClick={
            async () => {
              const value = await act(
                'settings',
                () => api('/settings/llm', { provider, ...(key ? { key } : {}), model, enabled: true }, 'PUT'),
                'AI settings saved.'
              );
              if (value) setKey('')
            }
          }
        >Save connection</button>
        <button
          disabled={!!busy || !s.configured || !unchangedProvider}
          onClick={() => act('check', () => api('/settings/check', {}), 'Provider connection verified.')}
        >
          {busy === 'check' ? 'Checking…' : 'Check connection'}
        </button>
        <button
          disabled={!!busy || !s.configured || !unchangedProvider}
          onClick={
            async () => {
              const value = await act('models', () => api<{ id: string, name: string }[]>('/settings/models'));
              if (value) setModels(value as { id: string, name: string }[])
            }
          }
        >Load models</button>
      </div>
      <p className="small muted">Check connection makes one small request without customer data. Changing the provider or model prepares
        fresh evidence for your requests.</p>
      <div className="settings-divider" />
      <div className="detail-grid">
        <div><span>Credential source</span><strong>{s.source}</strong></div>
        <div><span>Reported-cost threshold</span><strong>{'$' + s.budget_usd.toFixed(2)}</strong></div>
      </div>
      <p className="small muted">This is a soft threshold, not a billing cap. OpenAI reports tokens without dollar costs, so this threshold
        cannot limit OpenAI spending. Concurrent OpenRouter calls can also exceed it. Set a hard billing limit
        in your provider account.</p>
      {
        metrics &&
        <div className="detail-grid">
          <div><span>Calls recorded</span><strong>{metrics.ai.calls}</strong></div>
          <div>
            <span>Reported inference cost</span>
            <strong>
              {
                metrics.ai.calls === 0 ?
                  'Not measured' :
                  metrics.ai.unknown_cost_calls > 0 && metrics.ai.cost_usd === 0 ?
                    'Unknown' :
                    '$' + metrics.ai.cost_usd.toFixed(5) + (metrics.ai.unknown_cost_calls > 0 ? ' + unknown' : '')
              }
            </strong>
          </div>
          <div>
            <span>p95 latency</span>
            <strong>
              {
                metrics.ai.p95_latency_seconds == null ?
                  'Not measured' :
                  metrics.ai.p95_latency_seconds.toFixed(1) + ' s'
              }
            </strong>
          </div>
          <div><span>Unknown-cost calls</span><strong>{metrics.ai.unknown_cost_calls}</strong></div>
        </div>
      }
      <button
        className="danger-subtle"
        disabled={!!busy}
        onClick={
          () => act(
            'disconnect',
            () => api('/settings/llm', undefined, 'DELETE'),
            'Live AI disabled. Manual review remains available.'
          )
        }
      >Disconnect AI</button>
    </section>
  </>;
}
export function ImportModal({ onClose, act }: { onClose: () => void, act: Act }) {
  const [kind, setKind] = useState('pending'),
    [file, setFile] = useState<File | null>(null),
    [format, setFormat] = useState('DMY'),
    [report, setReport] = useState<ImportReport | null>(null);
  const preview = async () => {
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    form.append('kind', kind);
    form.append('date_format', format);
    const result = await act('import', () => api<ImportReport>('/imports/preview', form));
    if (result) setReport(result as ImportReport)
  };
  return <Modal title="Import refund requests" onClose={onClose}>
    <p>Upload a UTF-8 CSV with the assignment's columns. Preview does not change the queue or create refunds.</p>
    <label>Dataset<select value={kind} onChange={e => { setKind(e.target.value); setReport(null) }}>
      <option value="pending">Incoming requests</option>
      <option value="history">Historical decisions</option>
    </select>
    </label>
    <label className="dropzone">
      <Icon name="upload" size={25} />
      <strong>{file ? file.name : 'Choose a CSV file'}</strong>
      <span>Up to 10 MB · 10,000 rows</span>
      <input
        type="file"
        accept=".csv,text/csv"
        onChange={e => { setFile(e.target.files?.[0] || null); setReport(null) }}
      />
    </label>
    <label>Slash-separated date format<select value={format} onChange={e => { setFormat(e.target.value); setReport(null) }}>
      <option value="DMY">Day / month / year</option>
      <option value="MDY">Month / day / year</option>
    </select>
    </label>
    {
      report &&
      <div className="import-result">
        <h3>{report.row_count} rows · {report.unique_ids} request IDs</h3>
        <p>{report.exact_duplicates} exact duplicates · {report.conflicts.length} conflicting IDs</p>
        {report.conflicts.map(x => <Badge tone="amber" key={x}>{x}</Badge>)}
        <details>
          <summary>Data issues ({report.issues.length})</summary>
          {
            report.issues.map((x, i) => <p key={i}>Row {x.line} · {x.id}: {[...x.errors, ...x.warnings].join('; ')}</p>)
          }
        </details>
        {report.committed && <p>This file was already imported. It will not be paid twice.</p>}
      </div>
    }
    <div className="modal-actions">
      <button onClick={onClose}>Cancel</button>
      <button disabled={!file} onClick={preview}>Preview import</button>
      {
        report &&
        <button
          className="primary"
          onClick={
            async () => {
              if (await act(
                'commit',
                () => api('/imports/' + report.id + '/commit', {}),
                'Import saved. Duplicate protection applied.'
              )) onClose()
            }
          }
        >Commit import</button>
      }
    </div>
  </Modal>
}
