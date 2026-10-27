import { useEffect, useSyncExternalStore } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from './components';
import type { Policy, PolicyRecord } from './components';
import type { ManagedVersion } from './policyManagement';
import { editingLocked } from './policyManagement';
import { readWorkingCopy, workingCopyKey, samePolicy, includedCandidates } from './policyWorkingCopy';
import type { WorkingCopy } from './policyWorkingCopy';

type State = {
  policy: Policy,
  status: 'saved' | 'waiting' | 'saving' | 'invalid' | 'error' | 'conflict',
  error: string,
  locked: boolean
};
function complete(p: Policy) {
  return p.rules.every(r => r.name.trim() && r.conditions.length > 0 && r.conditions.every(c => c.value !== '')) &&
    p.criteria.every(c => c.question.trim() && /^[a-z][a-z0-9_-]{0,49}$/.test(c.id) && c.sources.length > 0) &&
    (!p.execution_limits || Object.values(p.execution_limits).every(v => Number.isInteger(v) && v > 0));
}
class DraftSession {
  state: State; work: WorkingCopy; timer: ReturnType<typeof setTimeout> | null = null; running = false; listeners = new Set<() => void>();
  constructor(public key: string, public version: ManagedVersion, workspace: string) {
    this.work = readWorkingCopy(workspace, version);
    let restored = false;
    try { restored = !!localStorage.getItem(key) } catch { }
    if (editingLocked(version)) this.work = {
      policy: structuredClone(version.data),
      basePolicy: structuredClone(version.data),
      discovery: null
    };
    this.state = { policy: this.work.policy, status: 'saved', error: '', locked: editingLocked(version) };
    if (restored && !samePolicy(this.work.policy, this.work.basePolicy || version.data) &&
      !this.state.locked) {
      if (!samePolicy(this.work.basePolicy || version.data, version.data)) this.state = {
        ...this.state,
        status: 'conflict',
        error: 'This version changed while local edits were pending. Reload the saved version to continue.'
      };
      else this.change(this.work.policy);
    }
  }
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } };
  snapshot = () => this.state;
  emit(patch: Partial<State>) { this.state = { ...this.state, ...patch }; this.listeners.forEach(f => f()) }
  persist() {
    try {
      if (this.state.status === 'saved') localStorage.removeItem(this.key); else localStorage.setItem(this.key, JSON.stringify(this.work))
    } catch {
      this.emit({ error: 'Browser backup is unavailable. Keep this page open until changes are saved.' })
    }
  }
  sync(version: ManagedVersion) {
    this.version = version;
    const locked = editingLocked(version);
    if (locked !== this.state.locked) this.emit({ locked });
    if (locked) {
      if (this.timer) clearTimeout(this.timer);
      if (!samePolicy(this.state.policy, version.data)) this.emit({ policy: structuredClone(version.data) });
      return
    }
    if (this.running || samePolicy(version.data, this.work.basePolicy || version.data)) return;
    if (this.state.status !== 'saved') {
      this.emit({
        status: 'conflict',
        error: 'This policy changed elsewhere. Your local edits are kept; reload the saved version before continuing.'
      });
      return
    }
    this.work = {
      policy: structuredClone(version.data),
      basePolicy: structuredClone(version.data),
      discovery: null
    };
    this.emit({ policy: this.work.policy });
  }
  change = (policy: Policy) => {
    if (this.state.locked) return;
    this.work = { ...this.work, policy };
    if (this.state.status === 'conflict') { this.emit({ policy }); this.persist(); return }
    const valid = complete(policy);
    this.emit({
      policy,
      status: valid ? 'waiting' : 'invalid',
      error: valid ? '' : 'Complete the unfinished fields to save automatically.'
    });
    this.persist();
    if (this.timer) clearTimeout(this.timer);
    if (valid) this.timer = setTimeout(() => { void this.save() }, 650);
  };
  save = async () => {
    if (this.running || this.state.locked || !['waiting', 'error'].includes(this.state.status) ||
      !complete(this.work.policy)) return;
    this.running = true;
    const payload = structuredClone(this.work.policy),
      expected = this.work.basePolicy || this.version.data;
    const selected = includedCandidates(this.work), report = this.work.discovery;
    this.emit({ status: 'saving', error: '' });
    try {
      const result = await (selected.length && report ?
        api<PolicyRecord>(
          '/rule-discovery/' + report.id + '/draft',
          {
            candidate_ids: selected.map(c => c.id),
            policy: payload,
            target_id: this.version.id,
            expected_policy: expected
          }
        ) :
        api<PolicyRecord>(
          '/policies/' + this.version.id + '/draft',
          { policy: payload, expected_policy: expected },
          'PUT'
        ));
      const furtherEdits = !samePolicy(this.work.policy, payload);
      this.work = {
        policy: furtherEdits ? this.work.policy : result.data,
        basePolicy: structuredClone(result.data),
        discovery: null
      };
      this.emit({
        policy: this.work.policy,
        status: furtherEdits ? (complete(this.work.policy) ? 'waiting' : 'invalid') : 'saved'
      });
      this.persist();
      this.onSaved?.();
    } catch (e) {
      const error = (e as Error).message;
      this.emit({ status: /changed|locked|checks have started/i.test(error) ? 'conflict' : 'error', error });
      this.persist()
    }
    finally {
      this.running = false;
      if (this.state.status === 'waiting') this.timer = setTimeout(() => { void this.save() }, 650)
    }
  };
  onSaved?: () => void;
  reload = () => {
    if (this.running) return;
    this.work = {
      policy: structuredClone(this.version.data),
      basePolicy: structuredClone(this.version.data),
      discovery: null
    };
    this.emit({ policy: this.work.policy, status: 'saved', error: '' });
    this.persist()
  };
}
const sessions = new Map<string, DraftSession>();
export async function flushPolicyDraft(workspace: string, version: ManagedVersion): Promise<Policy | null> {
  const session = sessions.get(workingCopyKey(workspace, version.id));
  if (!session) return version.data;
  if (session.timer) clearTimeout(session.timer);
  while (session.running) await new Promise(resolve => setTimeout(resolve, 20));
  if (session.state.status === 'waiting') await session.save();
  return session.state.status === 'saved' || session.state.locked ?
    session.work.basePolicy || version.data :
    null;
}
export function usePolicyAutosave(version: ManagedVersion, workspace: string) {
  const key = workingCopyKey(workspace, version.id), qc = useQueryClient();
  let session = sessions.get(key);
  if (!session) { session = new DraftSession(key, version, workspace); sessions.set(key, session) }
  session.onSaved = () => { void qc.invalidateQueries() };
  const state = useSyncExternalStore(session.subscribe, session.snapshot);
  useEffect(() => { session.sync(version) }, [session, version]);
  return { ...state, change: session.change, retry: session.save, reload: session.reload };
}
