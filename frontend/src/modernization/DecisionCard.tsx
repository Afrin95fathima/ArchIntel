import {useState} from 'react';
import {post} from '../api';
import {Badge, ErrorBox} from '../components';
import {aiReason} from '../insight/shared';

export type Decision={id:string;domain_id:string;kind:string;action:string;blockers:string[];finding_ids:string[];fact_ids:string[];evidence_ids:string[]};
type Reason={rule_id:string;severity:string;text:string;measured:Record<string,unknown>;threshold:Record<string,unknown>;subjects:string[];evidence_ids:string[];fact_count:number;measured_fields_recorded:boolean};
type AiBlock={status:string;reason?:string|null;label?:string;sentences?:{text:string;citations:string[]}[];dropped?:{reason:string}[]};
type Explanation={reasons:Reason[];decision:Decision;decision_rule:{rule_id:string;action:string};ai:AiBlock};

const pairs=(values:Record<string,unknown>)=>Object.entries(values).map(([k,v])=>`${k} = ${v===null||v===undefined?'not measured':String(v)}`).join('; ');

/** One decision with its own explanation state, so a click on one item never loads, disables or fills another. */
export function DecisionCard({base,versionId,planId,decision,name}:{base:string;versionId:string;planId:string;decision:Decision;name:string}){
  const [result,setResult]=useState<Explanation|null>(null);
  const [open,setOpen]=useState(false);
  const [busy,setBusy]=useState(false);
  const [aiBusy,setAiBusy]=useState(false);
  const [error,setError]=useState<unknown>(null);
  async function ask(withAi:boolean){
    const set=withAi?setAiBusy:setBusy;
    set(true);setError(null);
    try{
      const answer=await post<Explanation>(base+'/'+planId+'/explain',{question:'WHY',decision_id:decision.id,...(withAi?{with_ai:true}:{})});
      setResult(answer);setOpen(true);
    }catch(e){setError(e);}finally{set(false);}
  }
  function toggle(){
    if(result){setOpen(value=>!value);return;}
    void ask(false);
  }
  return <article aria-label={'Decision '+name}>
    <h3>{name}: {decision.kind}</h3><p>{decision.action}</p><p>Blockers: {decision.blockers.join(', ')}</p>
    <button type="button" disabled={busy} aria-expanded={open} aria-label={(open?'Hide explanation: ':'Explain why: ')+name} onClick={toggle}>{busy?'Explaining…':open?'Hide explanation':'Explain why'}</button>
    {error?<ErrorBox error={error}/>:null}
    {open&&result&&<section aria-label={'Explanation: '+name} className="decision-explanation">
      <p><strong>Decision rule:</strong> {result.decision_rule.rule_id}. {result.decision_rule.action}</p>
      {result.reasons.map((r,i)=><div key={r.rule_id+i} className="decision-reason">
        <p><strong>Rule {r.rule_id}</strong> · {r.severity}</p><p>{r.text}</p>
        {r.measured_fields_recorded?<>
          <p>Measured: {pairs(r.measured)}</p><p>Threshold: {pairs(r.threshold)}</p><p>Involved: {r.subjects.join(', ')||'none named'}</p>
        </>:<p>Measured value and threshold were not recorded: this proposal was saved before rule version modernization-intelligence-4. Create a new proposal to see them.</p>}
        <p>Evidence ids: {r.evidence_ids.join(', ')||'none'} · {r.fact_count} supporting fact(s)</p>
      </div>)}
      {result.decision.fact_ids.slice(0,50).map(f=><p key={f}><a target="_blank" rel="noreferrer" href={'/api/v1/architecture-versions/'+versionId+'/facts/'+f+'/provenance'}>Inspect fact {f.slice(0,8)} and supporting evidence</a></p>)}
      {result.decision.fact_ids.length>0&&<p>{result.decision.fact_ids.length} supporting facts; the first 50 links are shown. The JSON export lists all of them.</p>}
      <div className="ai-explain">
        <button type="button" className="secondary-button" disabled={aiBusy} onClick={()=>void ask(true)}>{aiBusy?'Asking the local model…':'Add AI wording (optional)'}</button>
        {result.ai.status==='AI_GENERATED'&&<><Badge tone="medium">AI-GENERATED</Badge><p className="fine-print">{result.ai.label}</p>
          <ul className="ai-sentences">{(result.ai.sentences||[]).map((s,i)=><li key={i}>{s.text} {s.citations.map(c=><span key={c} className="citation-chip" title={c}>{c.slice(0,16)}</span>)}</li>)}</ul></>}
        {result.ai.status==='NOT_AVAILABLE'&&<p className="muted">No AI text shown: {aiReason(result.ai.reason)}. The rule, value and evidence above are complete without it.</p>}
      </div>
    </section>}
  </article>;
}
