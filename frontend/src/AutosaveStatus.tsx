import { UiIcon } from './visualLanguage';
export default function AutosaveStatus({ state }: { state: { status: string, error: string, locked: boolean, retry: () => void, reload: () => void } }) {
  if (state.locked) return null;
  return <div className={'autosave-status ' + (state.error ? 'has-error' : '')} role="status">
    <span>
      <UiIcon name={state.status === 'saved' ? 'check' : state.error ? 'warning' : 'clock'} size={15} />
      {
        state.status === 'saved' ?
          'Saved' :
          state.status === 'saving' || state.status === 'waiting' ?
            'Saving…' :
            state.status === 'invalid' ? 'Incomplete changes' : 'Could not save'
      }
    </span>
    {state.error && <small>{state.error}</small>}
    {state.status === 'error' && <button onClick={state.retry}>Retry</button>}
    {state.status === 'conflict' && <button onClick={state.reload}>Reload saved version</button>}
  </div>;
}
