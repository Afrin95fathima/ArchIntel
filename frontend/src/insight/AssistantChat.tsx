import { useEffect, useRef, useState } from 'react';
import { Wrench } from 'lucide-react';
import { api, apiStream, ndjson } from '../api';
import { Badge } from '../components';
import { NodeLink, short } from './shared';

type Cited = { text: string; cites: string[]; code?: string | null };
type Final = { turn_id: string; status: string; mode: string; ai_generated: boolean; sentences: Cited[]; removed: { reason: string; text: string }[]; tool_calls: { tool: string; args: Record<string, unknown> }[]; label: string; gateway: { reason: string | null } };
export type Turn = { id: string; question: string; context?: string; tools: string[]; sentences: Cited[]; final?: Final; busy: boolean };
type Event = { type: 'start' | 'tool_call' | 'tool_result' | 'sentence' | 'done'; turn_id?: string; tool?: string; args?: Record<string, unknown>; text?: string; cites?: string[]; code?: string | null; answer?: Final };

export const EXAMPLES = ['How many classes and packages does the application have?', 'Which controller handles POST /owners/new?', 'What depends on OwnerRepository?', 'Are there circular dependencies?', 'Which controllers use entities directly?', 'Is anything end-of-life?'];

function Citation({ id }: { id: string }) {
  const [kind, value] = [id.split(':')[0], id.slice(id.indexOf(':') + 1)];
  if ((kind === 'class' || kind === 'package') && value) return <NodeLink id={value} label={short(value)} />;
  const node = kind === 'edge' ? value.split('->')[0] : kind === 'metric' ? value.slice(0, value.lastIndexOf(':')) : '';
  return node ? <NodeLink id={node} label={`${kind}: ${short(node)}`} /> : <span className="citation-chip" title={id}>{kind}</span>;
}

/** The conversation with the architecture assistant for one analysis: history, streaming, errors. The dock owns one instance so it survives navigation. */
export function useAssistantConversation(analysisId: string, sessionId: string) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!analysisId) { setTurns([]); return; }
    let cancelled = false;
    api<{ messages: { turn_id: string; role: string; content: string; detail: { tools?: string[] } }[] }>(`/analyses/${analysisId}/insight/assistant/history`).then(({ messages }) => {
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

  async function ask(text: string, context?: string) {
    const value = text.trim();
    if (value.length < 3 || !analysisId) return;
    setError(''); setBusy(true);
    const id = 'pending-' + Date.now();
    setTurns(t => [...t, { id, question: value, context, tools: [], sentences: [], busy: true }]);
    const patch = (fn: (turn: Turn) => Turn) => setTurns(t => t.map(x => x.id === id ? fn(x) : x));
    // The context only names what the question is about; the backend still reads the analysis through its read-only tools.
    const sent = context && !value.toLowerCase().includes(context.toLowerCase()) ? `${value} (about ${context})` : value;
    try {
      const response = await apiStream(`/analyses/${analysisId}/insight/assistant/chat${sessionId ? '?runtime_session_ids=' + sessionId : ''}`, { question: sent });
      for await (const event of ndjson<Event>(response)) {
        if (event.type === 'tool_call') patch(x => ({ ...x, tools: [...x.tools, `${event.tool}(${Object.values(event.args || {}).filter(v => v !== '' && v !== undefined).join(', ')})`] }));
        else if (event.type === 'sentence') patch(x => ({ ...x, sentences: [...x.sentences, { text: event.text!, cites: event.cites || [], code: event.code }] }));
        else if (event.type === 'done') patch(x => ({ ...x, busy: false, final: event.answer }));
      }
    } catch (e) { setTurns(t => t.filter(x => x.id !== id)); setError(e instanceof Error ? e.message : String(e)); }
    finally { patch(x => ({ ...x, busy: false })); setBusy(false); }
  }
  async function clear() {
    await api(`/analyses/${analysisId}/insight/assistant/history`, { method: 'DELETE' });
    setTurns([]);
  }
  return { turns, error, busy, ask, clear };
}

export function ConversationView({ turns, onExample }: { turns: Turn[]; onExample: (text: string) => void }) {
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => { bottom.current?.scrollIntoView?.({ block: 'end' }); }, [turns]);
  return <div className="chat-messages" role="log" aria-label="Assistant conversation" aria-live="polite">
    {!turns.length && <div className="chat-welcome"><h2>Try a question</h2><div className="suggestions">{EXAMPLES.map(e => <button key={e} onClick={() => onExample(e)}>{e}</button>)}</div></div>}
    {turns.map(turn => <div className="chat-exchange" key={turn.id}>
      <div className="user-message">{turn.question}{turn.context && <small className="fine-print"> · context: {turn.context}</small>}</div>
      <div className="assistant-message">
        {turn.tools.length > 0 && <div className="tool-trace" aria-label="Tools used"><Wrench size={12} /> {turn.tools.map((t, i) => <code key={i}>{t}</code>)}</div>}
        {turn.final && <Badge tone={turn.final.ai_generated ? 'medium' : 'green'}>{turn.final.ai_generated ? 'AI-GENERATED · CITED' : turn.final.status === 'REFUSED' ? 'READ-ONLY' : 'FROM THE ANALYSIS · NO MODEL'}</Badge>}
        {turn.sentences.map((s, i) => <div key={i} className="fact"><p>{s.text} {s.cites.slice(0, 6).map(c => <Citation key={c} id={c} />)}</p>{s.code && <pre className="code-block">{s.code}</pre>}</div>)}
        {turn.busy && !turn.sentences.length && <p className="thinking">Reading the analysis…</p>}
        {turn.final && <p className="fine-print">{turn.final.label}{turn.final.removed.length > 0 && ` ${turn.final.removed.length} generated sentence${turn.final.removed.length === 1 ? ' was' : 's were'} removed because ${[...new Set(turn.final.removed.map(r => r.reason.replaceAll('_', ' ').toLowerCase()))].join(', ')}.`}</p>}
      </div></div>)}
    <div ref={bottom} />
  </div>;
}
