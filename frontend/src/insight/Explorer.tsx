import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import cytoscape, { type Core } from 'cytoscape';
import { Maximize2 } from 'lucide-react';
import { api } from '../api';
import { PageTitle } from '../components';
import { Expandable, InsightState, NodeLink, NotAvailable, short, useInsight } from './shared';

type GNode = { id: string; kind: string; label: string; full_name: string; package?: string; layer: string; role: string | null; size: number; in_cycle: boolean; debt: string | null; observed: number | boolean | null;
  explanation: { what: string; why_here: string; coverage: string } };
type GEdge = { id: string; source: string; target: string; weight: number; edge_types: Record<string, number>; runtime_calls: number; sources: string[]; explanation: string };
export type GraphView = { level: string; nodes: GNode[]; edges: GEdge[]; layers: { id: string; label: string }[]; external: { total: number; categories: { category: string; label: string; count: number }[] };
  meta: { view: string; nodes_shown: number; nodes_total: number; edges_shown: number; edges_total: number; hidden: string[]; aggregation: string; runtime: string; external: string } };
type Index = { classes: { id: string; name: string; package: string; role: string; layer: string; in_cycle: boolean; debt: string | null; observed: boolean | null }[]; packages: string[]; roles: string[]; runtime_included: boolean };
type Detail = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const DEBT_COLOR: Record<string, string> = { HIGH: '#af584e', MEDIUM: '#98621d', LOW: '#b99a3c', INFO: '#7d8a82' };
const LAYER_FILL: Record<string, string> = { PRESENTATION: '#dbe7f5', SERVICE: '#e4ecd9', DATA_ACCESS: '#f1e6d2', DOMAIN: '#e8dff0', CONFIGURATION: '#e3e6e4', SUPPORT: '#eeeeee' };

/** Layered positions: one row per architecture layer, nodes ordered by package inside a row. */
export function layeredPositions(nodes: GNode[], layers: string[]) {
  const rows = layers.map(layer => nodes.filter(n => n.layer === layer).sort((a, b) => (a.package || '').localeCompare(b.package || '') || a.id.localeCompare(b.id))).filter(r => r.length);
  const width = Math.max(1, ...rows.map(r => r.length));
  const out: Record<string, { x: number; y: number }> = {};
  rows.forEach((row, y) => row.forEach((n, x) => { out[n.id] = { x: (x - (row.length - 1) / 2) * 130 + (width * 130) / 2, y: y * 130 }; }));
  return out;
}

function Canvas({ data, selected, onSelect, onEdge, onDrill }: { data: GraphView; selected: string; onSelect: (id: string) => void; onEdge: (edge: GEdge) => void; onDrill: (id: string) => void }) {
  const box = useRef<HTMLDivElement>(null), cy = useRef<Core | null>(null);
  const handlers = useRef({ onSelect, onEdge, onDrill }); handlers.current = { onSelect, onEdge, onDrill };
  useEffect(() => {
    if (!box.current) return;
    const positions = layeredPositions(data.nodes, data.layers.map(l => l.id));
    const maxWeight = Math.max(1, ...data.edges.map(e => e.weight));
    const instance = cytoscape({ container: box.current, minZoom: .1, maxZoom: 3, wheelSensitivity: .25,
      elements: [...data.nodes.map(n => ({ data: { id: n.id, label: n.label, fill: LAYER_FILL[n.layer] || '#eee', size: 26 + Math.min(34, Math.sqrt(n.size) * 6), cycle: n.in_cycle ? 1 : 0, debt: n.debt || '', observed: n.observed === null ? 'unknown' : n.observed ? 'yes' : 'no', kind: n.kind }, position: positions[n.id] })),
        ...data.edges.map(e => ({ data: { id: e.id, source: e.source, target: e.target, width: 1 + (4 * e.weight) / maxWeight, runtime: e.sources.includes('runtime') ? 1 : 0, staticOnly: e.sources.includes('static') ? 1 : 0 } }))],
      layout: Object.keys(positions).length ? { name: 'preset' } : { name: 'cose' },
      style: [
        { selector: 'node', style: { 'background-color': 'data(fill)', label: 'data(label)', width: 'data(size)', height: 'data(size)', 'font-size': 11, 'text-valign': 'bottom', 'text-margin-y': 5, color: '#26332c', 'border-width': 2, 'border-color': '#7d8a82', shape: 'round-rectangle' } },
        { selector: 'node[kind = "PACKAGE"]', style: { shape: 'rectangle' } },
        { selector: 'node[observed = "yes"]', style: { 'border-color': '#2d634b', 'border-width': 3 } },
        { selector: 'node[observed = "no"]', style: { 'border-style': 'dashed' } },
        { selector: 'node[cycle = 1]', style: { 'underlay-color': '#af584e', 'underlay-opacity': .25, 'underlay-padding': 6 } },
        { selector: 'node[debt = "HIGH"]', style: { 'border-color': DEBT_COLOR.HIGH, 'border-width': 4 } },
        { selector: 'node[debt = "MEDIUM"]', style: { 'border-color': DEBT_COLOR.MEDIUM, 'border-width': 4 } },
        { selector: 'node[debt = "LOW"]', style: { 'border-color': DEBT_COLOR.LOW, 'border-width': 3 } },
        { selector: 'edge', style: { width: 'data(width)', 'line-color': '#a9b8af', 'target-arrow-color': '#a9b8af', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier', opacity: .75 } },
        { selector: 'edge[staticOnly = 1]', style: { 'line-style': 'dashed' } },
        { selector: 'edge[runtime = 1]', style: { 'line-style': 'solid', 'line-color': '#2d634b', 'target-arrow-color': '#2d634b' } },
        { selector: '.faded', style: { opacity: .12 } },
        { selector: 'node:selected', style: { 'border-color': '#1a2a22', 'border-width': 5 } }] });
    instance.on('tap', 'node', e => handlers.current.onSelect(e.target.id()));
    instance.on('dbltap', 'node', e => handlers.current.onDrill(e.target.id()));
    instance.on('tap', 'edge', e => { const edge = data.edges.find(x => x.id === e.target.id()); if (edge) handlers.current.onEdge(edge); });
    cy.current = instance; instance.fit(undefined, 30);
    return () => { instance.destroy(); cy.current = null; };
  }, [data]);
  useEffect(() => { // highlight the neighbourhood of the selected node
    const c = cy.current; if (!c) return;
    c.elements().removeClass('faded');
    const node = selected ? c.getElementById(selected) : null;
    if (node && node.nonempty()) { c.elements().not(node.closedNeighborhood()).addClass('faded'); node.select(); }
  }, [selected, data]);
  return <div className="explorer-canvas-wrap"><div ref={box} className="explorer-canvas" role="img" aria-label="Dependency graph" /><button className="graph-fit" aria-label="Fit graph" onClick={() => cy.current?.fit(undefined, 30)}><Maximize2 size={16} /></button></div>;
}

function Legend() {
  return <details className="explorer-legend" open><summary>Legend</summary><div>
    <div><strong>Row / fill colour</strong> — architecture layer: {Object.entries(LAYER_FILL).map(([k, v]) => <span key={k} className="legend-chip" style={{ background: v }}>{k.toLowerCase().replace('_', ' ')}</span>)}</div>
    <div><strong>Shape</strong> — rectangle: package · rounded rectangle: class · size grows with the number of classes or methods.</div>
    <div><strong>Border colour</strong> — highest technical-debt severity: <span className="legend-chip" style={{ borderColor: DEBT_COLOR.HIGH }}>high</span><span className="legend-chip" style={{ borderColor: DEBT_COLOR.MEDIUM }}>medium</span><span className="legend-chip" style={{ borderColor: DEBT_COLOR.LOW }}>low</span></div>
    <div><strong>Red glow</strong> — member of a cyclic group.</div>
    <div><strong>Runtime coverage</strong> — green border: observed in the selected sessions · dashed border: not observed (not the same as unused) · grey: no session selected.</div>
    <div><strong>Edges</strong> — arrow points from dependent to dependency · dashed: static only · solid green: also observed at runtime · thickness: number of references.</div></div></details>;
}

function WhatAmILookingAt({ meta, external }: { meta: GraphView['meta']; external: GraphView['external'] }) {
  return <section className="explorer-what" aria-label="What am I looking at?"><h3>What am I looking at?</h3>
    <p><strong>{meta.view}.</strong> Showing {meta.nodes_shown} of {meta.nodes_total} nodes and {meta.edges_shown} of {meta.edges_total} edges.</p>
    <ul><li>{meta.aggregation}</li><li>{meta.runtime}</li><li>{meta.external}</li>{meta.hidden.map(h => <li key={h} className="hidden-note">{h}</li>)}</ul>
    {external.total > 0 && <Expandable summary={<strong>External and unresolved ({external.total})</strong>}><ul className="evidence-list">{external.categories.map(c => <li key={c.category}><strong>{c.count}</strong> — {c.label}</li>)}</ul><p className="fine-print">Open the list below the graph for each name and where it is first referenced.</p></Expandable>}
  </section>;
}

function Unresolved({ analysisId }: { analysisId: string }) {
  const q = useInsight<{ categories: { category: string; label: string; count: number; items: { name: string; reference_count: number; first_reference: Record<string, string> }[] }[] }>(analysisId, 'unresolved');
  return <InsightState query={q}>{() => <section className="panel insight-panel"><h3>External and unresolved</h3>
    {q.data!.categories.map(c => <Expandable key={c.category} summary={<span><strong>{c.count}</strong> {c.label}</span>}>
      <table className="insight-table"><thead><tr><th>Name</th><th>References</th><th>First referenced by</th></tr></thead><tbody>{c.items.slice(0, 50).map(i => <tr key={i.name}><td><code>{i.name}</code></td><td>{i.reference_count}</td>
        <td>{i.first_reference.kind === 'STATIC' ? <><NodeLink id={i.first_reference.source} /> ({i.first_reference.dependency_type.toLowerCase().replace('_', ' ')})</> : `runtime span node ${i.first_reference.runtime_node_id}`}</td></tr>)}</tbody></table></Expandable>)}
    {!q.data!.categories.length && <p className="muted">No external or unresolved names.</p>}</section>}</InsightState>;
}

export function DetailPanel({ analysisId, id, onNavigate, sessions }: { analysisId: string; id: string; onNavigate: (id: string) => void; sessions: string }) {
  const q = useQuery({ queryKey: ['insight', analysisId, 'node', id, sessions], queryFn: () => api<Detail>(`/analyses/${analysisId}/insight/node?id=${encodeURIComponent(id)}${sessions ? '&runtime_session_ids=' + sessions : ''}`) });
  const [why, setWhy] = useState<{ source: string; target: string } | null>(null);
  if (q.isPending) return <aside className="node-inspector">Loading details…</aside>;
  if (q.error || !q.data) return <aside className="node-inspector" role="alert">{String(q.error)}</aside>;
  const d = q.data;
  if (d.kind === 'UNKNOWN') return <aside className="node-inspector"><h3>{short(d.id)}</h3><NotAvailable reason={d.reason} />{d.external && <p>{d.external.explanation}</p>}</aside>;
  const link = (item: { id: string; name: string; reference_count: number; edge_types: Record<string, number>; runtime_calls: number }, outgoing: boolean) => <li key={item.id}>
    <button className="node-link" onClick={() => onNavigate(item.id)} title={item.id}>{item.name}</button> <small>{item.reference_count} refs · {Object.keys(item.edge_types).map(k => k.toLowerCase().replace('_', ' ')).join(', ')}{item.runtime_calls ? ` · ${item.runtime_calls} runtime calls` : ''}</small>
    <button className="why-link" onClick={() => setWhy(outgoing ? { source: d.id, target: item.id } : { source: item.id, target: d.id })}>why?</button></li>;
  return <aside className="node-inspector" aria-label={'Details for ' + d.id}>
    <nav className="breadcrumb" aria-label="Breadcrumb">{(d.breadcrumb || []).map((b: { id: string; label: string }, i: number) => <span key={b.id}>{i > 0 && ' › '}<button className="node-link" onClick={() => onNavigate(b.id)}>{b.label}</button></span>)}</nav>
    <h3 title={d.id}>{d.name}</h3><p className="fine-print">{d.kind.toLowerCase()} · {d.id}</p>
    <p className="summary">{d.summary}</p>
    {d.what && <p><strong>What it is:</strong> {d.what.plain} <span className="fine-print">Evidence: {d.what.reason || d.what.roles && Object.entries(d.what.roles).map(([k, v]) => `${v} ${k.toLowerCase()}`).join(', ')}</span></p>}
    {d.size && <p><strong>Size:</strong> {Object.entries(d.size).filter(([, v]) => typeof v === 'number').map(([k, v]) => `${v} ${k.replace('_', ' ')}`).join(' · ')}</p>}
    {d.signature && <p><code>{d.signature}</code> · {d.bytecode_size} bytes · ~{d.complexity} paths{d.line_range ? ` · lines ${d.line_range[0]}–${d.line_range[1]}` : ''}</p>}
    {d.depends_on && <Expandable defaultOpen summary={<strong>Depends on ({d.depends_on.length})</strong>}><ul className="detail-list">{d.depends_on.slice(0, 15).map((x: never) => link(x, true))}</ul></Expandable>}
    {d.depended_on_by && <Expandable summary={<strong>Depended on by ({d.depended_on_by.length})</strong>}><ul className="detail-list">{d.depended_on_by.slice(0, 15).map((x: never) => link(x, false))}</ul></Expandable>}
    {why && <WhyConnected analysisId={analysisId} source={why.source} target={why.target} sessions={sessions} onClose={() => setWhy(null)} />}
    {d.calls && <Expandable summary={<strong>Calls ({d.calls.length}) · called by ({d.called_by.length})</strong>}><ul className="call-sites">{d.calls.map((c: { target: string; label: string; line: number }) => <li key={c.target + c.line}>{c.label}{c.line ? ` (line ${c.line})` : ''}</li>)}{d.external_calls?.map((c: { label: string; owner: string; line: number }, i: number) => <li key={'x' + i}>{c.label} <span className="muted">[{c.owner}]</span></li>)}</ul><ul className="call-sites">{d.called_by.map((c: { source: string; label: string }) => <li key={c.source}>← {c.label}</li>)}</ul></Expandable>}
    {d.methods && <Expandable summary={<strong>Methods ({d.methods.length})</strong>}><ul className="call-sites">{d.methods.map((m: { id: string; label: string; bytecode_size: number; complexity: number; entry_point: string | null }) => <li key={m.id}><button className="node-link" onClick={() => onNavigate(m.id)}>{m.label}</button> {m.bytecode_size !== null && <small>{m.bytecode_size} B · ~{m.complexity} paths</small>}{m.entry_point && <strong> · entry point: {m.entry_point}</strong>}</li>)}</ul></Expandable>}
    {d.classes && <Expandable summary={<strong>Classes ({d.classes.length})</strong>}><ul className="detail-list">{d.classes.map((c: { id: string; name: string; role: string }) => <li key={c.id}><button className="node-link" onClick={() => onNavigate(c.id)}>{c.name}</button> <small>{c.role.toLowerCase()}</small></li>)}</ul></Expandable>}
    {d.cycles && <p><strong>Cycles:</strong> {d.cycles.length ? d.cycles.map((c: { id: string; size: number; level: string; members: string[] }) => `${c.level.toLowerCase()} group of ${c.size} (${c.members.slice(0, 4).map(short).join(', ')}${c.members.length > 4 ? '…' : ''})`).join('; ') : 'none'}</p>}
    {d.entry_points && <p><strong>Entry points:</strong> {d.entry_points.length ? d.entry_points.map((e: { description: string }) => e.description).join(' · ') : 'none'}</p>}
    {d.coverage && <p><strong>Runtime:</strong> {d.coverage.status === 'AVAILABLE' ? `${d.coverage.observed} of ${d.coverage.total} classes observed. ${d.coverage.note}` : d.coverage.reason}</p>}
    {d.debt && <Expandable summary={<strong>Technical debt ({d.debt.length})</strong>}>{d.debt.length ? <ul className="detail-list">{d.debt.map((f: { id: string; severity: string; title: string; explanation: { plain: string } }) => <li key={f.id}><span className={'status-pill ' + f.severity.toLowerCase()}>{f.severity}</span> {f.title}: {f.explanation.plain}</li>)}</ul> : <p className="muted">No debt rule fired.</p>}</Expandable>}
    {d.aging && <p><strong>Aging technology:</strong> {d.aging.length ? d.aging.map((a: { technology: string; status: string }) => `${a.technology} (${a.status})`).join(', ') : 'none detected'}</p>}
    {d.external_dependencies?.length > 0 && <Expandable summary={<strong>External libraries used ({d.external_dependencies.length})</strong>}><ul className="call-sites">{d.external_dependencies.map((x: { id: string; reference_count: number }) => <li key={x.id}>{x.id} ×{x.reference_count}</li>)}</ul></Expandable>}
  </aside>;
}

function WhyConnected({ analysisId, source, target, sessions, onClose }: { analysisId: string; source: string; target: string; sessions: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ['insight', analysisId, 'connection', source, target, sessions], queryFn: () => api<Detail>(`/analyses/${analysisId}/insight/connection?source=${encodeURIComponent(source)}&target=${encodeURIComponent(target)}${sessions ? '&runtime_session_ids=' + sessions : ''}`) });
  return <section className="why-connected" aria-label="Why is this connected"><header><strong>Why is {short(source)} connected to {short(target)}?</strong><button className="secondary-button" onClick={onClose}>Close</button></header>
    {q.isPending ? <p>Loading…</p> : q.data && <><p>{q.data.explanation}</p>
      {q.data.references ? <ul className="call-sites">{q.data.references.map((r: { text: string; line: number | null }, i: number) => <li key={i}>{r.text}{r.line ? ` (line ${r.line})` : ''}</li>)}{q.data.references.length === 0 && <li>Bytecode references are not available for this analysis.</li>}</ul> :
        <ul className="call-sites">{q.data.pairs.map((p: { source: string; target: string; edge_types?: Record<string, number>; references: { text: string }[] }) => <li key={p.source + p.target}>{short(p.source)} → {short(p.target)}: {p.references[0]?.text || Object.keys(p.edge_types || {}).join(', ')}</li>)}</ul>}</>}</section>;
}

export function ArchitectureExplorer({ analysisId, focusId = '', sessions = '' }: { analysisId: string; focusId?: string; sessions?: string }) {
  const [level, setLevel] = useState<'package' | 'class'>('package'), [pkg, setPkg] = useState(''), [min, setMin] = useState(1), [selected, setSelected] = useState('');
  const [search, setSearch] = useState(''), [role, setRole] = useState(''), [coverage, setCoverage] = useState(''), [debt, setDebt] = useState(''), [cyc, setCyc] = useState(false);
  const [edge, setEdge] = useState<GEdge | null>(null);
  const q = `?level=${level}&min_weight=${min}${pkg ? '&package=' + encodeURIComponent(pkg) : ''}${sessions ? '&runtime_session_ids=' + sessions : ''}`;
  const graph = useQuery({ queryKey: ['insight', analysisId, 'graph', q], queryFn: () => api<GraphView>(`/analyses/${analysisId}/insight/graph${q}`) });
  const index = useInsight<Index>(analysisId, 'index' + (sessions ? '?runtime_session_ids=' + sessions : ''));
  useEffect(() => { // open a node requested from another page
    if (!focusId || !index.data) return;
    const owner = focusId.split('#')[0];
    const cls = index.data.classes.find(c => c.id === owner);
    if (cls) { setLevel('class'); setPkg(cls.package); }
    else if (index.data.packages.includes(owner)) { setLevel('package'); setPkg(''); }
    setSelected(focusId);
  }, [focusId, index.data]);
  const matching = useMemo(() => {
    if (!index.data) return new Set<string>();
    const text = search.toLowerCase();
    const ok = index.data.classes.filter(c => (!text || c.id.toLowerCase().includes(text)) && (!role || c.role === role) && (!debt || (debt === 'any' ? !!c.debt : c.debt === debt)) && (!cyc || c.in_cycle) && (!coverage || (coverage === 'observed' ? c.observed === true : c.observed === false)));
    return new Set(level === 'class' ? ok.map(c => c.id) : ok.map(c => c.package));
  }, [index.data, search, role, debt, cyc, coverage, level]);
  const filtering = !!(search || role || debt || cyc || coverage);
  const data = useMemo(() => graph.data && filtering ? { ...graph.data, nodes: graph.data.nodes.filter(n => matching.has(n.id)), edges: graph.data.edges.filter(e => matching.has(e.source) && matching.has(e.target)) } : graph.data, [graph.data, filtering, matching]);
  function navigate(id: string) {
    setEdge(null); setSelected(id);
    const owner = id.split('#')[0];
    const cls = index.data?.classes.find(c => c.id === owner);
    if (cls && level === 'package') { setLevel('class'); setPkg(cls.package); }
  }
  function drill(id: string) { if (level === 'package') { setLevel('class'); setPkg(id); setSelected(''); } }
  return <>
    <PageTitle eyebrow="ARCHITECTURE EXPLORER" title="See how everything connects — and why." description="Click a node for its role, dependencies, cycles, entry points, coverage and debt. Click an edge, or “why?”, for the exact code references behind it." />
    <div className="insight-toolbar">
      <div className="segmented" role="group" aria-label="Graph level"><button className={level === 'package' ? 'selected' : ''} onClick={() => { setLevel('package'); setPkg(''); }}>Packages</button><button className={level === 'class' ? 'selected' : ''} onClick={() => setLevel('class')}>Classes</button></div>
      {level === 'class' && <select aria-label="Package" value={pkg} onChange={e => setPkg(e.target.value)}><option value="">All packages</option>{index.data?.packages.map(p => <option key={p}>{p}</option>)}</select>}
      <input aria-label="Search classes" placeholder="Search by name…" value={search} onChange={e => setSearch(e.target.value)} />
      <select aria-label="Filter by role" value={role} onChange={e => setRole(e.target.value)}><option value="">Any role</option>{index.data?.roles.map(r => <option key={r} value={r}>{r.toLowerCase().replace('_', ' ')}</option>)}</select>
      <select aria-label="Filter by coverage" value={coverage} onChange={e => setCoverage(e.target.value)} disabled={!index.data?.runtime_included} title={index.data?.runtime_included ? '' : 'Select a runtime session to filter by coverage'}><option value="">Any coverage</option><option value="observed">Observed</option><option value="unobserved">Not observed</option></select>
      <select aria-label="Filter by debt" value={debt} onChange={e => setDebt(e.target.value)}><option value="">Any debt</option><option value="any">Has debt</option><option value="HIGH">High</option><option value="MEDIUM">Medium</option><option value="LOW">Low</option></select>
      <label><input type="checkbox" checked={cyc} onChange={e => setCyc(e.target.checked)} /> In a cycle</label>
      <label>Min. references <input type="range" min={1} max={10} value={min} onChange={e => setMin(+e.target.value)} aria-label="Minimum references per edge" /> {min}</label>
    </div>
    <InsightState query={graph}>{() => data && <div className="explorer-layout">
      <div><Canvas data={data} selected={selected} onSelect={id => { setEdge(null); setSelected(id); }} onEdge={setEdge} onDrill={drill} />
        {filtering && <p className="fine-print">Filters active: {data.nodes.length} of {graph.data!.nodes.length} nodes match.</p>}
        {edge && <section className="why-connected"><strong>{edge.explanation}</strong><div className="fine-print">Sources: {edge.sources.join(' + ')}</div><button className="node-link" onClick={() => setSelected(edge.source)}>Open {short(edge.source)}</button></section>}
        <Legend /><WhatAmILookingAt meta={graph.data!.meta} external={graph.data!.external} /></div>
      <DetailPanel analysisId={analysisId} id={selected || 'system'} onNavigate={navigate} sessions={sessions} />
    </div>}</InsightState>
    <Unresolved analysisId={analysisId} />
  </>;
}
