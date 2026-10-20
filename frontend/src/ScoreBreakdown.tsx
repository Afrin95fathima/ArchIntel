import { ScoreBar } from './components';

export type ComponentDetail = { label: string; value: number; numerator: number | null; denominator: number | null; text: string; how_to_raise: string[]; weight: number };
export type NotMeasured = { input: string; label: string; reason: string; configured_weight?: number; how_to_measure?: string | null };
export type ReadinessSource = { domain_name: string; readiness_score: number; component_details?: Record<string, ComponentDetail>; not_measured?: NotMeasured[]; formula: string };
export type ConfidenceSource = { domain_name: string; confidence_score: number; confidence_inputs?: Record<string, ComponentDetail>; confidence_not_measured?: NotMeasured[]; confidence_note?: string };

function InputsTable({ inputs, caption }: { inputs: Record<string, ComponentDetail>; caption: string }) {
  return <table className="insight-table"><caption className="visually-hidden">{caption}</caption>
    <thead><tr><th>Input</th><th>Value</th><th>Weight</th><th>What was counted</th><th>How to raise it</th></tr></thead>
    <tbody>{Object.entries(inputs).map(([key, d]) => <tr key={key}>
      <td><strong>{d.label}</strong></td>
      <td>{d.value}<small>/100</small><ScoreBar value={d.value} /></td>
      <td>{Math.round(d.weight * 100)}%</td>
      <td>{d.text}{d.numerator !== null && d.denominator !== null && <div className="fine-print">{d.numerator} / {d.denominator}</div>}</td>
      <td>{d.how_to_raise.length ? <ul className="evidence-list">{d.how_to_raise.map(a => <li key={a}>{a}</li>)}</ul> : <span className="muted">no action needed</span>}</td>
    </tr>)}</tbody></table>;
}

function Excluded({ items }: { items: NotMeasured[] }) {
  if (!items.length) return null;
  return <div role="note" className="not-measured-note"><strong>Not measured, excluded from the formula:</strong>
    <ul className="evidence-list">{items.map(e => <li key={e.input}><strong>{e.label}</strong>: {e.reason}.{e.how_to_measure ? ` To measure it: ${e.how_to_measure}` : ''}</li>)}</ul></div>;
}

/** Readiness: the question it answers, every measured input with its counts, and what to change to raise it. */
export function ReadinessBreakdown({ assessment }: { assessment: ReadinessSource }) {
  const inputs = assessment.component_details;
  return <section className="score-breakdown" aria-label={`Readiness of ${assessment.domain_name}`}>
    <h3>Readiness {assessment.readiness_score}/100</h3>
    <p><strong>Question answered:</strong> how ready is {assessment.domain_name} to be modernized or extracted, judged from structural inputs only (dependencies, cycles, shared data, class size).</p>
    {inputs ? <InputsTable inputs={inputs} caption={`Readiness inputs of ${assessment.domain_name}`} /> : <p>This assessment was created before input details were recorded. Run a new analysis to see them.</p>}
    <Excluded items={assessment.not_measured || []} />
    <p className="fine-print">{assessment.formula}</p>
  </section>;
}

/** Confidence: how much evidence supports the readiness number. */
export function ConfidenceBreakdown({ assessment }: { assessment: ConfidenceSource }) {
  const inputs = assessment.confidence_inputs;
  return <section className="score-breakdown" aria-label={`Confidence of ${assessment.domain_name}`}>
    <h3>Confidence {assessment.confidence_score}/100</h3>
    <p><strong>Question answered:</strong> how much evidence supports the readiness number for {assessment.domain_name}: static scan quality, runtime coverage, review status and resolved references.</p>
    {inputs ? <InputsTable inputs={inputs} caption={`Confidence inputs of ${assessment.domain_name}`} /> : <p>This proposal was saved before confidence inputs were recorded. Create a new proposal to see them.</p>}
    <Excluded items={assessment.confidence_not_measured || []} />
    {assessment.confidence_note && <p className="fine-print">{assessment.confidence_note}</p>}
  </section>;
}
