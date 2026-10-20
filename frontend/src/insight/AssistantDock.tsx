import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Bot, MessageSquare, Send, Trash2, X } from 'lucide-react';
import { api } from '../api';
import { ConversationView, useAssistantConversation } from './AssistantChat';
import { onOpenAssistant, useAssistantSelection } from '../assistantContext';
import { short } from './shared';

const KEY = 'archintel-assistant-dock';
const MIN = 320, MAX = 760;
const read = (): { open: boolean; size: number } => { try { const v = JSON.parse(localStorage.getItem(KEY) || '{}'); return { open: !!v.open, size: Math.min(MAX, Math.max(MIN, Number(v.size) || 400)) }; } catch { return { open: false, size: 400 }; } };
const write = (state: { open: boolean; size: number }) => { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch { /* storage is optional */ } };

/** Docked architecture assistant: fixed button bottom-right, side panel (bottom drawer on narrow screens), available on every page, conversation kept while navigating. */
export function AssistantDock({ analysisId, applicationId, pageLabel, selectedNode }: { analysisId: string; applicationId?: string; pageLabel: string; selectedNode?: string }) {
  const initial = read();
  const [open, setOpen] = useState(initial.open);
  const [size, setSize] = useState(initial.size);
  const [editing, setEditing] = useState(false);
  const [scope, setScope] = useState<'selection' | 'application'>('selection');
  const [session, setSession] = useState('');
  const [question, setQuestion] = useState('');
  const published = useAssistantSelection();
  const sessions = useQuery({ queryKey: ['runtime-sessions', applicationId], queryFn: () => api<{ id: string; name: string; analysis_id: string }[]>('/applications/' + applicationId + '/runtime-sessions'), enabled: !!applicationId && open });
  const conversation = useAssistantConversation(analysisId, session);
  const input = useRef<HTMLInputElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);
  const selection = published && published.kind !== 'session' ? published : selectedNode ? { kind: 'class' as const, id: selectedNode, label: short(selectedNode) } : null;
  const context = scope === 'selection' && selection ? selection.label : '';
  const sessionName = sessions.data?.find(s => s.id === session)?.name;

  useEffect(() => { write({ open, size }); }, [open, size]);
  useEffect(() => onOpenAssistant(() => setOpen(true)), []);
  useEffect(() => {
    if (open) input.current?.focus();
    else if (restoreFocus.current) { restoreFocus.current = false; opener.current?.focus(); }       // keyboard users land back on the button that opened the panel
  }, [open]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key === '/') { event.preventDefault(); setOpen(value => !value); }
      else if (event.key === 'Escape' && open && !editing) { restoreFocus.current = true; setOpen(false); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, editing]);
  useEffect(() => { if (published?.kind === 'session' && published.id !== session) setSession(published.id); }, [published]);   // eslint-disable-line react-hooks/exhaustive-deps

  function resize(event: React.PointerEvent<HTMLDivElement>) {
    const vertical = window.matchMedia?.('(max-width: 760px)').matches;
    const move = (e: PointerEvent) => setSize(Math.min(MAX, Math.max(MIN, vertical ? window.innerHeight - e.clientY : window.innerWidth - e.clientX)));
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
    event.preventDefault();
  }
  const send = () => { const value = question; setQuestion(''); void conversation.ask(value, context); };

  if (!open) {
    return <button ref={opener} type="button" className="assistant-fab" aria-label="Open architecture assistant" title="Architecture assistant (Ctrl+/)" onClick={() => setOpen(true)}><MessageSquare size={20} /><span>Ask</span></button>;
  }
  return <aside className="assistant-dock" aria-label="Architecture assistant" style={{ ['--dock-size' as string]: size + 'px' }}>
    <div className="dock-resize" role="separator" aria-orientation="vertical" aria-label="Resize assistant" aria-valuemin={MIN} aria-valuemax={MAX} aria-valuenow={size} tabIndex={0} onPointerDown={resize}
      onKeyDown={e => { if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') setSize(s => Math.min(MAX, s + 24)); if (e.key === 'ArrowRight' || e.key === 'ArrowDown') setSize(s => Math.max(MIN, s - 24)); }} />
    <header className="dock-header"><span className="assistant-icon"><Bot size={18} /></span><div><strong>Architecture assistant</strong><small>Answers from the analysis, cited · works without a model · Ctrl+/ toggles</small></div>
      <button type="button" className="icon-button" aria-label="Clear conversation" disabled={!conversation.turns.length} onClick={() => void conversation.clear()}><Trash2 size={15} /></button>
      <button type="button" className="icon-button" aria-label="Close assistant" onClick={() => { restoreFocus.current = true; setOpen(false); }}><X size={16} /></button></header>
    <div className="dock-context">
      <button type="button" className="context-chip" aria-expanded={editing} aria-label={`Assistant context: ${pageLabel}${context ? ', ' + context : ', whole application'}${sessionName ? ', runtime ' + sessionName : ''}. Change`} onClick={() => setEditing(v => !v)}>
        <span>{pageLabel}</span><span>{context || 'whole application'}</span><span>{sessionName ? 'runtime: ' + sessionName : 'static only'}</span></button>
      {editing && <div role="dialog" aria-label="Assistant context" className="context-editor">
        <fieldset><legend>About</legend>
          <label><input type="radio" name="scope" checked={scope === 'selection'} disabled={!selection} onChange={() => setScope('selection')} /> {selection ? `${selection.kind} ${selection.label}` : 'the page selection (nothing is selected)'}</label>
          <label><input type="radio" name="scope" checked={scope === 'application' || !selection} onChange={() => setScope('application')} /> the whole application</label></fieldset>
        {applicationId && <label>Runtime session<select aria-label="Runtime session" value={session} onChange={e => setSession(e.target.value)}><option value="">None: static analysis only</option>{sessions.data?.filter(s => s.analysis_id === analysisId).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>}
        <button type="button" className="secondary-button" onClick={() => { setScope('selection'); setSession(''); setEditing(false); }}>Reset to this page</button></div>}
    </div>
    {!analysisId ? <p className="dock-empty" role="note">Open an application analysis to ask about it. It reads 1 analysis at a time.</p>
      : <ConversationView turns={conversation.turns} onExample={text => void conversation.ask(text, context)} />}
    {conversation.error && <p role="alert" className="dock-error">{conversation.error}</p>}
    <form className="chat-input" onSubmit={e => { e.preventDefault(); send(); }}>
      <input ref={input} aria-label="Ask an architecture question" placeholder="Ask about a class, package, route, cycle, debt or technology…" value={question} maxLength={2000} disabled={!analysisId} onChange={e => setQuestion(e.target.value)} />
      <button className="button" type="submit" aria-label="Send question" disabled={question.trim().length < 3 || conversation.busy || !analysisId}><Send size={16} /></button></form>
  </aside>;
}
