import type { ReactNode } from 'react';
import { AlertCircle, CheckCircle2, Info, TriangleAlert, type LucideIcon } from 'lucide-react';

export type StatusKind = 'success' | 'warning' | 'critical' | 'info' | 'neutral';

export function Card({
  children,
  className = '',
  title,
  description,
  actions,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <section className={`ui-card ${className}`.trim()}>
      {(title || description || actions) && (
        <header className="ui-card__header">
          <div>
            {title && <h2>{title}</h2>}
            {description && <p>{description}</p>}
          </div>
          {actions && <div className="ui-card__actions">{actions}</div>}
        </header>
      )}
      <div className="ui-card__body">{children}</div>
    </section>
  );
}

export function KpiCard({ label, value, context, icon }: {
  label: string;
  value: ReactNode;
  context?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <article className="ui-kpi" aria-label={label}>
      <div className="ui-kpi__label">{label}{icon && <span>{icon}</span>}</div>
      <strong className="ui-kpi__value">{value}</strong>
      {context && <div className="ui-kpi__context">{context}</div>}
    </article>
  );
}

const statusIcons = {
  success: CheckCircle2,
  warning: TriangleAlert,
  critical: AlertCircle,
  info: Info,
  neutral: Info,
} satisfies Record<StatusKind, LucideIcon>;

export function StatusBadge({ kind = 'neutral', children }: { kind?: StatusKind; children: ReactNode }) {
  const Icon = statusIcons[kind];
  return <span className={`ui-status ui-status--${kind}`}><Icon size={14} aria-hidden="true"/><span>{children}</span></span>;
}

export function ConfidenceMeter({ value, label = 'Evidence confidence' }: { value: number | null | undefined; label?: string }) {
  const known = typeof value === 'number' && Number.isFinite(value);
  const percent = known ? Math.max(0, Math.min(100, value <= 1 ? value * 100 : value)) : null;
  return (
    <div className="ui-meter">
      <div className="ui-meter__heading"><span>{label}</span><strong>{percent === null ? 'Not detected' : `${Math.round(percent)}%`}</strong></div>
      <div className="ui-meter__track" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent ?? undefined} aria-valuetext={percent === null ? 'Not detected' : `${Math.round(percent)} percent`}>
        {percent !== null && <span style={{ width: `${percent}%` }} />}
      </div>
    </div>
  );
}

export function CoverageBar({ observed, total, label = 'Coverage' }: { observed: number | null | undefined; total: number | null | undefined; label?: string }) {
  const known = typeof observed === 'number' && typeof total === 'number' && total > 0;
  const percent = known ? Math.max(0, Math.min(100, observed / total * 100)) : null;
  return (
    <div className="ui-meter">
      <div className="ui-meter__heading"><span>{label}</span><strong>{known ? `${observed.toLocaleString()} / ${total.toLocaleString()}` : 'Not observed'}</strong></div>
      <div className="ui-meter__track" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent ?? undefined} aria-valuetext={percent === null ? 'Not observed' : `${Math.round(percent)} percent`}>
        {percent !== null && <span style={{ width: `${percent}%` }} />}
      </div>
    </div>
  );
}

export function EvidenceChip({ children, kind = 'static' }: { children: ReactNode; kind?: 'static' | 'runtime' | 'inferred' | 'confirmed' }) {
  return <span className={`ui-evidence-chip ui-evidence-chip--${kind}`}>{children}</span>;
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return <div className="ui-skeleton" aria-busy="true" aria-label="Loading content">{Array.from({ length: Math.max(1, lines) }, (_, i) => <span key={i}/>)}</div>;
}

export function Tooltip({ children, content }: { children: ReactNode; content: string }) {
  return <span className="ui-tooltip" tabIndex={0} aria-label={content}>{children}<span role="tooltip">{content}</span></span>;
}
