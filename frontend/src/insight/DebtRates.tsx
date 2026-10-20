import { Fragment, useState } from 'react';
import { NodeLink, short } from './shared';

export type Rate = { id: string; label: string; rule_ids: string[]; unit: string; status: 'MEASURED' | 'NOT_MEASURED'; reason: string | null; numerator: number | null; denominator: number | null; percentage: number | null;
  text: string; numerator_definition: string; denominator_definition: string; severity: string | null; subjects: string[]; classes: string[]; basis?: string };
export type GroupRow = { id: string; name: string; class_count: number; rates: Record<string, { numerator: number; denominator: number; percentage: number | null; classes: string[] }> };
export type DebtRatesPayload = { rates: Rate[]; by_package: GroupRow[]; by_domain: GroupRow[]; note: string };
const ORDER: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3, INFO: 4 };

export function DebtRates({ data }: { data: DebtRatesPayload }) {
  const [sort, setSort] = useState<'percentage' | 'severity'>('percentage'), [open, setOpen] = useState(''), [view, setView] = useState<'overall' | 'domain' | 'package'>('overall');
  const measured = data.rates.filter(r => r.status === 'MEASURED' && (r.numerator || 0) > 0);
  const quiet = data.rates.filter(r => r.status === 'MEASURED' && !r.numerator);
  const missing = data.rates.filter(r => r.status === 'NOT_MEASURED');
  const rows = [...measured].sort((a, b) => sort === 'percentage' ? (b.percentage || 0) - (a.percentage || 0) : (ORDER[a.severity || 'INFO'] - ORDER[b.severity || 'INFO']) || (b.percentage || 0) - (a.percentage || 0));
  const groups = view === 'domain' ? data.by_domain : data.by_package;
  const columns = measured.filter(r => r.id !== 'cross-domain-edges' && r.id !== 'entry-points-unobserved' && groups.some(g => g.rates[r.id]));
  return <section className="panel insight-panel" aria-label="Technical problem rates"><h3>Technical problems as a share of the application</h3>
    <p className="fine-print">{data.note}</p>
    <div className="insight-toolbar">
      <label>Show <select aria-label="Rate view" value={view} onChange={e => setView(e.target.value as 'overall')}><option value="overall">Whole application</option><option value="domain">Per domain</option><option value="package">Per package</option></select></label>
      {view === 'overall' && <label>Sort by <select aria-label="Sort rates" value={sort} onChange={e => setSort(e.target.value as 'percentage')}><option value="percentage">Percentage</option><option value="severity">Severity</option></select></label>}
    </div>
    {view === 'overall' ? <div className="insight-table-wrap"><table className="insight-table"><thead><tr><th>Problem</th><th>Share</th><th>Highest severity</th><th>Counted</th></tr></thead><tbody>
      {rows.map(r => <Fragment key={r.id}><tr>
        <td><strong>{r.label}</strong><div className="fine-print">{r.rule_ids.join(', ') || 'derived'}</div></td>
        <td><button type="button" className="node-link" aria-expanded={open === r.id} aria-label={`${r.label}: ${r.text}`} onClick={() => setOpen(open === r.id ? '' : r.id)}>{r.text}</button>
          <div className="rate-bar" role="img" aria-label={`${r.percentage}%`}><span style={{ width: `${Math.min(100, r.percentage || 0)}%` }} /></div></td>
        <td>{r.severity ? <span className={'status-pill ' + r.severity.toLowerCase()}>{r.severity}</span> : <span className="muted">not rated</span>}</td>
        <td className="fine-print">{r.numerator_definition}</td></tr>
        {open === r.id && <tr className="selected"><td colSpan={4}>
          <p><strong>{r.numerator}</strong> counted of <strong>{r.denominator}</strong>: {r.denominator_definition}.{r.basis ? ` Basis: ${r.basis}.` : ''}</p>
          <ul className="evidence-list" aria-label={`Items counted for ${r.label}`}>{(r.unit === 'classes' ? r.classes : r.subjects).map(s => <li key={s}>{r.unit === 'classes' ? <NodeLink id={s} /> : <code>{s}</code>}{r.unit !== 'classes' && <span className="fine-print"> in {short(r.classes.find(c => s.startsWith(c)) || '')}</span>}</li>)}</ul>
        </td></tr>}
      </Fragment>)}
      {!rows.length && <tr><td colSpan={4}>No measured problem rate is above 0%.</td></tr>}
    </tbody></table></div> : <div className="insight-table-wrap"><table className="insight-table"><thead><tr><th>{view === 'domain' ? 'Domain' : 'Package'}</th><th>Classes</th>{columns.map(c => <th key={c.id}>{c.label}</th>)}<th>Any finding</th></tr></thead><tbody>
      {groups.map(g => <tr key={g.id}><td>{view === 'package' ? <NodeLink id={g.id} label={g.id} /> : g.name}</td><td>{g.class_count}</td>
        {columns.map(c => { const cell = g.rates[c.id]; return <td key={c.id}>{cell ? `${cell.numerator} of ${cell.denominator} (${cell.percentage}%)` : '0'}</td>; })}
        <td>{g.rates['any-class'] ? `${g.rates['any-class'].numerator} of ${g.rates['any-class'].denominator} (${g.rates['any-class'].percentage}%)` : '0'}</td></tr>)}
    </tbody></table></div>}
    {quiet.length > 0 && <p className="fine-print">Measured at 0%: {quiet.map(r => `${r.label} (0 of ${r.denominator} ${r.unit})`).join('; ')}.</p>}
    {missing.length > 0 && <p className="fine-print">Not measured: {missing.map(r => `${r.label} (${r.reason})`).join('; ')}.</p>}
  </section>;
}
