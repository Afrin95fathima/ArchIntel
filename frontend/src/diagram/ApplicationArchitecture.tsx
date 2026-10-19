import { useMemo, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { PageTitle, Tabs } from '../components';
import { DetailPanel } from '../insight/Explorer';
import { InsightState, NotAvailable, useInsight } from '../insight/shared';
import { DiagramViewer } from './Viewer';
import { layoutHld, hldMermaid, type HldData } from './hld';
import { layoutLld, layoutSequence, type LldData, type Seq } from './lld';
import './diagram.css';

type Selection = { type: 'node'; id: string } | { type: 'edge'; source: string; target: string; text: string } | null;

function Legend({ items }: { items: ReactNode[] }) {
  return <details className="explorer-legend" open><summary>Legend</summary><ul className="legend-list">{items.map((i, n) => <li key={n}>{i}</li>)}</ul></details>;
}
const Line = ({ cls, label }: { cls: string; label: string }) => <><svg width="46" height="10" aria-hidden="true"><path d="M2,5 L44,5" className={'edge ' + cls} /></svg> {label}</>;
function HowToRead({ lines, limits }: { lines: string[]; limits?: string[] }) {
  return <details className="explorer-what" open><summary>How to read this diagram</summary><ul>{lines.map(l => <li key={l}>{l}</li>)}</ul>{limits?.length ? <><strong>Limits</strong><ul>{limits.map(l => <li key={l}>{l}</li>)}</ul></> : null}</details>;
}

function EdgeInfo({ analysisId, sel, sessions }: { analysisId: string; sel: Extract<Selection, { type: 'edge' }>; sessions: string }) {
  const q = useQuery({ queryKey: ['insight', analysisId, 'connection', sel.source, sel.target, sessions], queryFn: () => api<{ explanation: string; pairs?: { source: string; target: string; references: { text: string }[] }[]; references?: { text: string }[] }>(`/analyses/${analysisId}/insight/connection?source=${encodeURIComponent(sel.source)}&target=${encodeURIComponent(sel.target)}${sessions ? '&runtime_session_ids=' + sessions : ''}`) });
  return <aside className="node-inspector" aria-label="Dependency details"><h3>Dependency</h3><p>{sel.text}</p>
    {q.data && <><p>{q.data.explanation}</p><ul className="call-sites">{(q.data.pairs || []).slice(0, 25).map(p => <li key={p.source + p.target}>{p.source.split('.').at(-1)} → {p.target.split('.').at(-1)}{p.references[0] ? `: ${p.references[0].text}` : ''}</li>)}{(q.data.references || []).map((r, i) => <li key={i}>{r.text}</li>)}</ul></>}</aside>;
}

export function HighLevel({ analysisId, sessions, onOpen }: { analysisId: string; sessions: string; onOpen: (id: string) => void }) {
  const query = useInsight<HldData & { status: string; reason?: string }>(analysisId, 'diagram/hld' + (sessions ? '?runtime_session_ids=' + sessions : ''));
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [sel, setSel] = useState<Selection>(null);
  return <InsightState query={query}>{() => {
    const data = query.data!;
    if (data.status !== 'AVAILABLE') return <NotAvailable reason={data.reason || 'Not available.'} />;
    return <HldBody data={data} expanded={expanded} setExpanded={setExpanded} sel={sel} setSel={setSel} analysisId={analysisId} sessions={sessions} onOpen={onOpen} />;
  }}</InsightState>;
}

function HldBody({ data, expanded, setExpanded, sel, setSel, analysisId, sessions, onOpen }: { data: HldData; expanded: Set<string>; setExpanded: (s: Set<string>) => void; sel: Selection; setSel: (s: Selection) => void; analysisId: string; sessions: string; onOpen: (id: string) => void }) {
  const layout = useMemo(() => layoutHld(data, expanded), [data, expanded]);
  const edges = new Map(data.edges.map(e => [e.id, e]));
  const toggle = (id: string) => { const next = new Set(expanded); if (next.has(id)) next.delete(id); else next.add(id); setExpanded(next); };
  return <div className="explorer-layout">
    <div>
      <DiagramViewer width={layout.width} height={layout.height} name="archintel-high-level" label="High-level architecture diagram" mermaid={() => hldMermaid(data)}>
        <defs><marker id="hld-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="#6c7d72" /></marker></defs>
        {data.entry_points.length > 0 && <text x={150} y={20} className="diagram-caption">Entry points</text>}
        {layout.routes.map(r => <g key={r.id} className="diagram-hit" onClick={e => { e.stopPropagation(); const edge = edges.get(r.id)!; setSel({ type: 'edge', source: edge.source, target: edge.target, text: edge.explanation }); }}>
          <path d={r.d} className={'edge ' + (r.reverse ? 'reverse' : r.observed ? 'observed' : 'static')} style={{ strokeWidth: r.weight }} markerEnd="url(#hld-arrow)" /><path d={r.d} className="edge-hit" />
          <text x={r.lx} y={r.ly} className="edge-label">{r.label}</text></g>)}
        {layout.boxes.map(b => <g key={b.id} className={'diagram-box ' + b.kind + (sel?.type === 'node' && sel.id === b.id ? ' selected' : '')} onClick={e => { e.stopPropagation(); if (b.kind !== 'entry') setSel({ type: 'node', id: b.id }); }}>
          <title>{b.title} — {b.subtitle}</title>
          <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={b.kind === 'external' ? 22 : 8} className={'box ' + b.kind} />
          <text x={b.x + 14} y={b.y + 24} className="box-title">{b.title.slice(0, Math.floor(b.w / 7))}</text>
          <text x={b.x + 14} y={b.y + 44} className="box-sub">{b.subtitle.slice(0, Math.floor(b.w / 6.2))}</text>
          {b.kind === 'layer' && <text x={b.x + b.w - 14} y={b.y + 24} textAnchor="end" className="expand-link" data-ui onClick={e => { e.stopPropagation(); toggle(b.id); }}>{expanded.has(b.id) ? 'Collapse' : 'Expand packages'}</text>}
          {b.chips.map((c, i) => <g key={c.id} className="chip" onClick={e => { e.stopPropagation(); setSel({ type: 'node', id: c.id }); }}><rect x={b.x + 14 + (i % 3) * 218} y={b.y + 60 + Math.floor(i / 3) * 24} width={208} height={19} rx={9} /><text x={b.x + 22 + (i % 3) * 218} y={b.y + 73 + Math.floor(i / 3) * 24}>{c.label.slice(0, 32)}</text></g>)}
          {b.hiddenChips > 0 && <text x={b.x + 14} y={b.y + b.h - 6} className="box-sub">+{b.hiddenChips} more packages (open the layer for the full list)</text>}
        </g>)}
      </DiagramViewer>
      <Legend items={[<Line cls="observed" label="Observed at runtime (thickness = dependencies)" />, <Line cls="static" label="In the code only (static)" />, <Line cls="reverse" label="Points against the layering" />,
        <><span className="legend-chip layer-chip" /> Layer (rounded rectangle) · <span className="legend-chip ext-chip" /> External system (pill) · top row: entry points</>]} />
      <HowToRead lines={data.how_to_read} limits={data.limitations} />
    </div>
    {sel?.type === 'edge' ? <EdgeInfo analysisId={analysisId} sel={sel} sessions={sessions} /> :
      <DetailPanel analysisId={analysisId} id={sel?.type === 'node' ? sel.id : 'system'} sessions={sessions} onNavigate={id => { if (id.startsWith('layer:') || id.startsWith('external:')) setSel({ type: 'node', id }); else onOpen(id); }} />}
  </div>;
}

export function LowLevel({ analysisId, sessions, onOpen }: { analysisId: string; sessions: string; onOpen: (id: string) => void }) {
  const index = useInsight<{ packages: string[] }>(analysisId, 'index' + (sessions ? '?runtime_session_ids=' + sessions : ''));
  const [pkg, setPkg] = useState('');
  const chosen = pkg || index.data?.packages[0] || '';
  const [sel, setSel] = useState<Selection>(null);
  const [entry, setEntry] = useState('');
  const q = useInsight<LldData & { status: string; reason?: string }>(analysisId, `diagram/lld?package=${encodeURIComponent(chosen)}${sessions ? '&runtime_session_ids=' + sessions : ''}`, !!chosen);
  const seq = useQuery({ queryKey: ['insight', analysisId, 'seq', entry, sessions], queryFn: () => api<Seq>(`/analyses/${analysisId}/insight/diagram/sequence?entry_id=${encodeURIComponent(entry)}${sessions ? '&runtime_session_ids=' + sessions : ''}`), enabled: !!entry });
  return <>
    <div className="insight-toolbar"><label>Component (package) <select aria-label="Component" value={chosen} onChange={e => { setPkg(e.target.value); setSel(null); setEntry(''); }}>{index.data?.packages.map(p => <option key={p}>{p}</option>)}</select></label></div>
    {chosen ? <InsightState query={q}>{() => {
      const data = q.data!;
      if (data.status !== 'AVAILABLE') return <NotAvailable reason={data.reason || 'Not available.'} />;
      const layout = layoutLld(data);
      const edges = new Map(data.edges.map(e => [e.id, e]));
      return <div className="explorer-layout"><div>
        <DiagramViewer width={layout.width} height={layout.height} name={'archintel-' + chosen} label={'Low-level diagram of ' + chosen}>
          <defs><marker id="lld-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="#6c7d72" /></marker></defs>
          {layout.tableRoutes.map(r => <path key={r.id} d={r.d} className="edge static" />)}
          {layout.routes.map(r => <g key={r.id} className="diagram-hit" onClick={e => { e.stopPropagation(); const edge = edges.get(r.id)!; setSel({ type: 'edge', source: edge.source, target: edge.target, text: `${edge.source.split('.').at(-1)} → ${edge.target.split('.').at(-1)}: ${edge.label}${edge.observed ? ` · ${edge.runtime_calls} runtime calls` : ' · static only'}` }); }}>
            <path d={r.d} className={'edge ' + (r.observed ? 'observed' : 'static')} style={{ strokeWidth: r.weight }} markerEnd="url(#lld-arrow)" /><path d={r.d} className="edge-hit" /><text x={r.lx} y={r.ly} className="edge-label">{r.label.slice(0, 28)}</text></g>)}
          {layout.boxes.map(b => <g key={b.id} className={'diagram-box' + (sel?.type === 'node' && sel.id === b.id ? ' selected' : '')} onClick={e => { e.stopPropagation(); setSel({ type: 'node', id: b.id }); }}>
            <title>{b.id} — {b.cls.reason}</title>
            <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={6} className={'box ' + (b.cls.observed === false ? 'unobserved' : '')} />
            <text x={b.x + 10} y={b.y + 20} className="box-title">{b.cls.name.slice(0, 24)}</text>
            <text x={b.x + 10} y={b.y + 36} className="box-sub">{b.cls.role.toLowerCase().replace('_', ' ')} · {b.cls.methods} methods</text>
            {b.cls.entry_points.map((p, i) => <text key={p.id} x={b.x + 10} y={b.y + 54 + i * 15} className="entry-text" onClick={e => { e.stopPropagation(); setEntry(p.id); }}>▶ {p.text.slice(0, 30)}</text>)}
            {b.cls.table && <text x={b.x + 10} y={b.y + b.h - 8} className="box-sub">table: {b.cls.table}</text>}
          </g>)}
          {layout.tables.map(t => <g key={t.id} className="db-table"><rect x={t.x} y={t.y} width={t.w} height={t.h} rx={4} /><text x={t.x + 10} y={t.y + 21}>{t.table}</text><title>Static: {t.entity} @Table(name="{t.table}")</title></g>)}
        </DiagramViewer>
        <Legend items={[<Line cls="observed" label="Observed at runtime" />, <Line cls="static" label="Static only" />, <>▶ marks an entry method; click it for its sequence diagram</>, <>Dashed box border: class not observed in the selected sessions</>, <>Database tables come from @Table annotations{data.runtime_tables.length ? ` and ${data.runtime_tables.length} runtime database spans` : ''}</>]} />
        <HowToRead lines={data.how_to_read} limits={data.limitations} />
        {data.runtime_tables.length > 0 && <section className="panel insight-panel"><h3>Tables touched at runtime</h3><ul>{data.runtime_tables.map(t => <li key={t.id}>{t.operation} {t.table} by {t.caller.split('.').at(-1)} ×{t.calls}</li>)}</ul></section>}
        <section className="panel insight-panel"><h3>Sequence diagram</h3>
          <label>Entry point <select aria-label="Entry point" value={entry} onChange={e => setEntry(e.target.value)}><option value="">Select an entry point…</option>{data.entry_points.map(p => <option key={p.id} value={p.id}>{p.text} — {p.handler}</option>)}</select></label>
          {entry && <InsightState query={seq}>{() => <SequenceView seq={seq.data!} />}</InsightState>}
        </section>
      </div>
      {sel?.type === 'edge' ? <EdgeInfo analysisId={analysisId} sel={sel} sessions={sessions} /> : <DetailPanel analysisId={analysisId} id={sel?.type === 'node' ? sel.id : chosen} sessions={sessions} onNavigate={onOpen} />}</div>;
    }}</InsightState> : <NotAvailable reason="This analysis has no packages." />}
  </>;
}

export function SequenceView({ seq }: { seq: Seq }) {
  if (seq.status !== 'AVAILABLE') return <NotAvailable reason={seq.reason || 'No sequence available.'} />;
  const l = layoutSequence(seq);
  return <>
    <p><span className={'status-pill ' + (seq.origin === 'RUNTIME' ? 'current' : 'aging')}>{seq.origin === 'RUNTIME' ? 'Observed at runtime' : 'Static (not observed)'}</span> {seq.entry}</p>
    <DiagramViewer width={l.width} height={l.height} name="archintel-sequence" label={'Sequence diagram for ' + seq.entry}>
      <defs><marker id="seq-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="#445" /></marker></defs>
      {seq.participants.map(p => <g key={p.id}><rect x={(l.xs.get(p.id) || 0) - l.colW / 2 + 6} y={14} width={l.colW - 12} height={30} rx={6} className="box" /><text x={l.xs.get(p.id)} y={33} textAnchor="middle" className="box-title">{p.label.slice(0, 20)}</text>
        <line x1={l.xs.get(p.id)} x2={l.xs.get(p.id)} y1={44} y2={l.height - 20} className="lifeline" /></g>)}
      {l.messages.map(m => <g key={m.order}>
        <line x1={m.x1} x2={m.x2 + (m.x2 === m.x1 ? 30 : 0)} y1={m.y} y2={m.y} className={'seq-arrow ' + (m.origin === 'runtime' ? 'observed' : 'static') + (m.error ? ' reverse' : '')} markerEnd="url(#seq-arrow)" />
        <text x={(m.x1 + m.x2) / 2 + (m.x2 === m.x1 ? 15 : 0)} y={m.y - 5} textAnchor="middle" className="edge-label">{m.order}. {m.label}{m.duration_ms !== undefined ? ` (${m.duration_ms} ms)` : ''}</text></g>)}
    </DiagramViewer>
    <p className="fine-print">{seq.note}</p></>;
}

export function ApplicationArchitecture({ analysisId, sessions = '', onOpen, blueprint }: { analysisId: string; sessions?: string; onOpen: (id: string) => void; blueprint: ReactNode }) {
  const [tab, setTab] = useState<'hld' | 'lld' | 'domains'>('hld');
  return <>
    <PageTitle eyebrow="APPLICATION ARCHITECTURE" title="How the application is built, layer by layer." description="A high-level view of layers, entry points and external systems, and a low-level view of one component with its sequence diagrams. Everything is drawn from the analysed code and, when selected, runtime evidence." />
    <Tabs label="Architecture views" value={tab} onChange={setTab} items={[{ value: 'hld', label: 'High-level (HLD)' }, { value: 'lld', label: 'Low-level (LLD)' }, { value: 'domains', label: 'Candidate-domain blueprint' }]} />
    {tab === 'hld' && <HighLevel analysisId={analysisId} sessions={sessions} onOpen={onOpen} />}
    {tab === 'lld' && <LowLevel analysisId={analysisId} sessions={sessions} onOpen={onOpen} />}
    {tab === 'domains' && blueprint}
  </>;
}
