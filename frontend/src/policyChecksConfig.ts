import type { ExecutionLimits } from './components';

export const defaultExecutionLimits: ExecutionLimits = {
  max_single_cents: 10000,
  daily_cents: 50000,
  customer_daily_cents: 20000,
  release_cents: 100000,
  release_count: 100
};
export const executionFields: [keyof ExecutionLimits, string, string][] = [
  ['max_single_cents', 'Maximum automatic refund', 'One automatic payment exceeds this amount'],
  [
    'daily_cents',
    'Daily automatic budget',
    'Total automatic payments across versions exceed this amount in a UTC day'
  ],
  [
    'customer_daily_cents',
    'Customer daily budget',
    'Automatic refunds to one customer exceed this amount in a UTC day'
  ],
  [
    'release_cents',
    'Version lifetime budget',
    'Total automatic payments by this version exceed this amount'
  ],
  [
    'release_count',
    'Version operation limit',
    'The next payment exceeds this version’s operation count'
  ],
];

export type FixedCheck = [string, string, string, string?];
export const dataChecks: FixedCheck[] = [
  ['Conflicting request versions', 'Different source versions have not been reconciled', 'Review'],
  ['Invalid source data', 'Required fields are missing or invalid', 'Review · request information'],
  [
    'Possible previous refund',
    'Source notes report that a refund was already made',
    'Review',
    'previous_refund'
  ],
  [
    'Untrusted instructions',
    'Source notes attempt to instruct or override the system',
    'Review',
    'untrusted_instructions'
  ],
  ['Payment risk', 'Payment is flagged without explicit fraud-team confirmation', 'Fraud Review'],
  [
    'Reported fraud',
    'Notes report fraud even when the structured payment flag is clear',
    'Fraud Review',
    'fraud_reports'
  ],
  [
    'Customer data consistency',
    'Tenure contradicts an earlier request from the same customer',
    'Review',
    'customer_history'
  ],
];
export const businessChecks: FixedCheck[] = [
  [
    'Wrong-item contradiction',
    'Customer selected wrong item, but staff confirms it matches the order',
    'Review',
    'item_mismatch'
  ],
  [
    'Damage origin',
    'Damage occurred after delivery, or notes say the product is undamaged',
    'Review',
    'damage_origin'
  ],
  [
    'Refund reason consistency',
    'Use the reason established from the entire request context; review unresolved contradictions',
    'Review',
    'reason_consistency'
  ],
  [
    'Cosmetic damage',
    'A damage claim may require a partial refund',
    'Review · choose amount',
    'cosmetic_damage'
  ],
  [
    'Part of order damaged',
    'Only some items in the order or set are damaged',
    'Review · choose amount',
    'partial_damage'
  ],
  [
    'Late delivery',
    'Delivery is late, or a never-arrived claim is contradicted by delivery evidence',
    'Review',
    'late_delivery'
  ],
  [
    'Delivery proof',
    'Delivery proof exists without a confirmed carrier investigation',
    'Review',
    'delivery_proof'
  ],
  ['Evidence-led judgment', 'Never arrived or wrong item has no applicable explicit rule', 'Review'],
  [
    'Confirmed full-refund obligation',
    'Fraud-team-confirmed stolen card or confirmed merchant error',
    'Full refund to original payment method; all integrity and execution checks still apply'
  ],
];
export const approvalChecks: FixedCheck[] = [
  [
    'Complete request evidence',
    'Require completed model evidence extraction before automatic approval',
    'Review',
    'evidence_analysis'
  ],
  [
    'Uncleared payment risk',
    'An automatic approval has unknown or flagged risk without fraud-team confirmation',
    'Fraud Review'
  ],
  [
    'Policy qualification',
    'Automation is not enabled for this policy; release qualification is required before execution',
    'Review / block automatic execution'
  ],
  ['Conflicting rule outcomes', 'Top-priority applicable rules request different actions', 'Review'],
  [
    'Unknown restrictive condition',
    'A potentially applicable restrictive rule has missing inputs',
    'Review'
  ],
  ['No matching rule', 'No rule determines an outcome', 'Review'],
  [
    'Payment integrity',
    'Request is already decided, changed since review, or held',
    'Block payment until resolved'
  ],
  [
    'Business obligations at payment',
    'A reviewer attempts payment despite unresolved duplicate refund, fraud, return window, required photo or delivery-proof restriction',
    'Block payment; verify or correct the evidence first'
  ],
  [
    'Repeated payment operation',
    'The same payment operation is submitted again',
    'Return its recorded result; no second payment'
  ],
];
