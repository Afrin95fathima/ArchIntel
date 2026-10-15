import type { ReactNode } from 'react';
import { ArrowUpRight, LoaderCircle } from 'lucide-react';
export function Badge({children, tone='neutral'}: {children: ReactNode; tone?: string}) {
  return <span className={'badge ' + tone.toLowerCase()}>{children}</span>;
}
export function Button({children, onClick, secondary=false, disabled=false}: {children: ReactNode; onClick?: () => void; secondary?: boolean; disabled?: boolean}) {
  return <button className={secondary ? 'button secondary' : 'button'} onClick={onClick} disabled={disabled}>{children}</button>;
}
export function Loading({text='Loading analysis…'}: {text?: string}) { return <div className="loading"><LoaderCircle className="spin" size={22}/>{text}</div>; }
export function ErrorBox({error}: {error: unknown}) { return <div className="error-box" role="alert">{error instanceof Error ? error.message : String(error)}</div>; }
export function PageTitle({eyebrow, title, description, action}: {eyebrow: string; title: string; description: string; action?: ReactNode}) {
  return <div className="page-title"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p className="subtitle">{description}</p></div>{action}</div>;
}
export function Stat({label,value,note,icon}: {label:string;value: ReactNode;note:string;icon:ReactNode}) {
  return <div className="stat-card"><div className="stat-top">{label}<span>{icon}</span></div><strong>{value}</strong><small>{note}</small></div>;
}
export function ScoreBar({value}: {value: number}) { return <div className="score-bar"><div style={{width: value+'%'}}/></div>; }
export function Empty({title,children}: {title:string;children:ReactNode}) { return <div className="empty"><div className="empty-icon"><ArrowUpRight/></div><h2>{title}</h2><p>{children}</p></div>; }
export function human(value: string) { return value.toLowerCase().replaceAll('_',' ').replace(/^./, c=>c.toUpperCase()); }

export { Card, ConfidenceMeter, CoverageBar, EvidenceChip, KpiCard, Skeleton, StatusBadge, Tooltip } from './ui';
export { Tabs } from './ui/Tabs';
