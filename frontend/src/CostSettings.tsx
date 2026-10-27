import { useQuery } from '@tanstack/react-query';
import { api } from './components';
import AutomaticSettingsForm from './AutomaticSettingsForm';
import { configGroups } from './policySettingsFields';
import type { NumericField } from './AutomaticSettingsForm';

export default function CostSettings() {
  const { data, error } = useQuery({ queryKey: ['cost-assumptions'], queryFn: () => api<Record<string, number>>('/settings/costs') });
  return <section className="panel padded">
    <h2>Cost assumptions</h2>
    <p>Defaults for new policy checks. Existing Backtest and Shadow runs keep their original assumptions.</p>
    {error && <p className="alert error">{(error as Error).message}</p>}
    {
      data &&
      <AutomaticSettingsForm
        path="/settings/costs"
        initial={data}
        fields={configGroups[1][1] as NumericField[]}
      />
    }
  </section>;
}
