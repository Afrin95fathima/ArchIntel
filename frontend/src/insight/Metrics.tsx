import { useMemo, useState } from 'react';
import { PageTitle } from '../components';
import { Formula, InsightState, NodeLink, NotAvailable, short, useInsight } from './shared';

type Indicator = { state: 'ok' | 'near' | 'over' | 'info' | 'unknown'; warn: number | null; over: number | null };
type MetricValue = { value: number | null; indicator: Indicator; inputs?: string[]; input_count?: number; note?: string };
type Row = { id: string; name: string; package?: string; role?: string; layer?: string; class_count?: number; nested_classes?: string[]; metrics: Record<string, MetricValue> };
type Definition = { label: string; formula: string; plain: string; threshold: { warn: number; over: number } | null };
export type MetricsResult = { definitions: Record<string, Definition>; classes: Row[]; packages: Row[]; worst: Record<string, { id: string; value: number; state: string }[]>; rules_version: string; facts_available: boolean; counting: string };

const PACKAGE_COLUMNS = ['package.class_count', 'package.Ca', 'package.Ce', 'package.I', 'package.A', 'package.D', 'package.cycle_groups', 'package.layer_violations', 'package.bytecode_size'];
const CLASS_COLUMNS = ['class.fan_in', 'class.fan_out', 'class.method_count', 'class.field_count', 'class.bytecode_size', 'class.max_method_size', 'class.max_method_complexity', 'class.dependency_count', 'class.cycle_groups', 'class.layer_violations'];
const STATE_LABEL: Record<string, string> = { ok: 'within threshold', near: 'near threshold', over: 'over threshold', info: 'no threshold', unknown: 'not available' };

function Cell({ metric }: { metric: MetricValue }) {
  if (metric.value === null) return <td className="muted" title={metric.note}>n/a</td>;
  return <td><span className={'metric-value ' + metric.indicator.state} title={STATE_LABEL[metric.indicator.state]}>{metric.value}</span></td>;
}

function Detail({ row, definitions, level }: { row: Row; definitions: Record<string, Definition>; level: 'class' | 'package' }) {
  const columns = level === 'class' ? CLASS_COLUMNS : PACKAGE_COLUMNS;
  return <section className="panel insight-panel" aria-label={'Metrics for ' + row.id}>
    <h3><NodeLink id={row.id} label={level === 'package' ? row.id : row.name} /></h3>
    <p className="fine-print" title={row.id}>{row.id}{row.role ? ` · role ${row.role.toLowerCase().replace('_', ' ')}` : ''}{row.nested_classes?.length ? ` · ${row.nested_classes.length} nested classes folded in` : ''}</p>
    <div className="metric-detail-grid">{columns.map(key => {
      const metric = row.metrics[key], definition = definitions[key];
      return <article key={key} className={'metric-card ' + metric.indicator.state}>
        <header><strong>{definition.label}</strong><span className={'metric-value ' + metric.indicator.state}>{metric.value ?? 'n/a'}</span></header>
        <p>{definition.plain}</p>
        <Formula formula={definition.formula} />
        <p className="fine-print">{definition.threshold ? `Threshold: near above ${definition.threshold.warn}, over above ${definition.threshold.over} — ${STATE_LABEL[metric.indicator.state]}.` : 'No threshold: informative only.'}{metric.note ? ' ' + metric.note : ''}</p>
        {metric.inputs && metric.inputs.length > 0 && <details><summary>Inputs ({metric.input_count})</summary><ul className="call-sites">{metric.inputs.map(item => <li key={item}>{item.includes('.') ? <NodeLink id={item} label={level === 'package' && key.endsWith('class_count') ? short(item) : item} /> : item}</li>)}</ul>{(metric.input_count || 0) > metric.inputs.length && <p className="fine-print">Showing {metric.inputs.length} of {metric.input_count}.</p>}</details>}
      </article>;
    })}</div>
  </section>;
}

function Scatter({ packages }: { packages: Row[] }) {
  const points = packages.filter(p => p.metrics['package.D'].value !== null);
  if (!points.length) return <NotAvailable reason="No package has internal dependencies, so instability I and distance D = |A + I - 1| are not measured." />;
  return <svg className="metric-scatter" viewBox="0 0 320 240" role="img" aria-label="Abstractness versus instability for each package">
    <line x1="40" y1="200" x2="300" y2="200" className="axis" /><line x1="40" y1="200" x2="40" y2="20" className="axis" />
    <line x1="40" y1="20" x2="300" y2="200" className="main-sequence" />
    <text x="170" y="232" textAnchor="middle">Instability I</text><text x="14" y="110" transform="rotate(-90 14 110)" textAnchor="middle">Abstractness A</text>
    {points.map(p => { const x = 40 + 260 * (p.metrics['package.I'].value || 0), y = 200 - 180 * (p.metrics['package.A'].value || 0); return <circle key={p.id} cx={x} cy={y} r={5} className={'metric-point ' + p.metrics['package.D'].indicator.state}><title>{`${p.id}: I=${p.metrics['package.I'].value}, A=${p.metrics['package.A'].value}, D=${p.metrics['package.D'].value}`}</title></circle>; })}
  </svg>;
}

export function ArchitectureMetrics({ analysisId }: { analysisId: string }) {
  const query = useInsight<MetricsResult>(analysisId, 'metrics');
  return <>
    <PageTitle eyebrow="ARCHITECTURE METRICS" title="Metrics = measured structure with its formula." description="Metrics per package and class: Ca, Ce, I, A, D, cycles, layer violations, size and bytecode complexity. Click a row for inputs and meaning." />
    <InsightState query={query}>{() => <MetricsBody data={query.data!} />}</InsightState>
  </>;
}

function MetricsBody({ data }: { data: MetricsResult }) {
  const [level, setLevel] = useState<'package' | 'class'>('package');
  const [sort, setSort] = useState(level === 'package' ? 'package.D' : 'class.fan_in');
  const [selected, setSelected] = useState('');
  const [search, setSearch] = useState('');
  const rows = level === 'package' ? data.packages : data.classes;
  const columns = level === 'package' ? PACKAGE_COLUMNS : CLASS_COLUMNS;
  const sortKey = columns.includes(sort) ? sort : columns[1];
  const ordered = useMemo(() => [...rows].filter(r => !search || r.id.toLowerCase().includes(search.toLowerCase())).sort((a, b) => (b.metrics[sortKey].value ?? -1) - (a.metrics[sortKey].value ?? -1) || a.id.localeCompare(b.id)), [rows, sortKey, search]);
  const chosen = rows.find(r => r.id === selected);
  const offenders = Object.entries(data.worst).filter(([key, list]) => key.startsWith(level) && list.some(item => item.state === 'over' || item.state === 'near'));
  return <>
    <p className="fine-print">{data.counting} Thresholds from debt-rules {data.rules_version}.{!data.facts_available && ' Bytecode size and complexity are not available for this analysis (no bytecode facts); run a new analysis.'}</p>
    <div className="insight-toolbar"><div className="segmented" role="group" aria-label="Metric level"><button className={level === 'package' ? 'selected' : ''} onClick={() => { setLevel('package'); setSelected(''); }}>Packages</button><button className={level === 'class' ? 'selected' : ''} onClick={() => { setLevel('class'); setSelected(''); }}>Classes</button></div>
      <input aria-label="Filter metrics by name" placeholder="Filter by name…" value={search} onChange={e => setSearch(e.target.value)} /><span className="muted">{ordered.length} {level === 'package' ? 'packages' : 'classes'}</span></div>
    <section className="panel insight-panel"><h3>Worst offenders</h3>{offenders.length ? <ul className="evidence-list">{offenders.map(([key, list]) => <li key={key}><strong>{data.definitions[key].label}:</strong> {list.filter(i => i.state !== 'ok').map(item => <span key={item.id}><NodeLink id={item.id} label={level === 'package' ? item.id : short(item.id)} /> ({item.value}, {STATE_LABEL[item.state]}) </span>)}</li>)}</ul> : <p className="muted">No {level} is near or over any threshold.</p>}</section>
    {level === 'package' && <section className="panel insight-panel"><h3>Abstractness vs. instability</h3><p className="fine-print">Each dot is a package; the diagonal is the main sequence (D = 0). Hover a dot for its values.</p><Scatter packages={data.packages} /></section>}
    <div className="insight-table-wrap"><table className="insight-table"><thead><tr><th>{level === 'package' ? 'Package' : 'Class'}</th>{columns.map(key => <th key={key} title={data.definitions[key].formula}><button onClick={() => setSort(key)} aria-label={'Sort by ' + data.definitions[key].label}>{data.definitions[key].label}{sortKey === key ? ' ↓' : ''}</button></th>)}</tr></thead>
      <tbody>{ordered.map(row => <tr key={row.id} className={selected === row.id ? 'selected' : ''} onClick={() => setSelected(selected === row.id ? '' : row.id)}><td title={row.id}><strong>{level === 'package' ? row.id : row.name}</strong>{level === 'class' && <div className="fine-print">{row.package}</div>}</td>{columns.map(key => <Cell key={key} metric={row.metrics[key]} />)}</tr>)}</tbody></table></div>
    {chosen && <Detail row={chosen} definitions={data.definitions} level={level} />}
  </>;
}
