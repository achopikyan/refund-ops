import { defaultExecutionLimits } from './policyChecksConfig';
import type { Policy, PolicyRecord, Rule } from './components';

export type RuleCandidate = {
  id: string,
  rule: Rule,
  training: any,
  later_diagnostic: any,
  support_ids: string[],
  scenario_net_cents: number
};
export type Discovery = {
  id: string,
  base_id: string,
  base_hash?: string,
  candidates: RuleCandidate[],
  excluded_existing: number,
  training_count: number,
  later_count: number,
  assumptions: { hourly_cost_cents: number, hypothetical_error_bps: number },
  limitations: string[]
};
export type WorkingCopy = { policy: Policy, discovery: Discovery | null, basePolicy?: Policy };
const policyContent = (p: Policy) => Object.fromEntries(Object.entries(p).filter(([key]) => ![
  'description',
  'small_customer_enabled',
  'small_amount_cents',
  'minimum_tenure',
  'maximum_prior_refunds'
].includes(key))) as Policy;
export function samePolicy(a: Policy, b: Policy) {
  const stable = (p: Policy) => JSON.stringify(
    p,
    (_, v) => v && typeof v === 'object' && !Array.isArray(v) ?
      Object.fromEntries(Object.entries(v).sort(([a], [b]) => a.localeCompare(b))) :
      v
  );
  return stable(policyContent(a)) === stable(policyContent(b));
}
export const scratchId = 'new-from-scratch';
export function blankPolicy(): PolicyRecord {
  return {
    id: scratchId,
    name: 'Policy version',
    status: 'draft',
    parent_id: null,
    created_at: '',
    data: {
      name: 'Policy version',
      rules: [],
      criteria: [],
      execution_limits: { ...defaultExecutionLimits },
      automation_enabled: true,
      change_mind_days: 14,
      damage_photo_above_cents: 5000
    }
  };
}
export const workingCopyKey = (workspace: string, baseId: string, isNew = false) => 'refund-policy-composer:' + workspace + ':' + baseId + (isNew ? ':new' : '');
export const discoveryKey = (workspace: string, baseId: string) => 'refund-rule-candidates:' + workspace + ':' + baseId;
export function readWorkingCopy(workspace: string, base: PolicyRecord, isNew = false): WorkingCopy {
  try {
    const saved = JSON.parse(localStorage.getItem(workingCopyKey(workspace, base.id, isNew)) || 'null');
    if (saved?.policy?.rules && Array.isArray(saved.policy.rules)) return {
      ...saved,
      policy: policyContent(saved.policy),
      basePolicy: policyContent(saved.basePolicy || structuredClone(base.data))
    }
  } catch { }
  return {
    policy: {
      ...policyContent(structuredClone(base.data)),
      execution_limits: structuredClone(base.data.execution_limits || base.execution_limits || defaultExecutionLimits),
      name: 'Policy version',
      automation_enabled: true
    },
    discovery: null,
    basePolicy: policyContent(structuredClone(base.data))
  };
}
export function includedCandidates(work: WorkingCopy) {
  return work.discovery?.candidates.filter(c => work.policy.rules.some(r => r.id === c.rule.id)) ?? []
}
export function readDiscovery(workspace: string, base: PolicyRecord): Discovery | null {
  const work = readWorkingCopy(workspace, base);
  if (includedCandidates(work).length) return work.discovery;
  try {
    const saved = JSON.parse(localStorage.getItem(discoveryKey(workspace, base.id)) || 'null');
    if (saved?.base_id === base.id && (!base.hash || saved.base_hash === base.hash) &&
      Array.isArray(saved.candidates)) return saved
  } catch { }
  return work.discovery;
}
