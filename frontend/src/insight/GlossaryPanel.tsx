import { useQuery } from '@tanstack/react-query';
import { api } from '../api';

export type GlossaryEntry = { id: string; group: string; term: string; answers: string; formula: string; numerator?: string; denominator?: string; inputs: string[]; not_measured?: string };

/** Terms are defined once, here, with the exact formula and inputs. `only` limits the panel to entries whose id starts with one of the prefixes. */
export function GlossaryPanel({ only, title = 'Glossary: how these numbers are calculated' }: { only?: string[]; title?: string }) {
  const query = useQuery({ queryKey: ['insight-glossary'], queryFn: () => api<{ entries: GlossaryEntry[] }>('/insight/glossary'), staleTime: 3600_000 });
  const entries = (query.data?.entries || []).filter(e => !only || only.some(prefix => e.id.startsWith(prefix)));
  const groups = [...new Set(entries.map(e => e.group))];
  return <details className="glossary-panel panel insight-panel"><summary>{title}</summary>
    {query.isPending && <p className="fine-print">Loading definitions…</p>}
    {query.error ? <p role="alert">The glossary could not be loaded: {query.error instanceof Error ? query.error.message : String(query.error)}</p> : null}
    {groups.map(group => <section key={group}><h4>{group}</h4><dl>
      {entries.filter(e => e.group === group).map(e => <div key={e.id} className="glossary-entry"><dt>{e.term}</dt>
        <dd><p>{e.answers}</p><p><strong>Formula:</strong> {e.formula}</p>
          {e.numerator && <p><strong>Numerator:</strong> {e.numerator}</p>}{e.denominator && <p><strong>Denominator:</strong> {e.denominator}</p>}
          {e.inputs.length > 0 && <p><strong>Inputs:</strong> {e.inputs.join('; ')}</p>}{e.not_measured && <p className="fine-print">{e.not_measured}</p>}</dd></div>)}
    </dl></section>)}
  </details>;
}
