import { useQuery } from '@tanstack/react-query';
import { api } from './components';
import { UiIcon } from './visualLanguage';

export type HistoryAnalysisStatus = {
  ready: boolean;
  complete_requests: number;
  requests: number;
  model: string;
  completed: number;
  total: number;
  running: number;
  pending: number;
  failed: number;
  unavailable: number;
  failures: { id: string; message: string }[];
  provider_issue?: { retry_at: number; message: string } | null;
};
export default function HistoricalAnalysis({ analysis }: { analysis?: HistoryAnalysisStatus }) {
  const query = useQuery({
    queryKey: ['history-analysis'],
    queryFn: () => api<HistoryAnalysisStatus>('/history-analysis'),
    refetchInterval: 3000,
    enabled: !analysis
  });
  const a = analysis || query.data;
  if (!a) return null;
  const issue = a.provider_issue && a.provider_issue.retry_at * 1000 > Date.now() ? a.provider_issue : null;
  const attention = !!issue || a.failed > 0 || a.unavailable > 0;
  return <section
    className={'analysis-progress ' + (a.ready ? 'is-passed' : attention ? 'needs-attention' : 'is-running')}
    role="status"
  >
    <UiIcon name={a.ready ? 'check' : 'spark'} />
    <div>
      <strong>{a.ready ? 'Historical evidence saved' : 'Preparing full historical evidence'}</strong>
      <p>
        {a.complete_requests}/{a.requests} requests · {a.model}. {
          a.ready ?
            'Validated extraction is saved and reused across policy comparisons.' :
            'Analysis runs automatically. Completed work survives restarts; Backtest waits for all requested evidence.'
        }
      </p>
      {
        !a.ready &&
        <div className="preparation-progress">
          <label>Saved extractions <span>{a.completed}/{a.total}</span>
            <progress value={a.completed} max={a.total || 1} />
          </label>
          <p>{a.running} running · {a.pending} pending · {a.failed} need attention</p>
        </div>
      }
      {issue && <p>{issue.message}</p>}
      {a.unavailable > 0 && <p>Configure the AI connection in Settings to continue automatically.</p>}
      {
        a.failures.length > 0 &&
        <details>
          <summary>Requests needing attention ({a.failures.length})</summary>
          {a.failures.map((f, i) => <p key={f.id + i}>{f.id}: {f.message}</p>)}
        </details>
      }
    </div>
  </section>;
}
