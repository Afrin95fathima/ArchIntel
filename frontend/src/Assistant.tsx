import { useState } from 'react';
import { ArrowUp, Sparkles, Database, CheckCheck, MessageSquare } from 'lucide-react';
import { post } from './api';
import { Badge, ErrorBox, PageTitle } from './components';
import type { Answer, Domain } from './types';

export function Assistant({analysisId,domains}: {analysisId:string;domains:Domain[]}) {
  const [question,setQuestion]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null);
  const [messages,setMessages]=useState<{question:string;answer:Answer}[]>([]);
  async function ask(value:string) {
    if(value.trim().length<3||busy)return;
    setBusy(true);setError(null);setQuestion('');
    try { const answer=await post<Answer>('/analyses/'+analysisId+'/assistant/query',{question:value});setMessages(m=>[...m,{question:value,answer}]); }
    catch(e){setError(e);}finally{setBusy(false);}
  }
  const prompts=['Where should modernization begin?','Which domains are involved in cycles?', 'Why is '+(domains.find(d=>d.name==='Payment')?.name||domains[0]?.name||'this domain')+' high risk?'];
  return <><PageTitle eyebrow="ARCHITECTURE ASSISTANT" title="Ask questions. Follow the evidence." description="Explore this analysis through grounded explanations and clearly separated recommendations."/><div className="assistant-layout"><section className="chat-panel"><div className="chat-header"><span className="assistant-icon"><Sparkles size={20}/></span><div><strong>ArchIntel Evidence Assistant</strong><small>Local explanations · no external API required</small></div><Badge tone="green">ANALYSIS GROUNDED</Badge></div><div className="chat-messages">
    {!messages.length&&<div className="chat-welcome"><MessageSquare size={34}/><h2>Your architecture has a story.</h2><p>Ask about dependencies, domain risks, or where to start modernizing. Every factual statement links to an analysis record.</p><div className="suggestions">{prompts.map(p=><button key={p} onClick={()=>ask(p)}>{p}<ArrowUp size={14}/></button>)}</div></div>}
    {messages.map((m,i)=><div className="chat-exchange" key={i}><div className="user-message">{m.question}</div><div className="assistant-message"><Badge tone="green"><CheckCheck size={12}/> FACTS FROM ANALYSIS</Badge><p>{m.answer.answer}</p>{m.answer.facts.map((f,n)=><div className="fact" key={f.id}><span>{n+1}</span><p>{f.text}<a className="citation" title={f.id} href={"/api/v1/analyses/"+analysisId+"/evidence/"+encodeURIComponent(f.id)} target="_blank" rel="noreferrer">↗ {f.kind} · {f.id.slice(0,25)}</a></p></div>)}{m.answer.recommendations.length>0&&<><h4>Recommendations for investigation</h4><ul>{m.answer.recommendations.map(r=><li key={r}>{r}</li>)}</ul></>}<details><summary>Sources and limitations</summary><p className="fine-print">Mode: {m.answer.mode}. Local evidence mode uses deterministic retrieval. LOCAL_MODEL_ASSISTED uses an approved local model to select citations; displayed facts still come from validated evidence.</p>{m.answer.limitations.map(l=><p className="fine-print" key={l}>{l}</p>)}{m.answer.sources.map(s=><small className="code-line" key={s.id}>{s.id}</small>)}</details></div></div>)}
    {busy&&<p className="thinking">Retrieving analysis evidence…</p>}{error?<ErrorBox error={error}/>:null}</div><form className="chat-input" onSubmit={e=>{e.preventDefault();ask(question);}}><input aria-label="Ask an architecture question" placeholder="Ask about a domain, risk, or modernization priority…" value={question} maxLength={2000} onChange={e=>setQuestion(e.target.value)}/><button className="button" type="submit" disabled={busy||question.trim().length<3} aria-label="Send question"><ArrowUp size={18}/></button></form></section>
    <aside className="assistant-context"><Database size={23}/><h3>Connected to your analysis</h3><p>Only relevant structured findings are retrieved. The assistant does not receive your artifact or the entire graph.</p><h4>Available evidence</h4>{['Candidate domains','Architecture issues','Dependency metrics','Cyclic clusters','Readiness components','Modernization sequence'].map(x=><div className="context-item" key={x}><CheckCheck size={14}/>{x}</div>)}<div className="notice">Static analysis cannot answer questions about runtime traffic, SQL transactions, or business ownership without additional evidence.</div></aside></div></>;
}
