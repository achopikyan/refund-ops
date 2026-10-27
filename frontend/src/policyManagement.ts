import { useQuery } from '@tanstack/react-query';
import { api } from './components';
import type { PolicyRecord } from './components';

export type ManagedVersion = PolicyRecord & {
  stage: string;
  stale?: boolean;
  checks_id: string | null;
  readiness: { passed: boolean, blockers: string[] };
  can_rollback: boolean;
  qualification?: { passed: boolean, warnings: string[] };
};
export type PolicyLibrary = {
  current_id: string,
  versions: ManagedVersion[],
  history: {
    type: string,
    created_at: string,
    from_version: number | null,
    to_version: number | null,
    reason: string
  }[]
};
export function usePolicyLibrary(enabled = true) {
  return useQuery({
    enabled,
    queryKey: ['policy-library'],
    queryFn: () => api<PolicyLibrary>('/policy-versions'),
    refetchInterval: 5000
  });
}
export const stageLabel = (v: ManagedVersion) => v.stage === 'current' ?
  'Current' :
  v.stage === 'shadow' && v.readiness.passed ?
    'Ready to activate' :
    v.stage.charAt(0).toUpperCase() + v.stage.slice(1);
export function nextStep(v: ManagedVersion) {
  if (v.stale) return 'Backtest results are being updated automatically';
  if (v.stage === 'current') return 'Serving the review workflow';
  if (v.stage === 'archived') return 'Previously current. Available for rollback';
  if (v.stage === 'stopped') return 'Checks stopped. Create a new version to continue';
  if (v.readiness.passed) return 'Checks passed. Ready for your release decision';
  if (v.stage === 'backtested') return 'Review Backtest results, then start Shadow manually';
  if (v.stage === 'shadow') return 'Observing requests. Open checks for release requirements';
  return v.checks_id ?
    'Open checks to continue validation' :
    'Run Backtest, then choose when to start Shadow';
}

export const editingLocked = (version: ManagedVersion) => version.stage !== 'draft';
