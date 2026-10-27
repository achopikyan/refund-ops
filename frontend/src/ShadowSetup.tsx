import AutomaticSettingsForm from './AutomaticSettingsForm';
import type { NumericField } from './AutomaticSettingsForm';
import { configGroups } from './policySettingsFields';

export default function ShadowSetup({ trial, onPending }: {
  trial: { id: string; status: string; settings: Record<string, number> },
  onPending?: (value: boolean) => void
}) {
  const fields = configGroups[0][1] as NumericField[];
  const initial = Object.fromEntries(fields.map(([key]) => [key, trial.settings[key]]));
  return <section className="panel padded">
    <h2>Shadow requirements</h2>
    <p>Observe requests without executing refunds. Choose your minimum sample and maximum exposure below; these
      requirements lock when Shadow starts. Only new arrivals first seen after that point can support release.
      Repeated requests from one customer count as one group for the uncertainty estimate.</p>
    <AutomaticSettingsForm
      key={trial.id + trial.status}
      path={'/trials/' + trial.id + '/shadow-settings'}
      initial={initial}
      fields={fields}
      readOnly={trial.status !== 'backtested' && trial.status !== 'draft'}
      onPending={onPending}
    />
  </section>;
}
