export type ItemDescriptionData = { title: string; target: { domain: string; class_count: number; packages: string[]; key_classes: string[] }; current_state: string[]; selected_because: string[];
  blockers: { code: string; meaning: string; resolve: string; subjects: string[]; detail: string | null }[]; order: string[]; formulas: { name: string; formula: string | null; value: number | null }[] };

/** Exact target, measured state, reason for selection, named blockers, dependency order and the formulas behind each number. */
export function ItemDescription({ item }: { item: ItemDescriptionData }) {
  return <details className="item-description"><summary>Target, current state, blockers and order: {item.title}</summary>
    <h4>Target</h4><p>{item.title}. Packages: {item.target.packages.join(', ')}. Key classes: {item.target.key_classes.map(c => c.split('.').at(-1)).join(', ')}.</p>
    <h4>Current state</h4><ul>{item.current_state.map(line => <li key={line}>{line}</li>)}</ul>
    <h4>Why it was selected</h4><ul>{item.selected_because.map(line => <li key={line}>{line}</li>)}</ul>
    <h4>Blockers</h4><ul>{item.blockers.map(b => <li key={b.code}><strong>{b.code}</strong>: {b.meaning} {b.detail ? <>Found: {b.detail} </> : null}{b.subjects.length ? <>Named: {b.subjects.join(', ')}. </> : null}Resolve: {b.resolve}</li>)}</ul>
    <h4>Dependency order</h4><ul>{item.order.map(line => <li key={line}>{line}</li>)}</ul>
    <h4>Formulas and inputs</h4><ul>{item.formulas.map(f => <li key={f.name}><strong>{f.name}</strong>{f.value !== null ? ` = ${f.value}` : ''}: {f.formula || 'not recorded'}</li>)}</ul>
  </details>;
}
