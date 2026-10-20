import {useState} from 'react';
import {post} from '../api';
import {Badge,ErrorBox} from '../components';

type Check={check:string;status:'PASS'|'COUPLED'|'FAIL';detail:string};
type Candidate={id:string;name:string;requires_java:number;lifecycle:{status:string;note:string|null}};
export type TechItem={rule_id:string;technology:string;status:string;phase:number;affected_classes:string[];recommended:Candidate;alternatives:{id:string;name:string;reason:string}[];why:string[];steps:string[];prerequisites:string[];coupled_with:string[];risks:string[];
  confidence:{label:string;present:number;total:number;rule:string;inputs:{name:string;present:boolean}[]};feasibility:Check[];feasible:boolean;citations:string[];verification:string;runtime_evidence:{text:string|null;not_measured:string|null}};
export type TechnologyPlanData={status:string;reason?:string;generated_by?:string;selection_rule?:string;phase_rule?:string;language?:{recommendation:string;reason:string};runtime?:{recommendation:string;reason:string;current_java:number|null;target_java:number|null};
  phases?:{number:number;title:string;items:string[];class_count:number;prerequisites:string[];exit_criteria:string[]}[];items?:TechItem[];dropped?:{rule_id:string;missing:string[]}[];feasible?:boolean;limitations?:string[];review?:{note:string}};
type AiResult={ai:{status:string;reason?:string|null;label?:string;recommendations:{rule_id:string;choice:string;rationale:string;citations:string[];verification:string}[];dropped:{reason:string}[]}};

/** The proposed technology plan. It becomes the active plan only when a reviewer approves it (Review tab). */
export function TechnologyPlan({plan,active,activeNote,explainPath}:{plan:TechnologyPlanData;active:boolean;activeNote:string;explainPath:string}){
  const [ai,setAi]=useState<AiResult['ai']|null>(null);const [busy,setBusy]=useState(false);const [error,setError]=useState<unknown>(null);
  if(!plan||plan.status==='NOT_AVAILABLE')return <section className="runtime-card" aria-label="Technology plan"><h2>Technology plan</h2><p role="note">{plan?.reason||'No technology plan was recorded on this proposal.'}</p></section>;
  async function explain(){setBusy(true);setError(null);try{setAi((await post<AiResult>(explainPath,{})).ai);}catch(e){setError(e);}finally{setBusy(false);}}
  const items=plan.items||[];
  return <section className="runtime-card" aria-label="Technology plan"><h2>Technology plan</h2>
    <p role="status"><Badge tone={active?'green':'medium'}>{active?'ACTIVE PLAN':'PROPOSAL'}</Badge> {activeNote}</p>
    <h3>Language and runtime</h3><p><strong>{plan.language?.recommendation.replaceAll('_',' ')}.</strong> {plan.language?.reason}</p><p><strong>{plan.runtime?.recommendation.replaceAll('_',' ')}.</strong> {plan.runtime?.reason}</p>
    <details><summary>How choices and phases are decided</summary><p>{plan.selection_rule}</p><p>{plan.phase_rule}</p></details>
    {(plan.phases||[]).map(phase=><section key={phase.number} aria-label={`Phase ${phase.number}`}><h3>Phase {phase.number}: {phase.title}</h3>
      <p>{phase.items.length} item(s), {phase.class_count} class(es). {phase.prerequisites.length?'Starts after: '+phase.prerequisites.join('; ')+'.':'No earlier phase.'}</p>
      {items.filter(i=>i.phase===phase.number).map(item=><article key={item.rule_id} aria-label={`Technology ${item.technology}`}>
        <h4>{item.technology} ({item.status}) → {item.recommended.name} <Badge tone={item.verification==='CURATED'?'green':'medium'}>{item.verification==='CURATED'?'curated candidate':'unverified, confirm before use'}</Badge></h4>
        <ul>{item.why.map(w=><li key={w}>{w}</li>)}</ul>
        <p><strong>Affected classes ({item.affected_classes.length}):</strong> {item.affected_classes.slice(0,8).map(c=>c.split('.').at(-1)).join(', ')||'none listed'}.</p>
        <h5>Alternatives considered</h5>{item.alternatives.length?<ul>{item.alternatives.map(a=><li key={a.id}><strong>{a.name}</strong>: not chosen because {a.reason}.</li>)}</ul>:<p>No other curated candidate exists for this rule.</p>}
        <h5>Steps</h5><ol>{item.steps.map(s=><li key={s}>{s}</li>)}</ol>
        {item.prerequisites.length>0&&<p><strong>Prerequisites:</strong> {item.prerequisites.join('; ')}.</p>}{item.coupled_with.length>0&&<p><strong>Moves together with:</strong> {item.coupled_with.join(', ')}.</p>}
        {item.risks.length>0&&<><h5>Risks</h5><ul>{item.risks.map(r=><li key={r}>{r}</li>)}</ul></>}
        <h5>Feasibility checks</h5><ul>{item.feasibility.map((c,i)=><li key={i}><strong>{c.check}</strong> {c.status}: {c.detail}</li>)}</ul>
        <p><strong>Confidence {item.confidence.label}</strong> ({item.confidence.present} of {item.confidence.total} inputs): {item.confidence.inputs.map(i=>(i.present?'yes':'no')+' - '+i.name).join('; ')}.</p>
        <p className="fine-print">Evidence: {item.citations.slice(0,4).join(', ')}{item.citations.length>4?`, and ${item.citations.length-4} more`:''}. {item.runtime_evidence.text||'Runtime evidence: not measured, '+item.runtime_evidence.not_measured+'.'}</p>
      </article>)}
      <p className="fine-print">Done when: {phase.exit_criteria.join(' ')}</p></section>)}
    {(plan.dropped||[]).length>0&&<p role="note">Dropped because a cited class, rule or candidate does not exist: {plan.dropped!.map(d=>d.rule_id+' ('+d.missing.join(', ')+')').join('; ')}.</p>}
    <section className="ai-explain" aria-label="AI wording"><button type="button" className="secondary-button" disabled={busy} onClick={()=>void explain()}>{busy?'Asking the local model…':'Add AI wording (optional)'}</button>
      {error?<ErrorBox error={error}/>:null}
      {ai?.status==='AI_GENERATED'&&<><Badge tone="medium">AI-WRITTEN</Badge><p className="fine-print">{ai.label}</p><ul>{ai.recommendations.map((r,i)=><li key={i}><strong>{r.rule_id}</strong> → {r.choice} <Badge tone={r.verification==='CURATED'?'green':'medium'}>{r.verification==='CURATED'?'curated':'unverified, confirm before use'}</Badge>: {r.rationale} <span className="fine-print">{r.citations.join(', ')}</span></li>)}</ul>{ai.dropped.length>0&&<p className="fine-print">{ai.dropped.length} recommendation(s) were removed by the evidence check.</p>}</>}
      {ai?.status==='NOT_AVAILABLE'&&<p className="muted">No AI text shown ({ai.reason}). The plan above is complete without it.</p>}</section>
    <p className="fine-print">{plan.limitations?.join(' ')}</p>
  </section>;
}
