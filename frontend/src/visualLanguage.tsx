/** Shared visual vocabulary: color has a meaning, and every marker has text. */
export const uiIconPaths: Record<string, string> = {
  queue: 'M8 6h13M8 12h13M8 18h13M3 6h1M3 12h1M3 18h1',
  info: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M12 10v7M12 7v.01',
  target: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10M12 11v2',
  chart: 'M4 3v17h17M8 16v-5M13 16V7M18 16V4',
  download: 'M12 3v12M7 10l5 5 5-5M4 16v5h16v-5',
  trash: 'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7',
  plus: 'M12 5v14M5 12h14',
  search: 'M10 4a6 6 0 1 0 0 12 6 6 0 0 0 0-12m5 11 5 5',
  settings: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8m0-5v3m0 12v3M3 12h3m12 0h3M6 6l2 2m8 8 2 2M6 18l2-2m8-8 2-2',
  money: 'M3 6h18v12H3zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6M6 9v.01M18 15v.01',
  photo: 'M3 6h5l2-2h4l2 2h5v14H3zM12 9a4 4 0 1 0 0 8 4 4 0 0 0 0-8',
  file: 'M5 3h9l5 5v13H5zM14 3v6h5M8 13h8M8 17h5',
  truck: 'M2 6h12v11H2zM14 10h4l4 4v3h-8M5 17a2 2 0 1 0 0 4 2 2 0 0 0 0-4M18 17a2 2 0 1 0 0 4 2 2 0 0 0 0-4',
  clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M12 7v5l3 2',
  history: 'M3 5v5h5M3 10a9 9 0 1 1 1 8M12 7v5l3 2',
  copy: 'M8 8h12v13H8zM16 8V3H3v13h5',
  split: 'M12 21v-8M5 3v5l7 5 7-5V3M2 6l3-3 3 3M16 6l3-3 3 3',
  warning: 'M12 3 2 21h20L12 3zM12 9v5M12 17v.1',
  shield: 'M12 3l8 4v5c0 5-8 9-8 9S4 17 4 12V7l8-4M12 8v5M12 16v.1',
  lock: 'M5 10h14v11H5zM8 10V7a4 4 0 0 1 8 0v3M12 14v3',
  card: 'M3 5h18v14H3zM3 9h18M6 15h4',
  calendar: 'M3 5h18v16H3zM7 3v4M17 3v4M3 10h18M8 14h2M14 17h2',
  partial: 'M12 3a9 9 0 1 0 9 9H12V3zM15 3v6h6',
  box: 'M3 7l9-4 9 4v10l-9 4-9-4V7zM3 7l9 4 9-4M12 11v10M7 5l10 4',
  question: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M9 9a3 3 0 1 1 5 2c-1 1-2 1-2 3M12 17v.1',
  eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6',
  branch: 'M5 3v14a3 3 0 0 0 3 3h8M5 7h8a4 4 0 0 0 4-4M14 17l3 3-3 3',
  spark: 'M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3',
  pause: 'M7 4h3v16H7zM14 4h3v16h-3z',
  check: 'M5 12l4 4L19 6',
  user: 'M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8M4 21v-2a8 8 0 0 1 16 0v2',
  edit: 'M4 15 16 3l5 5L9 20l-6 1 1-6zM13 6l5 5',
  tag: 'M3 3h8l10 10-8 8L3 11V3zM7 7h.01',
  database: 'M3 6a9 3 0 1 0 18 0 9 3 0 1 0-18 0M3 6v12a9 3 0 0 0 18 0V6M3 12a9 3 0 0 0 18 0',
  test: 'M9 3h6M10 3v7L4 20h16l-6-10V3M7 15h10',
  rocket: 'M8 16l-4 4M9 15l-5-1 4-5 3 1M9 15l5 5 1-5M9 15c0-7 6-12 12-12 0 6-5 12-12 12zM16 7h.01',
  arrow: 'M5 12h14m-5-5 5 5-5 5',
};
export function UiIcon({ name, size = 18 }: { name: string, size?: number }) {
  return <svg
    className="ui-icon"
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.7"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d={uiIconPaths[name] || uiIconPaths.tag} />
  </svg>
}
type Style = { tone: string, icon: string };
export const reasonStyles: Record<string, Style> = {
  execution_check: { tone: 'amber', icon: 'shield' },
  partial_damage: { tone: 'amber', icon: 'partial' },
  no_product_damage: { tone: 'orange', icon: 'box' },
  batch_defect: { tone: 'blue', icon: 'box' },
  carrier_incident: { tone: 'orange', icon: 'truck' },
  verified_damage: { tone: 'teal', icon: 'photo' },
  simple_return: { tone: 'teal', icon: 'check' },
  customer_history_conflict: { tone: 'orange', icon: 'user' },
  conflicting_rule_actions: { tone: 'orange', icon: 'split' },
  high_value: { tone: 'amber', icon: 'money' },
  photo_required: { tone: 'blue', icon: 'photo' },
  analysis_incomplete: { tone: 'blue', icon: 'file' },
  delivery_proof: { tone: 'orange', icon: 'truck' },
  late_delivery_judgment: { tone: 'orange', icon: 'clock' },
  repeat_requests: { tone: 'amber', icon: 'history' },
  possible_previous_refund: { tone: 'red', icon: 'copy' },
  conflicting_versions: { tone: 'orange', icon: 'split' },
  conflicting_evidence: { tone: 'orange', icon: 'warning' },
  reason_conflict: { tone: 'orange', icon: 'tag' },
  invalid_data: { tone: 'orange', icon: 'database' },
  untrusted_instruction: { tone: 'red', icon: 'lock' },
  fraud_confirmation_required: { tone: 'red', icon: 'shield' },
  fraud_not_cleared: { tone: 'red', icon: 'card' },
  fraud_unknown: { tone: 'red', icon: 'question' },
  return_window: { tone: 'amber', icon: 'calendar' },
  partial_judgment: { tone: 'amber', icon: 'partial' },
  damage_origin: { tone: 'blue', icon: 'box' },
  unknown_rule_input: { tone: 'blue', icon: 'question' },
  evidence_judgment: { tone: 'blue', icon: 'eye' },
  outside_automation: { tone: 'purple', icon: 'branch' },
  setup_required: { tone: 'purple', icon: 'test' },
  policy_hold: { tone: 'purple', icon: 'pause' },
  confirmed_stolen_card: { tone: 'teal', icon: 'shield' },
  confirmed_merchant_error: { tone: 'teal', icon: 'box' },
  policy_rule: { tone: 'slate', icon: 'check' },
  small_established_customer: { tone: 'teal', icon: 'user' },
};
export const actionStyles: Record<string, Style & { label: string }> = {
  auto_approve: { tone: 'teal', icon: 'check', label: 'Auto Approve' },
  review: { tone: 'amber', icon: 'user', label: 'Review' },
  fraud: { tone: 'red', icon: 'shield', label: 'Fraud Review' },
  information: { tone: 'blue', icon: 'file', label: 'Review' },
  hold: { tone: 'purple', icon: 'pause', label: 'Review' },
};
export function ActionTag({ action, route = false }: { action: string, route?: boolean }) {
  const a = actionStyles[action] || actionStyles.review;
  return <span className={'semantic-tag tone-' + a.tone}>
    <UiIcon name={a.icon} size={15} />
    {
      route ?
        (action === 'auto_approve' ? 'Auto Approve' : action === 'fraud' ? 'Fraud Review' : 'Review') :
        a.label
    }
  </span>
}
export function fieldStyle(field: string): Style {
  if (field === 'amount_cents') return { tone: 'teal', icon: 'money' };
  if (field.includes('fraud')) return { tone: 'red', icon: 'shield' };
  if (field === 'tenure_months') return { tone: 'blue', icon: 'user' };
  if (field === 'prior_refunds_12m') return { tone: 'amber', icon: 'history' };
  if (field === 'days_since_delivery') return { tone: 'orange', icon: 'calendar' };
  if (field === 'payment_method') return { tone: 'purple', icon: 'card' };
  if (field === 'category') return { tone: 'purple', icon: 'box' };
  if (field.startsWith('facts.')) return { tone: 'blue', icon: 'file' };
  return { tone: 'slate', icon: 'tag' };
}
export function StageTag({ stage }: { stage: string }) {
  const s: Record<string, Style> = {
    draft: { tone: 'slate', icon: 'edit' },
    backtested: { tone: 'blue', icon: 'test' },
    shadow: { tone: 'purple', icon: 'eye' },
    active: { tone: 'teal', icon: 'check' },
    archived: { tone: 'slate', icon: 'history' },
    stopped: { tone: 'red', icon: 'pause' }
  };
  const v = s[stage] || s.draft;
  return <span className={'semantic-tag tone-' + v.tone}>
    <UiIcon name={v.icon} size={15} />
    {
      stage === 'active' ? 'Current' : stage.charAt(0).toUpperCase() + stage.slice(1).replaceAll('_', ' ')
    }
  </span>
}
