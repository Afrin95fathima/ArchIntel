import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { publishAssistantContext } from '../assistantContext';
import { ErrorBox, Loading, PageTitle } from '../components';
import { AiExplain, Expandable, InsightState, NodeLink, NotAvailable, short, useInsight } from './shared';

export type Confidence = { level: 'HIGH' | 'MEDIUM' | 'LOW'; basis: string; calibrated: boolean };
type Evidence = { id: string; kind: string; text: string; strength: string; member: string | null; location: { file_path: string | null; start_line: number | null; member_line_range?: number[] | null; available: boolean; basis: string } };
export type Label = { category: string; side: 'FUNCTIONAL' | 'NON_FUNCTIONAL'; status: 'DETECTED' | 'INFERRED' | 'UNVERIFIED'; description: string; rule_ids: string[]; evidence_count: number;
  confidence: Confidence; mixes: boolean; methods: string[]; evidence?: Evidence[]; limit?: string };
type Taxonomy = Record<string, { label: string; description: string; limit: string }>;
export type Risk = { id: string; rule_id: string; category: string; title: string; description: string; severity: string; affected_components: string[]; affected_count: number; detection_status: string;
  consequence_status: string; consequence: string; potential_impact: string; confidence: Confidence; investigate: string; runtime_validation_required: boolean; priority_basis: string };
type Implication = { kind: string; severity: string; text: string };
export type Capability = { id: string; name: string; kind: string; class_count: number; primary_counts: Record<string, number>; basis: string; boundary_notes: string[]; entities: string[]; repositories: string[];
  boundary_confidence: { value: number | null; note: string }; nonfunctional_concerns: { category: string; class_count: number }[]; implications: Implication[]; risk_ids: string[] };
export type CrossCutting = { id: string; name: string; kind: string; concerns: string[]; scope: string; dependent_count: number; capabilities: { id: string; name: string }[]; capability_count: number; deployment_form: string; guidance: string; change_impact: string };
export type Summary = { status: string; reason?: string;
  analysis_metadata: { engine_version: string; rules_version: string; artifact_sha256: string | null; source_revision_kind: string; analyzed_class_count: number; confidence: { calibrated: boolean; levels: Record<string, string> } };
  taxonomy: { functional: Taxonomy; nonfunctional: Taxonomy; primary_classifications: Record<string, string>; statuses: Record<string, string> };
  summary: { classes: number; by_primary: Record<string, number>; functional_categories: Record<string, number>; nonfunctional_categories: Record<string, number>; capabilities: number; cross_cutting: number; dependencies: number; risks: number;
    risks_by_severity: Record<string, number>; evidence_items: number; evidence_rejected: number; statuses: Record<string, number> };
  validation: { evidence_checked: number; evidence_rejected: number };
  capabilities: Capability[]; cross_cutting: CrossCutting[]; risks: Risk[]; limitations: string[] };
export type Row = { id: string; fqn: string; simple_name: string; package: string; primary_classification: string; architectural_role: { role: string; layer: string };
  capability: { id: string; name: string; kind: string } | null; functional: { category: string; status: string; confidence: string }[]; non_functional: { category: string; status: string; confidence: string }[];
  risk_count: number; dependency_count: number; dependent_count: number; uncertain: boolean };
export type Page = { status: string; reason?: string; items: Row[]; total: number; offset: number; limit: number };
export type Detail = { fqn: string; simple_name: string; primary_classification: string; classification_reasons: string[]; architectural_role: { role: string; layer: string; evidence: string; reason: string };
  source_location: { file_path: string | null; start_line: number | null; available: boolean; basis: string };
  business_capabilities: { id: string; name: string; kind: string; relation: string }[]; functional_responsibilities: Label[]; non_functional_responsibilities: Label[];
  methods: { signature: string; name: string; labels: { category: string; side: string; status: string }[] }[]; uncertainties: string[];
  dependency_details: { target: string; relation: string; crosses_capability: boolean; evidence: { text: string; line: number | null }[] }[];
  dependent_details: { source: string; relation: string; crosses_capability: boolean }[]; risks: Risk[]; cross_cutting: CrossCutting[]; capability_implications: { capability: string; implications: Implication[] }[] };

const PRIMARY = ['FUNCTIONAL', 'FUNCTIONAL_SUPPORT', 'MIXED', 'NON_FUNCTIONAL', 'UNCERTAIN'];
const PAGE_SIZE = 25;
const pretty = (value: string) => value.replaceAll('_', ' ').toLowerCase();

export function Responsibilities({ analysisId }: { analysisId: string }) {
  const query = useInsight<Summary>(analysisId, 'responsibilities');
  return <>
    <PageTitle eyebrow="RESPONSIBILITIES" title="What each Java class does, and which concerns it carries."
      description="Functional responsibilities and non-functional concerns read from bytecode, each with its evidence, a DETECTED or INFERRED status and an ordinal confidence. Names alone never decide a class." />
    <InsightState query={query}>{() => query.data!.status !== 'AVAILABLE' ? <NotAvailable reason={query.data!.reason || 'Responsibility analysis is not available for this analysis.'} /> : <Body analysisId={analysisId} data={query.data!} />}</InsightState>
  </>;
}

function Body({ analysisId, data }: { analysisId: string; data: Summary }) {
  const [tab, setTab] = useState<'components' | 'capabilities' | 'cross' | 'risks' | 'method'>('components');
  const s = data.summary;
  return <>
    <div className="insight-cards">
      {PRIMARY.map(p => <article key={p}><strong>{s.by_primary[p] || 0}</strong><span>{pretty(p)}</span></article>)}
      <article><strong>{s.capabilities}</strong><span>candidate domains ({Object.entries(data.capabilities.reduce((a, c) => ({ ...a, [c.kind]: (a[c.kind] || 0) + 1 }), {} as Record<string, number>)).map(([k, n]) => `${n} ${k.toLowerCase()}`).join(', ')})</span></article>
      <article><strong>{s.cross_cutting}</strong><span>components or libraries shared across domains</span></article>
      <article><strong>{s.risks}</strong><span>risk indicators ({s.risks_by_severity.HIGH || 0} high, {s.risks_by_severity.MEDIUM || 0} medium)</span></article>
    </div>
    <p className="fine-print">{s.classes} classes analyzed with rules {data.analysis_metadata.rules_version}. {s.evidence_items} evidence items resolved to the snapshot and {s.evidence_rejected} were rejected. Confidence levels are an ordinal heuristic, not a calibrated probability.</p>
    <div className="resp-tabs" role="tablist">{([['components', 'Components'], ['capabilities', 'Capabilities'], ['cross', 'Cross-cutting'], ['risks', 'Risks'], ['method', 'Method and limits']] as const).map(([id, label]) =>
      <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>{label}</button>)}</div>
    {tab === 'components' && <Components analysisId={analysisId} data={data} />}
    {tab === 'capabilities' && <Capabilities data={data} />}
    {tab === 'cross' && <Cross data={data} />}
    {tab === 'risks' && <Risks data={data} />}
    {tab === 'method' && <Method data={data} />}
  </>;
}

function Chip({ category, status, confidence, taxonomy }: { category: string; status: string; confidence?: string; taxonomy: Taxonomy }) {
  return <span className={'resp-chip ' + status.toLowerCase()} title={`${taxonomy[category]?.label || category}: ${status.toLowerCase()}${confidence ? `, ${confidence.toLowerCase()} confidence` : ''}. ${taxonomy[category]?.limit || ''}`}>{taxonomy[category]?.label || pretty(category)}{status === 'DETECTED' ? '' : status === 'INFERRED' ? ' (inferred)' : ' (unverified)'}</span>;
}

function Components({ analysisId, data }: { analysisId: string; data: Summary }) {
  const [filters, setFilters] = useState({ primary: '', functional: '', concern: '', capability: '', status: '', confidence: '', q: '' });
  const [offset, setOffset] = useState(0), [open, setOpen] = useState('');
  const set = (key: keyof typeof filters, value: string) => { setFilters(f => ({ ...f, [key]: value })); setOffset(0); };
  const params = useMemo(() => { const p = new URLSearchParams({ offset: String(offset), limit: String(PAGE_SIZE) }); Object.entries(filters).forEach(([k, v]) => v && p.set(k, v)); return p.toString(); }, [filters, offset]);
  const page = useQuery({ queryKey: ['insight', analysisId, 'responsibility-components', params], queryFn: () => api<Page>(`/analyses/${analysisId}/insight/responsibilities/components?${params}`) });
  const tax = data.taxonomy;
  return <>
    <div className="insight-toolbar">
      <input aria-label="Search class" placeholder="Search class or package…" value={filters.q} onChange={e => set('q', e.target.value)} />
      <select aria-label="Primary classification" value={filters.primary} onChange={e => set('primary', e.target.value)}><option value="">All classifications</option>{PRIMARY.map(p => <option key={p} value={p}>{pretty(p)}</option>)}</select>
      <select aria-label="Functional responsibility" value={filters.functional} onChange={e => set('functional', e.target.value)}><option value="">All functional responsibilities</option>{Object.entries(tax.functional).map(([k, v]) => <option key={k} value={k}>{v.label} ({data.summary.functional_categories[k] || 0})</option>)}</select>
      <select aria-label="Non-functional concern" value={filters.concern} onChange={e => set('concern', e.target.value)}><option value="">All non-functional concerns</option>{Object.entries(tax.nonfunctional).filter(([k]) => data.summary.nonfunctional_categories[k]).map(([k, v]) => <option key={k} value={k}>{v.label} ({data.summary.nonfunctional_categories[k]})</option>)}</select>
      <select aria-label="Business capability" value={filters.capability} onChange={e => set('capability', e.target.value)}><option value="">All candidate domains</option>{data.capabilities.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
      <select aria-label="Detection status" value={filters.status} onChange={e => set('status', e.target.value)}><option value="">Any status</option>{['DETECTED', 'INFERRED', 'UNVERIFIED'].map(x => <option key={x}>{x}</option>)}</select>
      <select aria-label="Confidence" value={filters.confidence} onChange={e => set('confidence', e.target.value)}><option value="">Any confidence</option>{['HIGH', 'MEDIUM', 'LOW'].map(x => <option key={x}>{x}</option>)}</select>
      <span className="muted">{page.data?.total ?? '…'} classes</span>
    </div>
    {page.isPending ? <Loading /> : page.error ? <ErrorBox error={page.error} /> : !page.data!.items.length ? <NotAvailable reason={`No class matches these filters among the ${data.summary.classes} analyzed classes.`} /> : <>
      <div className="insight-table-wrap"><table className="insight-table"><thead><tr><th>Class</th><th>Classification</th><th>Candidate domain</th><th>Functional</th><th>Non-functional</th><th>Risks</th><th>Depends on / by</th></tr></thead><tbody>
        {page.data!.items.map(r => <tr key={r.id} className={open === r.id ? 'selected' : ''}>
          <td><button className="resp-link" onClick={() => setOpen(open === r.id ? '' : r.id)} aria-expanded={open === r.id}>{r.simple_name}</button><div className="fine-print">{r.package}</div></td>
          <td><span className={'resp-primary ' + r.primary_classification.toLowerCase()}>{pretty(r.primary_classification)}</span><div className="fine-print">{pretty(r.architectural_role.role)}</div></td>
          <td>{r.capability ? <>{r.capability.name}<div className="fine-print">{r.capability.kind.toLowerCase()}</div></> : <span className="muted">none</span>}</td>
          <td>{r.functional.length ? r.functional.map(l => <Chip key={l.category} {...l} taxonomy={tax.functional} />) : <span className="muted">none detected</span>}</td>
          <td>{r.non_functional.length ? r.non_functional.map(l => <Chip key={l.category} {...l} taxonomy={tax.nonfunctional} />) : <span className="muted">none detected</span>}</td>
          <td>{r.risk_count || <span className="muted">0</span>}</td><td>{r.dependency_count} / {r.dependent_count}</td></tr>)}
      </tbody></table></div>
      <div className="resp-pager"><button className="secondary-button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</button>
        <span className="muted">{offset + 1}–{Math.min(offset + PAGE_SIZE, page.data!.total)} of {page.data!.total}</span>
        <button className="secondary-button" disabled={offset + PAGE_SIZE >= page.data!.total} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</button></div>
    </>}
    {open && <ComponentDetail analysisId={analysisId} id={open} data={data} onClose={() => setOpen('')} />}
  </>;
}

function Evidences({ items }: { items?: Evidence[] }) {
  if (!items?.length) return <p className="fine-print">No evidence item resolved for this label, so ArchIntel marks it UNVERIFIED.</p>;
  return <ul className="resp-evidence">{items.map(e => <li key={e.id}><span className="evidence-kind">{pretty(e.kind)}</span>{e.text}
    <span className="muted"> · {e.strength.toLowerCase()}{e.location.start_line ? ` · line ${e.location.start_line}` : e.location.member_line_range ? ` · method body at lines ${e.location.member_line_range[0]}–${e.location.member_line_range[1]} (bytecode does not record where the annotation was written)` : ' · line not recorded'}</span></li>)}</ul>;
}

function Labels({ labels, taxonomy, title }: { labels: Label[]; taxonomy: Taxonomy; title: string }) {
  return <section className="resp-section"><h4>{title}</h4>{!labels.length ? <p className="muted">None detected in the bytecode of this Java class.</p> : <ul className="resp-labels">{labels.map(l =>
    <li key={l.category}><div><strong>{taxonomy[l.category]?.label || l.category}</strong> <span className={'status-pill ' + (l.status === 'DETECTED' ? 'ok' : l.status === 'INFERRED' ? 'medium' : 'info')}>{l.status}</span>{' '}
      <span className="muted" title={l.confidence.basis}>{l.confidence.level.toLowerCase()} confidence (heuristic)</span>{l.mixes && <span className="resp-note"> · the class's own code runs this concern</span>}</div>
      <p>{l.description}.</p>
      <Evidences items={l.evidence} />
      {l.limit && <p className="fine-print">What this does not prove: {l.limit}</p>}</li>)}</ul>}</section>;
}

function ComponentDetail({ analysisId, id, data, onClose }: { analysisId: string; id: string; data: Summary; onClose: () => void }) {
  const query = useQuery({ queryKey: ['insight', analysisId, 'responsibility-component', id], queryFn: () => api<Detail>(`/analyses/${analysisId}/insight/responsibilities/component?id=${encodeURIComponent(id)}`) });
  useEffect(() => { publishAssistantContext({ kind: 'class', id, label: short(id) }); return () => publishAssistantContext(null); }, [id]);
  return <section className="panel insight-panel resp-detail" aria-label={`Details of ${short(id)}`}>
    <div className="insight-panel-head"><h3>{short(id)}</h3><button className="secondary-button" onClick={onClose}>Close</button></div>
    {query.isPending ? <Loading /> : query.error ? <ErrorBox error={query.error} /> : (() => {
      const d = query.data!;
      return <>
        <p><span className={'resp-primary ' + d.primary_classification.toLowerCase()}>{pretty(d.primary_classification)}</span> {data.taxonomy.primary_classifications[d.primary_classification]}
          {d.classification_reasons.map(r => <span key={r} className="resp-note"> Reason: {r}.</span>)}</p>
        <p className="fine-print"><NodeLink id={d.fqn} /> · role {pretty(d.architectural_role.role)} ({d.architectural_role.reason}) · {d.source_location.file_path || 'source file unknown'}
          {d.source_location.available ? '' : ' (path derived from the package and the SourceFile attribute; the artifact has no source)'}</p>
        <p>{d.business_capabilities.length ? d.business_capabilities.map(c => <span key={c.id} className="resp-chip detected" title={c.kind}>{c.relation === 'MEMBER' ? 'Member of' : 'Uses'} {c.name} ({c.kind.toLowerCase()})</span>) : <span className="muted">No candidate domain.</span>}</p>
        {d.uncertainties.map(u => <p key={u} className="warning-banner">{u}</p>)}
        <Labels labels={d.functional_responsibilities} taxonomy={data.taxonomy.functional} title="Functional responsibilities" />
        <Labels labels={d.non_functional_responsibilities} taxonomy={data.taxonomy.nonfunctional} title="Non-functional concerns" />
        {d.risks.length > 0 && <section className="resp-section"><h4>Risk indicators</h4><ul className="detail-list">{d.risks.map(r => <li key={r.id}><span className={'status-pill ' + r.severity.toLowerCase()}>{r.severity}</span> <strong>{r.title}</strong>: {r.description}.
          <div className="fine-print">Consequence (inferred): {r.consequence} Investigate: {r.investigate}{r.runtime_validation_required ? ' Needs runtime validation.' : ''}</div></li>)}</ul></section>}
        <Expandable summary={<strong>Depends on {d.dependency_details.length}, used by {d.dependent_details.length}</strong>}>
          <ul className="call-sites">{d.dependency_details.map(x => <li key={x.target}>→ <NodeLink id={x.target} /> <span className="muted">{pretty(x.relation)}{x.crosses_capability ? ', crosses a domain boundary' : ''}{x.evidence[0] ? ` · ${x.evidence[0].text}${x.evidence[0].line ? ` (line ${x.evidence[0].line})` : ''}` : ''}</span></li>)}
            {d.dependent_details.map(x => <li key={x.source}>← <NodeLink id={x.source} /> <span className="muted">{pretty(x.relation)}{x.crosses_capability ? ', crosses a domain boundary' : ''}</span></li>)}</ul></Expandable>
        <Expandable summary={<strong>Methods with a responsibility ({d.methods.filter(m => m.labels.length).length})</strong>}>
          <ul className="call-sites">{d.methods.filter(m => m.labels.length).map(m => <li key={m.signature}>{m.name}() <span className="muted">{m.labels.map(l => `${pretty(l.category)} (${l.status.toLowerCase()})`).join(', ')}</span></li>)}</ul></Expandable>
        {d.cross_cutting.length > 0 && <Expandable summary={<strong>Shared components it takes part in ({d.cross_cutting.length})</strong>}><ul>{d.cross_cutting.map(c => <li key={c.id}><strong>{c.name}</strong>: {c.guidance}</li>)}</ul></Expandable>}
        {d.capability_implications.map(c => <Expandable key={c.capability} summary={<strong>What this means for modernizing {c.capability}</strong>}><ul>{c.implications.map(i => <li key={i.text}><span className={'status-pill ' + i.severity.toLowerCase()}>{i.severity}</span> {i.text}</li>)}</ul></Expandable>)}
        <AiExplain analysisId={analysisId} path="responsibilities/explain" targetId={id} title="AI: explain this class in words (optional)" />
      </>;
    })()}
  </section>;
}

function Capabilities({ data }: { data: Summary }) {
  if (!data.capabilities.length) return <NotAvailable reason="No candidate domain was found for this analysis, so no business capability can be named." />;
  return <>{data.capabilities.map(c => <section key={c.id} className="panel insight-panel">
    <div className="insight-panel-head"><h3>{c.name}</h3><span className={'resp-primary ' + (c.kind === 'BUSINESS' ? 'functional' : c.kind === 'TECHNICAL' ? 'non_functional' : 'mixed')}>{c.kind.toLowerCase()}</span></div>
    <p>{c.class_count} classes: {Object.entries(c.primary_counts).map(([k, n]) => `${n} ${pretty(k)}`).join(', ')}. {c.basis}.</p>
    <p className="fine-print">Boundary confidence {c.boundary_confidence.value ?? 'not recorded'}: {c.boundary_confidence.note}</p>
    {c.boundary_notes.map(n => <p key={n} className="fine-print">Note: {c.name} {n}.</p>)}
    <p>{c.nonfunctional_concerns.length ? c.nonfunctional_concerns.map(x => <span key={x.category} className="resp-chip detected">{data.taxonomy.nonfunctional[x.category]?.label || x.category} ({x.class_count})</span>) : <span className="muted">{`No non-functional concern detected in its ${c.class_count} classes.`}</span>}</p>
    <h4>What this means for modernization</h4>
    <ul className="detail-list">{c.implications.map(i => <li key={i.text}><span className={'status-pill ' + i.severity.toLowerCase()}>{i.severity}</span> {i.text}</li>)}</ul>
  </section>)}</>;
}

function Cross({ data }: { data: Summary }) {
  const [kind, setKind] = useState('');
  const rows = data.cross_cutting.filter(c => !kind || c.kind === kind);
  return <>
    <p className="fine-print">A class is cross-cutting when classes of two or more other candidate domains use it; a library is, when two or more domains include it. A single other domain calling a class is an ordinary cross-domain dependency, shown in Candidate domains. A shared library is kept as a library dependency; it is not turned into a service by default.</p>
    <div className="insight-toolbar"><select aria-label="Kind of shared component" value={kind} onChange={e => setKind(e.target.value)}><option value="">All kinds</option>{[...new Set(data.cross_cutting.map(c => c.kind))].map(k => <option key={k} value={k}>{pretty(k)}</option>)}</select><span className="muted">{rows.length} shared</span></div>
    {!rows.length ? <NotAvailable reason="No component or library is used from two or more candidate domains in this analysis." /> :
      <div className="insight-table-wrap"><table className="insight-table"><thead><tr><th>Name</th><th>Kind</th><th>Domains</th><th>Used by</th><th>Form</th><th>Guidance</th></tr></thead><tbody>{rows.map(c =>
        <tr key={c.id}><td><strong>{c.name}</strong><div className="fine-print">{c.concerns.map(x => data.taxonomy.nonfunctional[x]?.label || data.taxonomy.functional[x]?.label || pretty(x)).join(', ')}</div></td><td>{pretty(c.kind)}</td>
          <td>{c.capabilities.map(x => x.name).join(', ')}</td><td>{c.dependent_count} classes</td><td>{pretty(c.deployment_form)}</td><td>{c.guidance}<div className="fine-print">{c.change_impact}</div></td></tr>)}</tbody></table></div>}
  </>;
}

function Risks({ data }: { data: Summary }) {
  const [f, setF] = useState({ category: '', detection: '', severity: '', runtime: '' });
  const categories = [...new Set(data.risks.map(r => r.category))];
  const rows = data.risks.filter(r => (!f.category || r.category === f.category) && (!f.detection || r.detection_status === f.detection) && (!f.severity || r.severity === f.severity) && (!f.runtime || String(r.runtime_validation_required) === f.runtime));
  return <>
    <p className="fine-print">Each indicator is found in bytecode (its detection status); what it could cause is always reasoned (inferred). A missing mechanism is not proof that the mechanism is absent.</p>
    <div className="insight-toolbar">
      <select aria-label="Risk category" value={f.category} onChange={e => setF({ ...f, category: e.target.value })}><option value="">All categories</option>{categories.map(c => <option key={c} value={c}>{data.taxonomy.nonfunctional[c]?.label || pretty(c)}</option>)}</select>
      <select aria-label="Risk detection status" value={f.detection} onChange={e => setF({ ...f, detection: e.target.value })}><option value="">Any detection status</option><option>DETECTED</option><option>INFERRED</option></select>
      <select aria-label="Risk severity" value={f.severity} onChange={e => setF({ ...f, severity: e.target.value })}><option value="">Any severity</option><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select>
      <select aria-label="Runtime validation" value={f.runtime} onChange={e => setF({ ...f, runtime: e.target.value })}><option value="">Runtime validation: any</option><option value="true">Needs runtime validation</option><option value="false">Does not need it</option></select>
      <span className="muted">{rows.length} risk indicators</span></div>
    {!rows.length ? <NotAvailable reason={data.risks.length ? 'No risk indicator matches these filters.' : 'No risk rule in responsibility-rules.yaml found an indicator in this application.'} /> :
      <ul className="resp-risks">{rows.map(r => <li key={r.id}><Expandable summary={<><span className={'status-pill ' + r.severity.toLowerCase()}>{r.severity}</span> <strong>{r.title}</strong> <span className="muted">({r.detection_status.toLowerCase()}; {r.affected_count} {r.affected_count === 1 ? 'component' : 'components'})</span></>}>
        <p>{r.description}.</p>
        <p><strong>Consequence (inferred, {r.confidence.level.toLowerCase()} confidence):</strong> {r.consequence}</p>
        <p><strong>Potential impact on modernization:</strong> {r.potential_impact}</p>
        <p><strong>Investigate:</strong> {r.investigate} {r.runtime_validation_required ? 'This needs runtime validation (see the Performance tab in Dynamic analysis).' : 'This can be settled from the code and the design, without a JVM run.'}</p>
        <p className="fine-print">{r.priority_basis}. Confidence basis: {r.confidence.basis}.</p>
        <p>{r.affected_components.slice(0, 8).map(c => <span key={c} className="resp-chip detected"><NodeLink id={c} /></span>)}</p></Expandable></li>)}</ul>}
  </>;
}

function Method({ data }: { data: Summary }) {
  return <>
    <section className="panel insight-panel"><h3>How classes are classified</h3><ul className="detail-list">{Object.entries(data.taxonomy.primary_classifications).map(([k, v]) => <li key={k}><strong>{pretty(k)}:</strong> {v}</li>)}</ul>
      <h4>Detection status</h4><ul className="detail-list">{Object.entries(data.taxonomy.statuses).map(([k, v]) => <li key={k}><strong>{k}:</strong> {v}</li>)}</ul>
      <h4>Confidence (heuristic, not calibrated)</h4><ul className="detail-list">{Object.entries(data.analysis_metadata.confidence.levels).map(([k, v]) => <li key={k}><strong>{k}:</strong> {v}</li>)}</ul></section>
    <section className="panel insight-panel"><h3>Limits of this analysis</h3><ul className="detail-list">{data.limitations.map(l => <li key={l}>{l}</li>)}</ul>
      <p className="fine-print">Engine {data.analysis_metadata.engine_version}, rules {data.analysis_metadata.rules_version}. Source revision: {data.analysis_metadata.source_revision_kind}. {data.validation.evidence_checked} evidence items were checked against the snapshot and {data.validation.evidence_rejected} were rejected.</p></section>
    <section className="panel insight-panel"><h3>What each label does not prove</h3><div className="insight-table-wrap"><table className="insight-table"><thead><tr><th>Label</th><th>Meaning</th><th>Does not prove</th></tr></thead><tbody>
      {[...Object.entries(data.taxonomy.functional), ...Object.entries(data.taxonomy.nonfunctional)].map(([k, v]) => <tr key={k}><td>{v.label}</td><td>{v.description}</td><td>{v.limit}</td></tr>)}</tbody></table></div></section>
  </>;
}
