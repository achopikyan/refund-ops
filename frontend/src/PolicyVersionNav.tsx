import { UiIcon } from './visualLanguage';
import { policyLabel } from './policyIdentity';
import { VersionStatus, formatDate } from './PolicyVersions';
import { editingLocked } from './policyManagement';
import type { ManagedVersion } from './policyManagement';

const descriptions: Record<string, string> = {
  settings: 'Policy-wide checks, evidence questions and automatic payment limits.',
  rules: 'Read or edit the conditions that determine each route.',
  candidates: 'Find candidate rules in historical records and review their supporting cases.',
  backtest: 'Replay historical requests without making payments. Recorded human decisions are comparison evidence, not guaranteed truth.',
  shadow: 'Observe incoming requests without making payments. Normal reviewer decisions provide independent comparisons.',
  performance: 'See recorded decisions, payments, outcomes and the current queue for this version.',
};

export default function PolicyVersionNav({ version, baseVersion, active, onChange, onBack }: {
  version?: ManagedVersion,
  baseVersion?: ManagedVersion,
  active: string,
  onChange: (view: string) => void,
  onBack: () => void
}) {
  return <header className="policy-version-header">
    <nav className="policy-version-nav" aria-label="Selected policy version">
      <div className="policy-version-identity">
        <button className="text-button policy-library-back" onClick={onBack}>
          <span aria-hidden="true">←</span>All policies</button>
        <span className="policy-header-divider" />
        <h1 className="policy-header-title">
          {version ? policyLabel(version.version) : 'New policy version'}
        </h1>
        {version ? <VersionStatus version={version} /> : <span className="badge">Unsaved</span>}
        {
          version &&
          <div className="policy-header-meta">
            <span>
              <UiIcon name="branch" size={13} />
              {version.data.rules.filter(r => r.enabled).length} of {version.data.rules.length} rules enabled</span>
            <span><UiIcon name="clock" size={13} />Created {formatDate(version.created_at, true)}</span>
            <span>
              <UiIcon name="copy" size={13} />
              {baseVersion ? 'Based on ' + policyLabel(baseVersion.version) : 'No base version'}
            </span>
          </div>
        }
      </div>
      <div className="version-nav-links">
        {
          [
            ['settings', 'settings', 'Settings'],
            ['rules', 'branch', 'Rules'],
            ['candidates', 'spark', 'Discovery'],
            ['backtest', 'test', 'Backtest'],
            ['shadow', 'eye', 'Shadow'],
            ...(version && ['active', 'archived'].includes(version.status) ?
              [['performance', 'chart', 'Performance']] :
              [])
          ].map(([id, icon, label]) => {
            const currentShadow = id === 'shadow' && (version?.stage === 'current' || version?.status === 'active');
            const disabled = currentShadow || (!version ? id !== 'rules' : id === 'candidates' && editingLocked(version));
            return <button
              key={id}
              disabled={disabled}
              title={
                currentShadow ?
                  'Current is already serving requests and cannot run in Shadow.' :
                  disabled ?
                    version ?
                      'This version is locked. Create a new version from Policies to change or discover rules.' :
                      'Save this new version first.' :
                    descriptions[id]
              }
              className={active === id ? 'selected' : ''}
              aria-current={active === id ? 'page' : undefined}
              onClick={() => onChange(id)}
            >
              <UiIcon name={icon} size={16} />
              {label}
            </button>;
          })
        }
      </div>
    </nav>
  </header>;
}
