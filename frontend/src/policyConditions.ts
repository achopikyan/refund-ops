import { money, words } from './components';
import type { Condition } from './components';

export type ConditionCatalog = Record<string, { label: string, type?: string, unit?: string }>;
export const operators: Record<string, { symbol: string, label: string }> = {
  eq: { symbol: '=', label: 'is' },
  ne: { symbol: '≠', label: 'is not' },
  gt: { symbol: '>', label: 'more than' },
  gte: { symbol: '≥', label: 'at least' },
  lt: { symbol: '<', label: 'less than' },
  lte: { symbol: '≤', label: 'at most' },
  in: { symbol: '∈', label: 'one of' },
};
export const actionLabel: Record<string, string> = {
  auto_approve: 'Propose full refund',
  review: 'Send to reviewer',
  fraud: 'Send to fraud reviewer',
  information: 'Request evidence',
  hold: 'Hold request'
};
export function conditionValue(field: string, value: unknown): string {
  if (value == null) return 'Unknown';
  if (Array.isArray(value)) return value.map(v => conditionValue(field, v)).join(', ');
  if (field === 'amount_cents' && typeof value === 'number') return money(value);
  if (typeof value === 'boolean') return field === 'fraud_flag' ? (value ? 'Flagged' : 'Not flagged') : (value ? 'Yes' : 'No');
  if (value === 'yes' || value === 'no' || value === 'unknown') return value[0].toUpperCase() + value.slice(1);
  return words(String(value));
}
export function conditionText(c: Condition, catalog: ConditionCatalog) {
  return `${catalog[c.field]?.label || words(c.field.replace('facts.', ''))} ${operators[c.op]?.label || c.op} ${conditionValue(c.field, c.value)}`;
}
