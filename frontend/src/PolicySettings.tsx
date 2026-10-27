import { UiIcon } from './visualLanguage';
import PolicyWideChecks from './PolicyWideChecks';
import type { ManagedVersion } from './policyManagement';

export default function PolicySettings({ version: v, onRollback, workspaceKey }: {
  version: ManagedVersion,
  onRollback: () => void,
  workspaceKey: string
}) {
  return <>

    <PolicyWideChecks version={v} workspaceKey={workspaceKey} />
    {
      v.can_rollback &&
      <details className="panel padded" open>
        <summary>Rollback options</summary>
        <p>Preview the effect of restoring this previously current version. Existing decisions and payments remain
          unchanged.</p>
        <button onClick={onRollback}><UiIcon name="history" />Rollback to this version</button>
      </details>
    }
  </>;
}
