import { useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Bot, ChevronDown, ExternalLink, Info } from 'lucide-react';
import { api, post } from '../api';
import { Badge, ErrorBox, Loading } from '../components';
import './insight.css';

export type Explanation = { technical: string; plain: string };
export type EvidenceItem = { kind?: string; text: string; line?: number | null };
export type AiBlock = { status: string; reason?: string | null; label?: string; sentences: { text: string; citations: string[] }[]; dropped: { text: string; reason: string }[]; request_id?: string | null };

/** Opens a class, package or method in the Architecture explorer from anywhere in the app. */
export function openNode(id: string) {
  window.dispatchEvent(new CustomEvent('archintel-open-node', { detail: { id } }));
}

export function short(name: string) { return name.split('.').at(-1) || name; }

export function NodeLink({ id, label }: { id: string; label?: string }) {
  return <button type="button" className="node-link" title={id + ' — open in Architecture explorer'} onClick={() => openNode(id)}>
    {label || short(id)}<ExternalLink size={12} aria-hidden="true" />
  </button>;
}

export function useInsight<T>(analysisId: string, path: string, enabled = true) {
  return useQuery({ queryKey: ['insight', analysisId, path], queryFn: () => api<T>(`/analyses/${analysisId}/insight/${path}`), enabled });
}

export function InsightState({ query, children }: { query: { isPending: boolean; error: unknown; data?: unknown }; children: () => ReactNode }) {
  if (query.isPending) return <Loading />;
  if (query.error) return <ErrorBox error={query.error} />;
  return <>{children()}</>;
}

/** The four-part layout every finding uses. */
export function ExplanationLayers({ explanation, evidence, action, children }: { explanation: Explanation; evidence?: EvidenceItem[]; action?: string | null; children?: ReactNode }) {
  return <div className="explanation-layers">
    <section><h4>Plain language</h4><p>{explanation.plain}</p></section>
    <section><h4>Technical</h4><p>{explanation.technical}</p></section>
    {evidence && <section><h4>Evidence</h4>{evidence.length ? <ul className="evidence-list">{evidence.map((item, index) => <li key={index}>{item.kind && <span className="evidence-kind">{item.kind.replaceAll('_', ' ').toLowerCase()}</span>}{item.text}{item.line ? <small> · line {item.line}</small> : null}</li>)}</ul> : <p className="muted">not measured: no supporting record was found.</p>}</section>}
    {action && <section><h4>Suggested action</h4><p>{action}</p></section>}
    {children}
  </div>;
}

export function NotAvailable({ reason }: { reason: string }) {
  return <div className="not-available" role="note"><Info size={16} /><div><strong>Not available</strong><p>{reason}</p></div></div>;
}

/** Optional AI rewrite. Shows the verifier outcome; never mixes AI text with deterministic findings. */
export function AiExplain({ analysisId, path, targetId, title = 'AI explanation (optional)' }: { analysisId: string; path: string; targetId: string; title?: string }) {
  const [state, setState] = useState<{ busy: boolean; result?: { ai: AiBlock }; error?: unknown }>({ busy: false });
  async function run() {
    setState({ busy: true });
    try { setState({ busy: false, result: await post<{ ai: AiBlock }>(`/analyses/${analysisId}/insight/${path}`, { target_id: targetId }) }); }
    catch (error) { setState({ busy: false, error }); }
  }
  const ai = state.result?.ai;
  return <section className="ai-explain">
    <div className="ai-explain-head"><Bot size={16} /><strong>{title}</strong><button type="button" className="secondary-button" disabled={state.busy} onClick={run}>{state.busy ? 'Asking the local model…' : ai ? 'Regenerate' : 'Generate'}</button></div>
    {state.error ? <ErrorBox error={state.error} /> : null}
    {ai && (ai.status === 'AI_GENERATED' ? <>
      <Badge tone="medium">AI-GENERATED</Badge><p className="fine-print">{ai.label}</p>
      <ul className="ai-sentences">{ai.sentences.map((s, i) => <li key={i}>{s.text} {s.citations.map(c => <span key={c} className="citation-chip" title={c}>{c.startsWith('class:') ? short(c.slice(6)) : c}</span>)}</li>)}</ul>
      {ai.dropped.length > 0 && <p className="fine-print">{ai.dropped.length} AI sentence{ai.dropped.length === 1 ? ' was' : 's were'} removed by the evidence check ({[...new Set(ai.dropped.map(d => d.reason.replaceAll('_', ' ').toLowerCase()))].join(', ')}).</p>}
    </> : <p className="muted">No AI text shown: {aiReason(ai.reason)}. The deterministic finding above is complete without it.</p>)}
  </section>;
}

export function aiReason(reason?: string | null) {
  const known: Record<string, string> = {
    INSIGHT_AI_DISABLED: 'AI explanations are switched off for this deployment (insight_ai_mode=OFF)',
    MODEL_DISABLED: 'no local model is enabled in the workspace AI policy',
    MODEL_PERMISSION_REQUIRED: 'your account lacks the MODEL_USE_LOCAL permission',
    PROVIDER_UNAVAILABLE: 'the configured local model provider (Ollama) is unavailable',
    DESTINATION_DENIED: 'the policy only allows local models',
    HOURLY_BUDGET: 'the hourly model budget (model_calls_per_hour) is used up',
    NO_VERIFIED_SENTENCES: 'every generated sentence failed the citation check (UNCITED_OR_UNKNOWN_CITATION)',
    SECRET_DETECTED: 'the evidence contained a credential-like value (SECRET_DETECTED), so nothing was sent',
    SENSITIVE_DATA: 'the evidence contained personal data (SENSITIVE_DATA) and the policy blocks it',
  };
  return known[reason || ''] || (reason ? reason.replaceAll('_', ' ').toLowerCase() : 'unknown');
}

export function Expandable({ summary, children, defaultOpen = false }: { summary: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return <div className={'expandable ' + (open ? 'open' : '')}>
    <div className="expandable-summary"><button type="button" className="expandable-toggle" aria-expanded={open} aria-label={open ? 'Hide details' : 'Show details'} onClick={() => setOpen(!open)}><ChevronDown size={15} /></button><div>{summary}</div></div>
    {open && <div className="expandable-body">{children}</div>}
  </div>;
}

export function Formula({ formula, inputs }: { formula: string; inputs?: Record<string, unknown> }) {
  return <div className="formula"><code>{formula}</code>{inputs && <span>{Object.entries(inputs).map(([k, v]) => `${k.replaceAll('_', ' ')} = ${typeof v === 'number' ? v : Array.isArray(v) ? v.length : String(v)}`).join(' · ')}</span>}</div>;
}
