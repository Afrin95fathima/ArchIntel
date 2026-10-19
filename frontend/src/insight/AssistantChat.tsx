import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Bot, Send, Trash2, Wrench } from 'lucide-react';
import { api, apiStream, ndjson } from '../api';
import { Badge, ErrorBox, PageTitle } from '../components';
import { NodeLink, short } from './shared';

type Cited = { text: string; cites: string[]; code?: string | null };
type Final = { turn_id: string; status: string; mode: string; ai_generated: boolean; sentences: Cited[]; removed: { reason: string; text: string }[]; tool_calls: { tool: string; args: Record<string, unknown> }[]; label: string; gateway: { reason: string | null } };
type Turn = { id: string; question: string; tools: string[]; sentences: Cited[]; final?: Final; busy: boolean; error?: string };
type Event = { type: 'start' | 'tool_call' | 'tool_result' | 'sentence' | 'done'; turn_id?: string; tool?: string; args?: Record<string, unknown>; text?: string; cites?: string[]; code?: string | null; answer?: Final };

const EXAMPLES = ['How many classes and packages does the application have?', 'Which controller handles POST /owners/new?', 'What depends on OwnerRepository?', 'Are there circular dependencies?', 'Which controllers use entities directly?', 'Is anything end-of-life?'];

function Citation({ id }: { id: string }) {
  const [kind, value] = [id.split(':')[0], id.slice(id.indexOf(':') + 1)];
  if ((kind === 'class' || kind === 'package') && value) return <NodeLink id={value} label={short(value)} />;
  const node = kind === 'edge' ? value.split('->')[0] : kind === 'metric' ? value.slice(0, value.lastIndexOf(':')) : '';
  return node ? <NodeLink id={node} label={`${kind}: ${short(node)}`} /> : <span className="citation-chip" title={id}>{kind}</span>;
}

export function AssistantChat({ analysisId, applicationId }: { analysisId: string; applicationId?: string }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState('');
  const [session, setSession] = useState('');
  const [error, setError] = useState('');
  const bottom = useRef<HTMLDivElement>(null);
  const sessions = useQuery({ queryKey: ['runtime-sessions', applicationId], queryFn: () => api<{ id: string; name: string; analysis_id: string }[]>('/applications/' + applicationId + '/runtime-sessions'), enabled: !!applicationId });
  useEffect(() => {
    let cancelled = false;
    api<{ messages: { turn_id: string; role: string; content: string; detail: { tools?: string[]; status?: string; mode?: string } }[] }>(`/analyses/${analysisId}/insight/assistant/history`).then(({ messages }) => {
      if (cancelled) return;
      const byTurn = new Map<string, Turn>();
      for (const m of messages) {
        const turn = byTurn.get(m.turn_id) || { id: m.turn_id, question: '', tools: [], sentences: [], busy: false };
        if (m.role === 'user') turn.question = m.content;
        if (m.role === 'assistant') { turn.sentences = [{ text: m.content, cites: [] }]; turn.tools = m.detail.tools || []; }
        byTurn.set(m.turn_id, turn);
      }
      setTurns(current => current.length ? current : [...byTurn.values()]);   // never overwrite a turn the user already started
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [analysisId]);
  useEffect(() => { bottom.current?.scrollIntoView?.({ block: 'end' }); }, [turns]);

  async function ask(text: string) {
    const value = text.trim();
    if (value.length < 3) return;
    setError(''); setQuestion('');
    const id = 'pending-' + Date.now();
    setTurns(t => [...t, { id, question: value, tools: [], sentences: [], busy: true }]);
    const patch = (fn: (turn: Turn) => Turn) => setTurns(t => t.map(x => x.id === id || (x.busy && x.question === value) ? fn(x) : x));
    try {
      const response = await apiStream(`/analyses/${analysisId}/insight/assistant/chat${session ? '?runtime_session_ids=' + session : ''}`, { question: value });
      for await (const event of ndjson<Event>(response)) {
        if (event.type === 'tool_call') patch(x => ({ ...x, tools: [...x.tools, `${event.tool}(${Object.values(event.args || {}).filter(v => v !== '' && v !== undefined).join(', ')})`] }));
        else if (event.type === 'sentence') patch(x => ({ ...x, sentences: [...x.sentences, { text: event.text!, cites: event.cites || [], code: event.code }] }));
        else if (event.type === 'done') patch(x => ({ ...x, busy: false, final: event.answer }));
      }
    } catch (e) { setTurns(t => t.filter(x => x.id !== id)); setError(e instanceof Error ? e.message : String(e)); }
    finally { patch(x => ({ ...x, busy: false })); }
  }
  async function clear() {
    await api(`/analyses/${analysisId}/insight/assistant/history`, { method: 'DELETE' });
    setTurns([]);
  }
  return <>
    <PageTitle eyebrow="ARCHITECTURE ASSISTANT" title="Ask about this application. Every answer cites its evidence." description="The assistant answers by reading this analysis through read-only tools. It cannot change code, and anything it cannot support from the analysis is reported as not determinable." />
    <div className="assistant-layout"><section className="chat-panel">
      <div className="chat-header"><span className="assistant-icon"><Bot size={20} /></span><div><strong>ArchIntel assistant</strong><small>Works without any AI model · a local model, if enabled, only rewords verified tool results</small></div>
        <button className="secondary-button" onClick={() => void clear()} disabled={!turns.length} aria-label="Clear conversation"><Trash2 size={14} /> Clear</button></div>
      <div className="chat-messages">
        {!turns.length && <div className="chat-welcome"><h2>Try a question</h2><div className="suggestions">{EXAMPLES.map(e => <button key={e} onClick={() => void ask(e)}>{e}</button>)}</div></div>}
        {turns.map(turn => <div className="chat-exchange" key={turn.id}>
          <div className="user-message">{turn.question}</div>
          <div className="assistant-message">
            {turn.tools.length > 0 && <div className="tool-trace" aria-label="Tools used"><Wrench size={12} /> {turn.tools.map((t, i) => <code key={i}>{t}</code>)}</div>}
            {turn.final && <Badge tone={turn.final.ai_generated ? 'medium' : 'green'}>{turn.final.ai_generated ? 'AI-GENERATED · CITED' : turn.final.status === 'REFUSED' ? 'READ-ONLY' : 'FROM THE ANALYSIS · NO MODEL'}</Badge>}
            {turn.sentences.map((s, i) => <div key={i} className="fact"><p>{s.text} {s.cites.slice(0, 6).map(c => <Citation key={c} id={c} />)}</p>{s.code && <pre className="code-block">{s.code}</pre>}</div>)}
            {turn.busy && !turn.sentences.length && <p className="thinking">Reading the analysis…</p>}
            {turn.final && <p className="fine-print">{turn.final.label}{turn.final.removed.length > 0 && ` ${turn.final.removed.length} generated sentence${turn.final.removed.length === 1 ? ' was' : 's were'} removed because ${[...new Set(turn.final.removed.map(r => r.reason.replaceAll('_', ' ').toLowerCase()))].join(', ')}.`}{turn.final.gateway.reason && turn.final.mode === 'LOCAL_EVIDENCE' && turn.final.gateway.reason !== 'NOT_TRIED' ? ` Model not used: ${turn.final.gateway.reason.replaceAll('_', ' ').toLowerCase()}.` : ''}</p>}
          </div></div>)}
        <div ref={bottom} />
      </div>
      {error && <ErrorBox error={error} />}
      <form className="chat-input" onSubmit={e => { e.preventDefault(); void ask(question); }}>
        <input aria-label="Ask an architecture question" placeholder="Ask about a class, package, route, dependency, cycle, debt or technology…" value={question} maxLength={2000} onChange={e => setQuestion(e.target.value)} />
        <button className="button" type="submit" disabled={question.trim().length < 3} aria-label="Send question"><Send size={16} /></button>
      </form>
    </section>
    <aside className="assistant-context"><h3>What it can read</h3>
      <ul className="evidence-list">{['Classes, packages and their roles', 'Dependencies and dependents', 'Cycles and cut candidates', 'Technical debt findings', 'Entry points and routes', 'Aging technology', 'Metrics', 'Source or a labelled bytecode outline (size-bounded)'].map(x => <li key={x}>{x}</li>)}</ul>
      {applicationId && <label>Runtime session (optional)<select aria-label="Runtime session" value={session} onChange={e => setSession(e.target.value)}><option value="">None — static analysis only</option>{sessions.data?.filter(s => s.analysis_id === analysisId).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>}
      <p className="fine-print">Rate-limited per user. Prompts, tool calls and answers are stored with this analysis and recorded in the audit log without their content.</p></aside></div>
  </>;
}
