import { useMemo, useState } from 'react';
import { AlertTriangle, ExternalLink } from 'lucide-react';
import { PageTitle } from '../components';
import { AiExplain, Expandable, ExplanationLayers, Formula, InsightState, NodeLink, NotAvailable, useInsight } from './shared';

export type CallSite = { where: string; text: string; line?: number | null };
export type AffectedClass = { class_name: string; package: string; apis: string[]; api_count: number; call_site_count: number; call_sites: CallSite[] };
export type LifecycleFinding = {
  id: string; rule_id: string; technology: string; category: string; version_found: string | null; version_reason: string | null;
  status: 'end-of-life' | 'aging' | 'current'; status_note: string | null; matched_range: string | null; source_url: string;
  recommended_alternative: string; replacement: { from: string; to: string } | null; migration_notes: string; effort_hint: string;
  effort_index: { value: number; formula: string; inputs: Record<string, number>; label: string };
  evidence: { kind: string; text: string }[]; affected_class_count: number; call_site_count: number; affected_classes: AffectedClass[];
  affected_truncated: boolean; explanation: { technical: string; plain: string };
};
export type LifecycleResult = {
  rules: { rules_version: string; reviewed: string; age_days: number; max_age_days: number; stale: boolean; warning: string | null };
  findings: LifecycleFinding[]; summary: Record<string, number>; label: string; limitations: string[];
};

const STATUS_LABEL: Record<string, string> = { 'end-of-life': 'End-of-life', aging: 'Aging', current: 'Current' };

export function TechnologyLifecycle({ analysisId }: { analysisId: string }) {
  const query = useInsight<LifecycleResult>(analysisId, 'lifecycle');
  const [status, setStatus] = useState('');
  const [open, setOpen] = useState('');
  return <>
    <PageTitle eyebrow="TECHNOLOGY LIFECYCLE" title="Which technologies are ageing, and where are they used?"
      description="Each row is matched against lifecycle-rules.yaml. Status = vendor support (end-of-life / aging / current), not security vulnerabilities." />
    <InsightState query={query}>{() => {
      const data = query.data!;
      return <LifecycleBody data={data} analysisId={analysisId} status={status} setStatus={setStatus} open={open} setOpen={setOpen} />;
    }}</InsightState>
  </>;
}

function LifecycleBody({ data, analysisId, status, setStatus, open, setOpen }: { data: LifecycleResult; analysisId: string; status: string; setStatus: (v: string) => void; open: string; setOpen: (v: string) => void }) {
  const rows = useMemo(() => data.findings.filter(f => !status || f.status === status), [data, status]);
  return <>
    {data.rules.stale && <div className="warning-banner" role="alert"><AlertTriangle size={18} /><span>{data.rules.warning}</span></div>}
    <p className="fine-print">Rules version {data.rules.rules_version}, reviewed {data.rules.reviewed} ({data.rules.age_days} days ago; warning after {data.rules.max_age_days} days). {data.label}</p>
    <div className="insight-cards">
      {(['end-of-life', 'aging', 'current'] as const).map(key => <article key={key}><strong>{data.summary[key] || 0}</strong><span>{STATUS_LABEL[key]} findings</span></article>)}
      <article><strong>{data.findings.reduce((n, f) => n + f.affected_class_count, 0)}</strong><span>class usages (a class can count for several technologies)</span></article>
    </div>
    {data.limitations.map(item => <p className="fine-print" key={item}>{item}</p>)}
    <div className="insight-toolbar"><label>Status <select aria-label="Filter by lifecycle status" value={status} onChange={e => setStatus(e.target.value)}><option value="">All</option><option value="end-of-life">End-of-life</option><option value="aging">Aging</option><option value="current">Current</option></select></label><span className="muted">{rows.length} technologies</span></div>
    {!rows.length ? <NotAvailable reason={data.findings.length ? 'No technology matches this filter.' : 'No rule in the lifecycle rules file matched this application: no matching dependency metadata, class-file targets or package usage was found.'} /> :
      <div className="insight-table-wrap"><table className="insight-table"><thead><tr><th>Technology</th><th>Version found</th><th>Status</th><th>Affected classes</th><th>Recommended alternative</th><th>Effort hint</th></tr></thead>
        <tbody>{rows.map(f => <LifecycleRow key={f.id} finding={f} analysisId={analysisId} open={open === f.id} toggle={() => setOpen(open === f.id ? '' : f.id)} />)}</tbody></table></div>}
  </>;
}

function LifecycleRow({ finding: f, analysisId, open, toggle }: { finding: LifecycleFinding; analysisId: string; open: boolean; toggle: () => void }) {
  return <>
    <tr className={open ? 'selected' : ''}>
      <td><button type="button" className="node-link" aria-expanded={open} onClick={toggle}>{f.technology}</button><div className="fine-print">{f.category}</div></td>
      <td>{f.version_found || <span className="muted" title={f.version_reason || ''}>not determinable</span>}</td>
      <td><span className={'status-pill ' + f.status}>{STATUS_LABEL[f.status]}</span></td>
      <td>{f.affected_class_count}{f.call_site_count ? <small className="muted"> · {f.call_site_count} code references</small> : null}</td>
      <td>{f.recommended_alternative}{f.replacement && <div className="fine-print"><code>{f.replacement.from}</code> → <code>{f.replacement.to}</code></div>}</td>
      <td>{f.effort_hint}</td>
    </tr>
    {open && <tr className="selected"><td colSpan={6}>
      <ExplanationLayers explanation={f.explanation} evidence={f.evidence} action={f.migration_notes} />
      {f.version_reason && <p className="fine-print">Version: {f.version_reason}.</p>}
      <p className="fine-print">Why this status: {f.status_note || 'rule default status for any version'}. Source: <a href={f.source_url} target="_blank" rel="noreferrer">{f.source_url} <ExternalLink size={11} /></a></p>
      <Formula formula={f.effort_index.formula} inputs={f.effort_index.inputs} /><p className="fine-print">Effort index {f.effort_index.value}. {f.effort_index.label}</p>
      <h4>Affected classes ({f.affected_class_count}{f.affected_truncated ? ', list truncated' : ''})</h4>
      {f.affected_classes.length ? f.affected_classes.map(c => <Expandable key={c.class_name} summary={<><NodeLink id={c.class_name} /> <span className="muted">· {c.call_site_count} references · {c.apis.slice(0, 3).join(', ')}{c.apis.length > 3 ? '…' : ''}</span></>}>
        {c.call_sites.length ? <ul className="call-sites">{c.call_sites.map((s, i) => <li key={i}>{s.text}{s.line ? ` (line ${s.line})` : ''}</li>)}</ul> : <p className="muted">Referenced at class level only (call sites: not measured).</p>}
      </Expandable>) : <p className="muted">Found from dependency metadata only; no application class references these packages.</p>}
      {f.affected_class_count > 0 && f.status !== 'current' && <AiExplain analysisId={analysisId} path="lifecycle/explain" targetId={f.id} title="AI migration note for these classes (optional)" />}
    </td></tr>}
  </>;
}
