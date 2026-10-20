import { useState } from 'react';
import { PageTitle } from '../components';
import { AiExplain, Expandable, ExplanationLayers, InsightState, NodeLink, NotAvailable, openNode, short, useInsight } from './shared';

export type CycleEdge = { id: string; source: string; target: string; edge_types: Record<string, number>; dominant_type: string; reference_count: number; runtime_calls: number; sources: string[];
  references?: { kind: string; text: string; line?: number | null }[]; class_pairs?: { source: string; target: string; edge_types: Record<string, number>; references: { text: string }[] }[]; class_pair_count?: number };
export type CyclePath = { id: string; members: string[]; size: number; edges: CycleEdge[]; explanation: { technical: string; plain: string }; sources: string[] };
export type CutCandidate = { rank: number; source: string; target: string; edge_types: Record<string, number>; reference_count: number; runtime_calls: number; against_layering: boolean; cycles_broken: number; breaks_whole_group: boolean; why: string; label: string };
export type CycleGroup = { id: string; level: 'CLASS' | 'PACKAGE'; members: string[]; size: number; internal_edge_count: number; cycles: CyclePath[]; cycle_count_listed: number; enumeration_truncated: boolean;
  packages: string[]; layers: string[]; severity: string; expected_entity_association: boolean; overlapping: boolean; cut_candidates: CutCandidate[]; explanation: { technical: string; plain: string } };
export type CycleResult = { groups: CycleGroup[]; class_group_count: number; package_group_count: number; nested_or_self_references_ignored: number; method: Record<string, string>; runtime_included: boolean };

const TYPE_LABEL: Record<string, string> = { METHOD_CALL: 'calls', FIELD_TYPE: 'field', INHERITANCE: 'extends', INTERFACE: 'implements', PARAMETER_TYPE: 'parameter', RETURN_TYPE: 'returns', ANNOTATION: 'annotation', GENERIC_TYPE: 'type argument', EXCEPTION: 'throws', TYPE_REFERENCE: 'uses', OTHER: 'depends' };

/** Small loop diagram: members on a circle in cycle order, one arrow per loop edge. */
export function CycleDiagram({ cycle, level }: { cycle: CyclePath; level: string }) {
  const n = cycle.members.length, w = n === 2 ? 340 : 360, h = n === 2 ? 130 : 260, r = n === 2 ? 0 : 92;
  const pos = cycle.members.map((_, i) => n === 2 ? { x: i === 0 ? 70 : w - 70, y: h / 2 } : { x: w / 2 + r * Math.cos(-Math.PI / 2 + (2 * Math.PI * i) / n), y: h / 2 + r * Math.sin(-Math.PI / 2 + (2 * Math.PI * i) / n) });
  const label = (name: string) => level === 'PACKAGE' ? name.split('.').slice(-2).join('.') : short(name);
  return <svg className="cycle-diagram" viewBox={`0 0 ${w} ${h}`} role="img" aria-label={'Cycle ' + cycle.members.map(label).join(' to ') + ' back to ' + label(cycle.members[0])}>
    <defs><marker id={'arrow-' + cycle.id} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="currentColor" /></marker></defs>
    {cycle.edges.map((edge, i) => {
      const a = pos[i], b = pos[(i + 1) % n];
      const bend = n === 2 ? (i === 0 ? -34 : 34) : 18;
      const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2, dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
      const cx = mx - (dy / len) * bend, cy = my + (dx / len) * bend;
      const shrink = (p: { x: number; y: number }, q: { x: number; y: number }) => { const d = Math.hypot(q.x - p.x, q.y - p.y) || 1; return { x: p.x + ((q.x - p.x) / d) * 30, y: p.y + ((q.y - p.y) / d) * 30 }; };
      const s = shrink(a, { x: cx, y: cy }), t = shrink(b, { x: cx, y: cy });
      const runtimeOnly = !edge.sources.includes('static');
      return <g key={edge.id} className={'cycle-edge ' + (runtimeOnly ? 'runtime-only' : '')}>
        <path d={`M${s.x},${s.y} Q${cx},${cy} ${t.x},${t.y}`} fill="none" stroke="currentColor" strokeWidth={1.6} strokeDasharray={runtimeOnly ? '5 4' : undefined} markerEnd={`url(#arrow-${cycle.id})`} />
        <text x={cx} y={cy - 4} textAnchor="middle">{TYPE_LABEL[edge.dominant_type] || edge.dominant_type}{edge.runtime_calls ? ` · ${edge.runtime_calls} calls` : ''}</text>
      </g>;
    })}
    {cycle.members.map((member, i) => <g key={member} className="cycle-node" transform={`translate(${pos[i].x},${pos[i].y})`} onClick={() => openNode(member)} role="button" tabIndex={0} onKeyDown={e => { if (e.key === 'Enter') openNode(member); }}>
      <title>{member}</title><rect x={-56} y={-15} width={112} height={30} rx={7} /><text textAnchor="middle" y={4}>{label(member).slice(0, 18)}</text>
    </g>)}
  </svg>;
}

function EdgeTable({ cycle, level }: { cycle: CyclePath; level: string }) {
  return <table className="insight-table"><thead><tr><th>From → to</th><th>Edge types</th><th>Source</th><th>What creates the dependency</th></tr></thead><tbody>
    {cycle.edges.map(edge => <tr key={edge.id}>
      <td><NodeLink id={edge.source} label={level === 'PACKAGE' ? edge.source : undefined} /> → <NodeLink id={edge.target} label={level === 'PACKAGE' ? edge.target : undefined} /></td>
      <td>{Object.entries(edge.edge_types).map(([k, v]) => `${TYPE_LABEL[k] || k} ×${v}`).join(', ')}</td>
      <td>{edge.sources.join(' + ')}{edge.runtime_calls ? ` (${edge.runtime_calls} calls)` : ''}</td>
      <td>{edge.references ? (edge.references.length ? <ul className="call-sites">{edge.references.map((r, i) => <li key={i}>{r.text}{r.line ? ` (line ${r.line})` : ''}</li>)}</ul> : <span className="muted">Bytecode references are not available for this analysis.</span>) :
        <ul className="call-sites">{(edge.class_pairs || []).map((p, i) => <li key={i}>{short(p.source)} → {short(p.target)}{p.references[0] ? `: ${p.references[0].text}` : ''}</li>)}{(edge.class_pair_count || 0) > (edge.class_pairs || []).length && <li>… {(edge.class_pair_count || 0) - (edge.class_pairs || []).length} more class pairs</li>}</ul>}</td>
    </tr>)}
  </tbody></table>;
}

function GroupCard({ group, analysisId }: { group: CycleGroup; analysisId: string }) {
  return <section className="panel insight-panel">
    <header className="insight-panel-head"><span className={'status-pill ' + group.severity.toLowerCase()}>{group.severity}</span>
      <h3>{group.size} {group.level === 'CLASS' ? 'classes' : 'packages'} in a cyclic group{group.overlapping ? ` · ${group.cycle_count_listed} overlapping cycles` : ''}</h3></header>
    <p className="fine-print">Members: {group.members.map(m => <span key={m}><NodeLink id={m} label={group.level === 'PACKAGE' ? m : undefined} /> </span>)}</p>
    {group.level === 'CLASS' && <p className="fine-print">Packages crossed: {group.packages.join(', ')}{group.layers.length ? ` · layers: ${group.layers.map(l => l.toLowerCase().replace('_', ' ')).join(', ')}` : ''}</p>}
    <ExplanationLayers explanation={group.explanation} />
    {group.enumeration_truncated && <p className="fine-print">The list of elementary cycles is bounded; the group membership above is complete.</p>}
    {group.cycles.map((cycle, index) => <Expandable key={cycle.id} defaultOpen={index === 0} summary={<strong>Cycle {index + 1}: {cycle.members.map(m => group.level === 'PACKAGE' ? m : short(m)).join(' → ')} → {group.level === 'PACKAGE' ? cycle.members[0] : short(cycle.members[0])}</strong>}>
      <div className="cycle-layout"><CycleDiagram cycle={cycle} level={group.level} /><ExplanationLayers explanation={cycle.explanation} /></div>
      <EdgeTable cycle={cycle} level={group.level} />
      <AiExplain analysisId={analysisId} path="cycles/explain" targetId={cycle.id} title="AI plain-language rewrite (optional, must cite these edges)" />
    </Expandable>)}
    <h4>Which dependency to cut first</h4>
    {group.cut_candidates.length ? <table className="insight-table"><thead><tr><th>#</th><th>Dependency</th><th>Breaks</th><th>Why it is suggested</th></tr></thead><tbody>
      {group.cut_candidates.map(c => <tr key={c.source + c.target}><td>{c.rank}</td><td><NodeLink id={c.source} label={group.level === 'PACKAGE' ? c.source : undefined} /> → <NodeLink id={c.target} label={group.level === 'PACKAGE' ? c.target : undefined} /></td><td>{c.breaks_whole_group ? 'all cycles in this group' : `${c.cycles_broken} listed cycle${c.cycles_broken === 1 ? '' : 's'}`}</td><td>{c.why}<div className="fine-print">{c.label}</div></td></tr>)}
    </tbody></table> : <p className="muted">No candidates computed.</p>}
  </section>;
}

export function CircularDependencies({ analysisId }: { analysisId: string }) {
  const query = useInsight<CycleResult>(analysisId, 'cycles');
  const [level, setLevel] = useState('');
  return <>
    <PageTitle eyebrow="CIRCULAR DEPENDENCIES" title="Which parts cannot change independently?" description="Loop = classes in order, each step backed by a code reference (field, call, parameter or inheritance)." />
    <InsightState query={query}>{() => {
      const data = query.data!;
      const shown = data.groups.filter(g => !level || g.level === level);
      return <>
        <div className="insight-cards"><article><strong>{data.class_group_count}</strong><span>class-level cyclic groups</span></article><article><strong>{data.package_group_count}</strong><span>package-level cyclic groups</span></article><article><strong>{data.nested_or_self_references_ignored}</strong><span>nested-class and self references = ignored, not cycles</span></article></div>
        <Expandable summary={<span>How cycles are found</span>}><ul className="evidence-list">{Object.values(data.method).map(v => <li key={v}>{v}</li>)}</ul><p className="fine-print">Runtime evidence {data.runtime_included ? 'is included: runtime-only edges are dashed.' : 'is not measured (no runtime session selected).'}</p></Expandable>
        <div className="insight-toolbar"><label>Level <select aria-label="Cycle level" value={level} onChange={e => setLevel(e.target.value)}><option value="">Classes and packages</option><option value="CLASS">Classes</option><option value="PACKAGE">Packages</option></select></label></div>
        {shown.length ? shown.map(group => <GroupCard key={group.id} group={group} analysisId={analysisId} />) : <NotAvailable reason={data.groups.length ? 'No cycles at this level.' : 'No circular dependencies were found: no strongly connected component with 2 or more members exists in the class or package graphs.'} />}
      </>;
    }}</InsightState>
  </>;
}
