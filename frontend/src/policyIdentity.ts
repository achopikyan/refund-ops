import { useQuery } from '@tanstack/react-query';
import { api } from './components';
import type { PolicyRecord } from './components';

export const policyLabel = (version?: number | null) => version ? `Policy v${version}` : 'Policy version';

export function usePolicyVersions() {
  return useQuery({ queryKey: ['policies', 'manager'], queryFn: () => api<PolicyRecord[]>('/policies') });
}
