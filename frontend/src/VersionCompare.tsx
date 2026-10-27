import HistoricalAnalysis from './HistoricalAnalysis';
import { ComparisonEvidence } from './DecisionReport';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, PageHeading, Empty } from './components';
import { UiIcon } from './visualLanguage';
import { policyLabel } from './policyIdentity';
import { usePolicyLibrary } from './policyManagement';
import { VersionStatus } from './PolicyVersions';

export default function VersionCompare({ initialId, onOpen }: { initialId: string | null, onOpen: (id: string) => void }) {
  const library = usePolicyLibrary();
  const [selected, setSelected] = useState<string[]>(initialId ? [initialId] : []),
    [mode, setMode] = useState('backtest');
  const current = library.data?.versions.find(v => v.id === library.data.current_id);
  const ids = selected.filter(id => id !== current?.id);
  const query = useQuery({
    queryKey: ['version-comparison', mode, ...ids],
    queryFn: () => api<any>('/policy-comparisons/' + mode + '?policy_ids=' + encodeURIComponent(ids.join(','))),
    enabled: !!current && ids.length > 0,
    refetchInterval: mode === 'shadow' ? 5000 : 3000
  });
  const data = query.data;
  const toggle = (id: string) => setSelected(prev => prev.includes(id) ? prev.filter(x => x !== id) : prev.length < 5 ? [...prev, id] : prev);
  return <>
    <PageHeading
      title="Compare versions"
      text="Choose versions, then compare their decisions against Current on the same requests."
    />
    {library.error && <div className="alert error">{(library.error as Error).message}</div>}
    <section className="manager-section manager-blue">
      <div className="manager-section-title">
        <span className="manager-icon"><UiIcon name="split" /></span>
        <div>
          <h2>Versions to compare</h2>
          <p>Current is always included. Add up to five saved versions.</p>
        </div>
      </div>
      <div className="comparison-picker">
        {
          current &&
          <div className="version-choice pinned">
            <UiIcon name="lock" />
            <strong>{policyLabel(current.version)}</strong>
            <span>Current</span>
          </div>
        }
        {
          library.data?.versions.filter(v => v.id !== current?.id).map(v => <label className={'version-choice ' + (ids.includes(v.id) ? 'chosen' : '')} key={v.id}>
            <input
              type="checkbox"
              checked={ids.includes(v.id)}
              disabled={ids.length >= 5 && !ids.includes(v.id)}
              onChange={() => toggle(v.id)}
            />
            <strong>{policyLabel(v.version)}</strong>
            <VersionStatus version={v} />
          </label>)
        }
      </div>
      <p className="small muted">
        {
          mode === 'shadow' ?
            'Every selected Shadow version observes the same cases. Reviewer decisions update results automatically; reviewers never see Shadow recommendations.' :
            'Versions use the same request-time data and saved evidence. Recorded decisions and outcomes are comparison context only.'
        }
      </p>
      {
        library.data?.versions.length === 1 &&
        <p>Create and save another version in Policies to compare its behavior.</p>
      }
    </section>
    {mode === 'backtest' && <HistoricalAnalysis analysis={data?.analysis} />}
    <div className="comparison-modes" aria-label="Comparison mode">
      {
        [
          ['backtest', 'test', 'Backtest', 'Replay the same historical records'],
          ['shadow', 'eye', 'Shadow', 'Observe the same operational requests']
        ].map(([id, icon, label, detail]) => <button
          key={id}
          className={mode === id ? 'selected' : ''}
          aria-pressed={mode === id}
          onClick={() => setMode(id)}
        >
          <UiIcon name={icon} size={23} />
          <span><strong>{label}</strong><small>{detail}</small></span>
        </button>)
      }
    </div>
    {
      !ids.length ?
        <Empty
          title="Select versions to compare"
          detail="Use the version cards above. Current remains the reference in every comparison."
        /> :
        query.isPending ?
          <p role="status">Preparing the same request pool for every selected version…</p> :
          query.error ?
            <div className="alert error">
              {(query.error as Error).message}
              <button onClick={() => void query.refetch()}>Retry comparison</button>
            </div> :
            data?.preparing ?
              <section className="panel padded">
                <h2>Comparison will appear automatically</h2>
                <p>All historical requests must have current, validated evidence before comparing policies. No partial
                  result is shown as a finished backtest.</p>
              </section> :
              data &&
              <>
                {
                  data.versions.filter((v: any) => !v.available).map((v: any) => <div className="comparison-unavailable" key={v.policy_id}>
                    <UiIcon name="warning" />
                    <div>
                      <strong>
                        {policyLabel(v.version)} is unavailable in {mode === 'shadow' ? 'Shadow' : 'Backtest'}
                      </strong>
                      <p>{v.reason}</p>
                    </div>
                    <button onClick={() => onOpen(v.policy_id)}>Open version</button>
                  </div>)
                }
                <ComparisonEvidence key={mode + ids.join()} data={data} />
                <details className="manager-section manager-slate">
                  <summary>How to read this comparison</summary>
                  {data.limitations?.map((note: string) => <p className="small muted" key={note}>{note}</p>)}
                  <p className="small muted">This comparison does not qualify a release. Each version keeps its own Backtest and Shadow requirements
                    for new arrivals.</p>
                </details>
              </>
    }
  </>;
}
