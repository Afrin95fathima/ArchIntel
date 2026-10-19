import { useState } from 'react';
import { ExplanationLayers, AiExplain, Expandable, InsightState, NodeLink, NotAvailable, short, useInsight } from './shared';

type Suggestion = { id: string; rank: number; status: string;
  entry_point: { kind: string; description: string; handler: string; handler_class: string };
  action_steps: string[]; preconditions: string[]; edge_cases: string[];
  sample_request: null | { method: string | null; path: string | null; path_parameters: { name: string; example: string; type: string }[]; query_parameters: { name: string; example: string; required: boolean; constraints: string[] }[]; form_fields: { name: string; example: string; required: boolean; constraints: string[] }[] };
  exercises: { classes: string[]; methods: string[]; method_count: number };
  expected_gain: { new_classes: number; new_methods: number; standalone_new_classes: number; class_names: string[]; basis: string }; evidence: string[] };
export type TestsResult = { status: string; reason?: string; suggestions: Suggestion[]; done: { id: string; entry_point: string; handler: string }[]; limitation: string; runtime_included: boolean; totals: { entry_points: number; done: number; open: number } };

export function SuggestedTests({ analysisId, sessions }: { analysisId: string; sessions: string }) {
  const query = useInsight<TestsResult>(analysisId, 'tests' + (sessions ? '?runtime_session_ids=' + sessions : ''));
  const [open, setOpen] = useState('');
  return <section className="runtime-card"><h2>Suggested next tests</h2>
    <p>Each suggestion is an entry point of the application that the selected session(s) did not exercise, ranked by how many additional classes and methods it would reach according to the static call graph.</p>
    <InsightState query={query}>{() => {
      const data = query.data!;
      if (data.status !== 'AVAILABLE') return <NotAvailable reason={data.reason || 'Not available.'} />;
      return <>
        <div className="insight-cards"><article><strong>{data.totals.open}</strong><span>open suggestions</span></article><article><strong>{data.totals.done}</strong><span>done (observed)</span></article><article><strong>{data.totals.entry_points}</strong><span>entry points total</span></article></div>
        <p className="fine-print">{data.limitation}</p>
        {data.suggestions.length === 0 && <NotAvailable reason="Every detected entry point has been observed in the selected sessions." />}
        <ol className="suggestion-list">{data.suggestions.map(s => <li key={s.id}>
          <button className="suggestion-head" aria-expanded={open === s.id} onClick={() => setOpen(open === s.id ? '' : s.id)}>
            <span className="rank">#{s.rank}</span><strong>{s.entry_point.description}</strong><span className="muted">{s.entry_point.handler}</span>
            <span className="gain">+{s.expected_gain.new_classes} classes · +{s.expected_gain.new_methods} methods</span></button>
          {open === s.id && <div className="suggestion-body">
            <ExplanationLayers explanation={{ plain: s.action_steps.join(' ') || 'No steps could be derived.', technical: `Entry point ${s.entry_point.description} (${s.entry_point.kind.toLowerCase().replace('_', ' ')}) handled by ${s.entry_point.handler}; it reaches ${s.exercises.method_count} methods in ${s.exercises.classes.length} classes through static calls.` }}
              evidence={s.evidence.map(text => ({ text }))} action={s.preconditions.length ? 'Preconditions: ' + s.preconditions.join('; ') + '.' : null} />
            {s.sample_request && <><h4>Sample request</h4><pre>{s.sample_request.method} {s.sample_request.path}{s.sample_request.query_parameters.length ? '\n?' + s.sample_request.query_parameters.map(q => `${q.name}=${q.example}`).join('&') : ''}{s.sample_request.form_fields.length ? '\n\n' + s.sample_request.form_fields.map(f => `${f.name}=${f.example}${f.required ? '   (required)' : ''}${f.constraints.length ? '   [' + f.constraints.join('; ') + ']' : ''}`).join('\n') : ''}</pre></>}
            {s.edge_cases.length > 0 && <><h4>Edge cases to include</h4><ul>{s.edge_cases.map(e => <li key={e}>{e}</li>)}</ul></>}
            <Expandable summary={<strong>Would newly exercise {s.expected_gain.new_classes} classes and {s.expected_gain.new_methods} methods</strong>}>
              <ul className="call-sites">{s.expected_gain.class_names.map(c => <li key={c}><NodeLink id={c} /> <span className="muted">{c.replace(short(c), '')}</span></li>)}</ul>
              <p className="fine-print">{s.expected_gain.basis}</p></Expandable>
            <AiExplain analysisId={analysisId} path={'tests/explain' + (sessions ? '?runtime_session_ids=' + sessions : '')} targetId={s.id} title="AI: write the human steps and edge cases (optional)" />
          </div>}
        </li>)}</ol>
        {data.done.length > 0 && <Expandable summary={<strong>Done: {data.done.length} entry points already observed</strong>}><ul>{data.done.map(d => <li key={d.id}>✓ {d.entry_point} <span className="muted">{d.handler}</span></li>)}</ul></Expandable>}
      </>;
    }}</InsightState></section>;
}
