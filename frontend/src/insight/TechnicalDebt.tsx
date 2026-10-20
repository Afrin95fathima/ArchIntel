import { Fragment, useEffect, useMemo, useState } from 'react';
import { publishAssistantContext } from '../assistantContext';
import { PageTitle } from '../components';
import { DebtRates, type DebtRatesPayload } from './DebtRates';
import { GlossaryPanel } from './GlossaryPanel';
import { AiExplain, ExplanationLayers, Formula, InsightState, NodeLink, NotAvailable, short, useInsight } from './shared';

export type DebtFinding = { id: string; rule_id: string; title: string; severity: string; entity_id: string; entity_type: string; package: string;
  measured: Record<string, unknown>; threshold: unknown; reason: string; explanation: { technical: string; plain: string };
  evidence: { kind: string; text: string; line?: number | null }[]; suggested_action: string; node_ids: string[]; related: Record<string, string> };
export type DebtResult = { findings: DebtFinding[]; packages: { package: string; class_count: number; counts: Record<string, number>; debt_index: number; debt_density: number | null; formula: string; inputs: Record<string, number> }[];
  rules: { id: string; title: string; severity: string; description: string; action: string }[]; counts: Record<string, number>; by_rule: Record<string, number>;
  runtime_included: boolean; facts_available: boolean; effort_note: string; rules_version: string; rates?: DebtRatesPayload };

const ORDER: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3, INFO: 4 };

function render(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (Array.isArray(value)) return value.join(', ');
  if (typeof value === 'object') return Object.entries(value as Record<string, unknown>).map(([k, v]) => `${k.replaceAll('_', ' ')}: ${typeof v === 'object' && v !== null ? JSON.stringify(v).replaceAll('"', '') : String(v)}`).join('; ');
  return String(value);
}

function Subject({ finding }: { finding: DebtFinding }) {
  if (finding.entity_type === 'DEPENDENCY') return <><NodeLink id={finding.node_ids[0]} /> → <NodeLink id={finding.node_ids[1]} /></>;
  if (finding.entity_type === 'METHOD' || finding.entity_type === 'FIELD') {
    const [owner, member] = finding.entity_id.split('#');
    return <><NodeLink id={finding.node_ids[0]} label={short(owner)} /><span className="muted">.{member.split('(')[0]}</span></>;
  }
  return <NodeLink id={finding.node_ids[0]} />;
}

export function TechnicalDebt({ analysisId }: { analysisId: string }) {
  const query = useInsight<DebtResult>(analysisId, 'debt');
  return <>
    <PageTitle eyebrow="TECHNICAL DEBT" title="Findings with measured value and threshold." description="Row = one class, method or dependency, the rule that fired, its measured value and the suggested action. Thresholds are documented in debt-rules.yaml." />
    <InsightState query={query}>{() => <DebtBody data={query.data!} analysisId={analysisId} />}</InsightState>
  </>;
}

function DebtBody({ data, analysisId }: { data: DebtResult; analysisId: string }) {
  const [severity, setSeverity] = useState(''), [rule, setRule] = useState(''), [search, setSearch] = useState(''), [group, setGroup] = useState<'none' | 'package' | 'rule'>('none');
  const [sort, setSort] = useState<'severity' | 'subject' | 'rule'>('severity'), [open, setOpen] = useState('');
  const rules = Object.fromEntries(data.rules.map(r => [r.id, r]));
  useEffect(() => {      // the opened finding is the page selection the docked assistant can ask about
    const finding = data.findings.find(f => f.id === open);
    publishAssistantContext(finding ? { kind: 'class', id: finding.node_ids[0], label: short(finding.node_ids[0]) } : null);
    return () => publishAssistantContext(null);
  }, [open, data.findings]);
  const rows = useMemo(() => data.findings.filter(f => (!severity || f.severity === severity) && (!rule || f.rule_id === rule) && (!search || (f.entity_id + ' ' + f.explanation.plain).toLowerCase().includes(search.toLowerCase())))
    .sort((a, b) => sort === 'subject' ? a.entity_id.localeCompare(b.entity_id) : sort === 'rule' ? a.rule_id.localeCompare(b.rule_id) || a.entity_id.localeCompare(b.entity_id) : (ORDER[a.severity] - ORDER[b.severity]) || a.rule_id.localeCompare(b.rule_id)), [data, severity, rule, search, sort]);
  const groups = useMemo(() => {
    if (group === 'none') return [['', rows] as const];
    const map = new Map<string, DebtFinding[]>();
    rows.forEach(f => { const key = group === 'package' ? f.package : f.rule_id; map.set(key, [...(map.get(key) || []), f]); });
    return [...map.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [rows, group]);
  return <>
    <div className="insight-cards">{['HIGH', 'MEDIUM', 'LOW', 'INFO'].map(s => <article key={s}><strong>{data.counts[s] || 0}</strong><span>{s.toLowerCase()} findings</span></article>)}</div>
    <p className="fine-print">Rules {data.rules_version}. {data.runtime_included ? 'Runtime evidence is included (unobserved classes are listed as INFO).' : 'No runtime session is selected: the DEBT-UNOBSERVED rule is not evaluated.'}{!data.facts_available && ' Method-level rules need bytecode facts, which this analysis does not have; run a new analysis.'}</p>
    {data.rates && <DebtRates data={data.rates} />}
    <section className="panel insight-panel"><h3>Debt by package</h3><Formula formula={data.packages[0]?.formula || 'debt index = 3 × HIGH + 2 × MEDIUM + 1 × LOW'} /><p className="fine-print">{data.effort_note}</p>
      <div className="insight-table-wrap"><table className="insight-table"><thead><tr><th>Package</th><th>Classes</th><th>High</th><th>Medium</th><th>Low</th><th>Debt index</th><th>Per class</th></tr></thead><tbody>
        {data.packages.filter(p => p.debt_index > 0).map(p => <tr key={p.package}><td><NodeLink id={p.package} label={p.package} /></td><td>{p.class_count}</td><td>{p.counts.HIGH || 0}</td><td>{p.counts.MEDIUM || 0}</td><td>{p.counts.LOW || 0}</td><td>{p.debt_index}</td><td>{p.debt_density ?? '—'}</td></tr>)}
      </tbody></table></div></section>
    <div className="insight-toolbar">
      <input aria-label="Search findings" placeholder="Search class, package or text…" value={search} onChange={e => setSearch(e.target.value)} />
      <select aria-label="Severity" value={severity} onChange={e => setSeverity(e.target.value)}><option value="">All severities</option>{['HIGH', 'MEDIUM', 'LOW', 'INFO'].map(s => <option key={s}>{s}</option>)}</select>
      <select aria-label="Rule" value={rule} onChange={e => setRule(e.target.value)}><option value="">All rules</option>{data.rules.filter(r => data.by_rule[r.id]).map(r => <option key={r.id} value={r.id}>{r.title} ({data.by_rule[r.id]})</option>)}</select>
      <select aria-label="Group findings" value={group} onChange={e => setGroup(e.target.value as 'none')}><option value="none">No grouping</option><option value="package">Group by package</option><option value="rule">Group by rule</option></select>
      <span className="muted">{rows.length} findings</span>
    </div>
    {!rows.length ? <NotAvailable reason={data.findings.length ? 'No finding matches these filters.' : 'No rule in debt-rules.yaml fired for this application.'} /> :
      <div className="insight-table-wrap"><table className="insight-table"><thead><tr>
        <th><button onClick={() => setSort('severity')}>Severity{sort === 'severity' ? ' ↓' : ''}</button></th><th><button onClick={() => setSort('subject')}>Class / package{sort === 'subject' ? ' ↓' : ''}</button></th><th><button onClick={() => setSort('rule')}>Rule{sort === 'rule' ? ' ↓' : ''}</button></th><th>Measured vs. threshold</th><th>Plain-language explanation</th><th>Suggested fix</th></tr></thead>
        <tbody>{groups.map(([key, list]) => <Fragment key={key || 'all'}>
          {key && <tr className="group-row"><td colSpan={6}><strong>{group === 'rule' ? rules[key]?.title || key : key}</strong> · {list.length} findings</td></tr>}
          {list.map(f => <Fragment key={f.id}><tr className={open === f.id ? 'selected' : ''}>
            <td><span className={'status-pill ' + f.severity.toLowerCase()}>{f.severity}</span></td>
            <td><Subject finding={f} /><div className="fine-print">{f.package}</div></td>
            <td><button className="node-link" aria-expanded={open === f.id} onClick={() => setOpen(open === f.id ? '' : f.id)}>{f.title}</button><div className="fine-print">{f.rule_id}</div></td>
            <td><div>{render(f.measured)}</div><div className="fine-print">threshold: {render(f.threshold)}</div></td>
            <td>{f.explanation.plain}</td><td>{f.suggested_action}</td>
          </tr>
          {open === f.id && <tr className="selected"><td colSpan={6}>
            <ExplanationLayers explanation={f.explanation} evidence={f.evidence} action={f.suggested_action} />
            <p className="fine-print">Rule: {f.reason}</p>
            <AiExplain analysisId={analysisId} path="debt/explain" targetId={f.id} title="AI refactoring proposal (optional, cites the methods it reads)" />
          </td></tr>}
          </Fragment>)}
        </Fragment>)}</tbody></table></div>}
    <GlossaryPanel only={['rate:', 'debt-index']} />
  </>;
}
