import {useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {api} from '../api';

type Candidate={id:string;name:string;repository_name:string;proposal_state:string;class_ids:string[];dependencies:string[];consumers:string[];decision:string;readiness:number;blockers:string[]};
type Plan={id:string;document:{microservice_decomposition?:{service_candidates:Candidate[];status:string}};reviews:{state:string}[]};
type Summary={id:string;strategy:string;objective:string};
const STATE:Record<string,string>={CANDIDATE_REQUIRES_REVIEW:'Candidate service, needs business review',TECHNICAL_DOMAIN_NOT_A_SERVICE:'Not a service: keep as shared configuration or a library'};

/** The approved or proposed target next to what exists today. Proposal only: no code is generated or changed. */
export function TargetView({versionId,domains}:{versionId:string;domains:{id:string;name:string;classes:string[]}[]}){
  const plans=useQuery({queryKey:['evidence-plans',versionId],queryFn:()=>api<Summary[]>('/architecture-versions/'+versionId+'/modernization'),enabled:!!versionId});
  const [chosen,setChosen]=useState('');
  const planId=chosen||plans.data?.[0]?.id||'';
  const plan=useQuery({queryKey:['evidence-plan',versionId,planId],queryFn:()=>api<Plan>('/architecture-versions/'+versionId+'/modernization/'+planId),enabled:!!planId});
  if(plans.error)return <p role="alert">The saved plans of this version could not be loaded.</p>;
  if(plans.data&&!plans.data.length)return <section className="runtime-card"><h2>Current and proposed architecture</h2><p>No modernization plan has been saved for this version. Save one in Modernization to see the proposed services next to the current domains.</p></section>;
  const candidates=plan.data?.document.microservice_decomposition?.service_candidates||[];
  const latest=plan.data?.reviews.at(-1)?.state;
  const names=Object.fromEntries(domains.map(d=>[d.id,d.name]));
  return <section className="runtime-card evidence-target" aria-label="Current and proposed architecture"><h2>Current and proposed architecture</h2>
    <p>Left: the domains this version found in the application today. Right: the services the saved plan proposes. This is a proposal only; no code was generated or changed.</p>
    {plans.data&&plans.data.length>1&&<label>Plan<select value={planId} onChange={e=>setChosen(e.target.value)}>{plans.data.map(p=><option key={p.id} value={p.id}>{p.strategy}: {p.objective.slice(0,60)}</option>)}</select></label>}
    {plan.data&&<p className="fine-print">{latest?`Latest review: ${latest.replace(/_/g,' ').toLowerCase()}.`:'This plan has no recorded review.'}</p>}
    {plan.data&&!candidates.length&&<p>This plan does not list service candidates. Plans saved before service proposals existed do not carry them; save a new plan.</p>}
    {candidates.length>0&&<div className="sequence-table"><table><thead><tr><th>Today: domain</th><th>Proposed</th><th>Depends on</th><th>Plan action</th></tr></thead><tbody>{candidates.map(c=><tr key={c.id}><td><strong>{names[c.id]||c.name}</strong><small>{c.class_ids.length} classes</small></td><td>{c.repository_name}<small>{STATE[c.proposal_state]||c.proposal_state}</small></td><td>{c.dependencies.map(i=>names[i]||i).join(', ')||'No other domain'}</td><td>{c.decision.replace(/_/g,' ').toLowerCase()}{c.blockers.length>0&&<small>{c.blockers.length} {c.blockers.length===1?'blocker':'blockers'}</small>}</td></tr>)}</tbody></table></div>}
  </section>;
}
