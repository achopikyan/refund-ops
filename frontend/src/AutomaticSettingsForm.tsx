import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api, money } from './components';
import { UiIcon } from './visualLanguage';

export type NumericField = [string, string, 'dollars' | 'percent' | undefined];
export default function AutomaticSettingsForm({ path, initial, fields, readOnly = false, onPending }: {
  path: string,
  initial: Record<string, number>,
  fields: NumericField[],
  readOnly?: boolean,
  onPending?: (pending: boolean) => void
}) {
  const qc = useQueryClient(),
    [values, setValues] = useState(initial),
    [status, setStatus] = useState('saved'),
    [error, setError] = useState('');
  const state = useRef({
    base: initial,
    values: initial,
    running: false,
    timer: undefined as ReturnType<typeof setTimeout> | undefined,
    mounted: true
  });
  const pendingCallback = useRef(onPending);
  pendingCallback.current = onPending;
  const equal = (a: Record<string, number>, b: Record<string, number>) => fields.every(([key]) => a[key] === b[key]);
  const save = async () => {
    const s = state.current;
    if (s.running || readOnly || equal(s.base, s.values)) return;
    s.running = true;
    if (s.mounted) setStatus('saving');
    try {
      while (!equal(s.base, s.values)) {
        const sent = { ...s.values };
        const next = await api<Record<string, number>>(path, { values: sent, expected: s.base }, 'PUT');
        s.base = next;
        if (equal(s.values, sent)) { s.values = next; if (s.mounted) setValues(next) }
      }
      if (s.mounted) { setStatus('saved'); setError('') }
      pendingCallback.current?.(false);
      void qc.invalidateQueries();
    } catch (e) {
      if (s.mounted) { setStatus('error'); setError((e as Error).message) }
      pendingCallback.current?.(true)
    }
    finally { s.running = false }
  };
  const saveRef = useRef(save);
  saveRef.current = save;
  useEffect(
    () => {
      state.current.mounted = true;
      return () => { state.current.mounted = false; clearTimeout(state.current.timer); void saveRef.current() }
    },
    [path]
  );
  const change = (key: string, value: number) => {
    const s = state.current;
    s.values = { ...s.values, [key]: value };
    setValues(s.values);
    setStatus('waiting');
    setError('');
    pendingCallback.current?.(true);
    clearTimeout(s.timer);
    s.timer = setTimeout(() => { void saveRef.current() }, 650)
  };
  return <>
    <div className="lab-form">
      {
        fields.map(([key, label, format]) => <label key={key}>
          {label}
          {
            readOnly ?
              <strong>
                {
                  format === 'dollars' ?
                    money(initial[key]) :
                    format === 'percent' ? initial[key] / 100 + '%' : initial[key]
                }
              </strong> :
              <input
                type="number"
                min="0"
                step={
                  format === 'dollars' ?
                    '.01' :
                    key.includes('hours') || key.includes('minutes') || key === 'audit_fraction' ? '.1' : '1'
                }
                value={format ? values[key] / 100 : values[key]}
                onChange={e => change(key, format ? Math.round(Number(e.target.value) * 100) : Number(e.target.value))}
              />
          }
        </label>)
      }
    </div>
    {
      !readOnly &&
      <div className={'autosave-status ' + (error ? 'has-error' : '')} role="status">
        <span>
          <UiIcon name={status === 'saved' ? 'check' : error ? 'warning' : 'clock'} size={15} />
          {status === 'saved' ? 'Saved' : error ? 'Could not save' : 'Saving…'}
        </span>
        {error && <><small>{error}</small><button onClick={() => void saveRef.current()}>Retry</button></>}
      </div>
    }
  </>;
}
