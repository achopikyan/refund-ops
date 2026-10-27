import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { UiIcon } from './visualLanguage';

type Option = { value: string, label: string, tone: string, icon: string };
export default function BadgeSelect({ label, value, options, onChange, hideLabel = false }: {
  hideLabel?: boolean,
  label: string,
  value: string,
  options: Option[],
  onChange: (value: string) => void
}) {
  const id = useId(), button = useRef<HTMLButtonElement>(null), menu = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false),
    [active, setActive] = useState(0),
    [position, setPosition] = useState({ left: 0, top: 0, width: 220 });
  const selected = options.find(o => o.value === value) || options[0];
  const show = () => {
    if (!options.length) return;
    const rect = button.current!.getBoundingClientRect();
    setPosition({
      left: Math.max(8, Math.min(rect.left, innerWidth - 288)),
      top: rect.bottom + 250 > innerHeight ? Math.max(8, rect.top - 250) : rect.bottom + 5,
      width: Math.max(220, Math.min(280, innerWidth - 16))
    });
    setActive(Math.max(0, options.findIndex(o => o.value === value)));
    setOpen(true)
  };
  const select = (index: number) => { if (options[index]) onChange(options[index].value); setOpen(false); button.current?.focus() };
  useEffect(
    () => {
      if (!open) return;
      const close = (e: PointerEvent) => {
        if (!button.current?.contains(e.target as Node) && !menu.current?.contains(e.target as Node)) setOpen(false)
      };
      const resize = () => setOpen(false);
      const scroll = (e: Event) => { if (!menu.current?.contains(e.target as Node)) setOpen(false) };
      document.addEventListener('pointerdown', close);
      window.addEventListener('resize', resize);
      document.addEventListener('scroll', scroll, true);
      return () => {
        document.removeEventListener('pointerdown', close);
        window.removeEventListener('resize', resize);
        document.removeEventListener('scroll', scroll, true)
      }
    },
    [open]
  );
  useEffect(
    () => { if (open) document.getElementById(id + '-' + active)?.scrollIntoView({ block: 'nearest' }) },
    [open, active, id]
  );
  return <div className="badge-select">
    <span className={hideLabel ? "inline-column-label" : "badge-select-label"} id={id + '-label'}>
      {label}
    </span>
    <button
      ref={button}
      type="button"
      role="combobox"
      aria-haspopup="listbox"
      aria-labelledby={id + '-label'}
      aria-expanded={open}
      aria-controls={open ? id : undefined}
      aria-activedescendant={open ? id + '-' + active : undefined}
      className={'badge-select-trigger semantic-tag tone-' + (selected?.tone || 'slate')}
      onClick={() => open ? setOpen(false) : show()}
      onKeyDown={
        e => {
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            if (!open) show(); else setActive(n => (n + (e.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length)
          } else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (open) select(active); else show() } else if (e.key === 'Escape' || e.key === 'Tab') setOpen(false)
        }
      }
    >
      <UiIcon name={selected?.icon || 'tag'} size={15} />
      <span>{selected?.label || 'General'}</span>
      <span className="badge-select-chevron">⌄</span>
    </button>
    {
      open &&
      createPortal(
        <div
          ref={menu}
          id={id}
          role="listbox"
          aria-label={label}
          className="badge-select-menu"
          style={{ left: position.left, top: position.top, width: position.width }}
        >
          {
            options.map((option, i) => <div
              key={option.value}
              id={id + '-' + i}
              role="option"
              aria-selected={option.value === value}
              className={'badge-select-option ' + (i === active ? 'active' : '')}
              onMouseMove={() => setActive(i)}
              onMouseDown={e => e.preventDefault()}
              onClick={() => select(i)}
            >
              <span className={'semantic-tag tone-' + option.tone}>
                <UiIcon name={option.icon} size={15} />
                {option.label}
              </span>
              {option.value === value && <UiIcon name="check" size={14} />}
            </div>)
          }
        </div>,
        document.body
      )
    }
  </div>;
}
