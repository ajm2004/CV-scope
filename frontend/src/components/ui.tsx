import React, { useEffect, useState } from "react";
import { ApiError } from "../api/client";

export function Panel({ title, actions, children, className = "", flush = false, style }: { title?: React.ReactNode; actions?: React.ReactNode; children?: React.ReactNode; className?: string; flush?: boolean; style?: React.CSSProperties }) {
  return (
    <section className={`panel ${className}`} style={style}>
      {title !== undefined && (
        <header className="panel-h">
          <span>{title}</span>
          {actions && <span className="actions">{actions}</span>}
        </header>
      )}
      <div className={`panel-b ${flush ? "flush" : ""}`}>{children}</div>
    </section>
  );
}

export function Field({ label, help, children, className = "" }: { label: React.ReactNode; help?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <div className={`field ${className}`}>
      <label>{label}</label>
      {children}
      {help && <span className="help">{help}</span>}
    </div>
  );
}

export function Pill({ tone = "", children, dot = false }: { tone?: "" | "ok" | "warn" | "err" | "accent"; children: React.ReactNode; dot?: boolean }) {
  return (
    <span className={`pill ${tone}`}>
      {dot && <span className="dot" />}
      {children}
    </span>
  );
}

export function Stat({ value, label, tone }: { value: React.ReactNode; label: React.ReactNode; tone?: string }) {
  return (
    <div className="stat">
      <div className="v" style={tone ? { color: `var(--${tone})` } : undefined}>
        {value}
      </div>
      <div className="l">{label}</div>
    </div>
  );
}

export function Empty({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="empty">
      <div>{children}</div>
      {action}
    </div>
  );
}

export function Notice({ tone = "", children }: { tone?: "" | "warn" | "err" | "ok"; children: React.ReactNode }) {
  return <div className={`notice ${tone}`}>{children}</div>;
}

export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof ApiError ? error.message : error instanceof Error ? error.message : String(error);
  return <Notice tone="err">{msg}</Notice>;
}

export function Progress({ value }: { value: number }) {
  return (
    <div className="progress">
      <span style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
    </div>
  );
}

export function Modal({ title, onClose, children, footer, width }: { title: string; onClose: () => void; children: React.ReactNode; footer?: React.ReactNode; width?: number }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={width ? { width: `min(${width}px, 94vw)` } : undefined} role="dialog" aria-modal="true">
        <header className="panel-h">
          <span>{title}</span>
          <button className="btn ghost sm" onClick={onClose} aria-label="Close">
            Close
          </button>
        </header>
        <div className="panel-b">{children}</div>
        {footer && (
          <div className="panel-b" style={{ borderTop: "1px solid var(--line)", display: "flex", justifyContent: "flex-end", gap: 8 }}>
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

export function KV({ items }: { items: [React.ReactNode, React.ReactNode][] }) {
  return (
    <dl className="kv">
      {items.map(([k, v], i) => (
        <React.Fragment key={i}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

export function Tabs({ tabs, active, onChange }: { tabs: { id: string; label: string }[]; active: string; onChange: (id: string) => void }) {
  return (
    <div className="tabs">
      {tabs.map((t) => (
        <button key={t.id} className={active === t.id ? "active" : ""} onClick={() => onChange(t.id)}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function useLocalState<T>(key: string, initial: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw ? (JSON.parse(raw) as T) : initial;
    } catch {
      return initial;
    }
  });
  const set = (nv: T) => {
    setV(nv);
    try {
      localStorage.setItem(key, JSON.stringify(nv));
    } catch {
      /* ignore */
    }
  };
  return [v, set];
}

export function ConfirmButton({ label, confirm = "Confirm", onConfirm, className = "btn danger sm" }: { label: string; confirm?: string; onConfirm: () => void; className?: string }) {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(false), 3000);
    return () => clearTimeout(t);
  }, [armed]);
  return (
    <button
      className={className}
      onClick={() => {
        if (armed) {
          setArmed(false);
          onConfirm();
        } else setArmed(true);
      }}
    >
      {armed ? confirm : label}
    </button>
  );
}

export function ClassPicker({ value, onChange, options }: { value: string[]; onChange: (v: string[]) => void; options: { id: string; label: string }[] }) {
  return (
    <div className="row wrap" style={{ gap: 6 }}>
      {options.map((o) => (
        <label key={o.id} className="check">
          <input
            type="checkbox"
            checked={value.includes(o.id)}
            onChange={(e) => onChange(e.target.checked ? [...value, o.id] : value.filter((x) => x !== o.id))}
          />
          {o.label}
        </label>
      ))}
    </div>
  );
}
