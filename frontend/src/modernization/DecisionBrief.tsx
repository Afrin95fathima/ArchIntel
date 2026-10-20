export type BriefFact = { id: string; label: string; value: number; text: string; unit: string; source: string };
export type DecisionBriefData = { headline: string; summary?: string; facts?: BriefFact[]; sections?: { id: string; title: string; paragraphs: string[] }[];
  options?: { strategy: string; status: string; selected_by_user: boolean; recommended: boolean; tradeoffs: string[] }[]; evidence?: { id: string; kind: string; source: string | null; target: string | null }[];
  recommendation?: { option: string; rule: string; matches_request: boolean }; numbers_check?: { unregistered: string[] }; next_step?: string };

/** The brief: fact table first, then each section. Every number in the text is in the table above it. */
export function DecisionBrief({ brief }: { brief: DecisionBriefData }) {
  if (!brief.sections || !brief.facts) {
    return <section className="runtime-card" aria-label="Decision brief"><h2>{brief.headline}</h2>{brief.summary && <p>{brief.summary}</p>}
      <p role="note">This proposal was saved before the brief carried a fact table. Create a new proposal to see the numbers with their sources.</p></section>;
  }
  return <section className="runtime-card" aria-label="Decision brief">
    <details open className="brief-facts"><summary>Fact table: {brief.facts.length} numbers used in this brief</summary>
      <table><thead><tr><th>Number</th><th>Value</th><th>Source</th></tr></thead><tbody>
        {brief.facts.map(f => <tr key={f.id}><td>{f.label}</td><td>{f.text}{f.unit}</td><td>{f.source}</td></tr>)}
      </tbody></table></details>
    {brief.sections.map(section => <section key={section.id} aria-label={section.title}><h3>{section.title}</h3>
      {section.paragraphs.map((p, i) => <p key={i}>{p}</p>)}
      {section.id === 'options' && brief.options && <table><thead><tr><th>Option</th><th>Evidence status</th><th>Marks</th></tr></thead><tbody>
        {brief.options.map(o => <tr key={o.strategy}><td>{o.strategy}</td><td>{o.status.replaceAll('_', ' ')}</td><td>{[o.selected_by_user && 'requested', o.recommended && 'recommended'].filter(Boolean).join(', ') || 'none'}</td></tr>)}</tbody></table>}
    </section>)}
    {brief.evidence && brief.evidence.length > 0 && <section aria-label="Evidence ids"><h3>Evidence ids</h3>
      <ul className="evidence-list">{brief.evidence.map(e => <li key={e.id}><code>{e.id}</code> {e.kind.toLowerCase()}: {e.source} → {e.target}</li>)}</ul></section>}
    {brief.numbers_check && brief.numbers_check.unregistered.length > 0 && <p role="alert">Numbers in this text without a fact-table entry: {brief.numbers_check.unregistered.join(', ')}.</p>}
  </section>;
}
