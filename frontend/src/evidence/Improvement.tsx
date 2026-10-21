import {useQuery} from '@tanstack/react-query';
import {api} from '../api';

type Domain={id:string;name:string;observed:number;total:number;percentage:number;target_percentage:number;met:boolean;classes_needed:number;unobserved_classes:string[];reachable_by_open_suggestions:number;can_reach_target:boolean};
type Suggestion={discovery_id:string;text:string;entry_class:string;method:string;domain_name:string;up_to_new_classes:number;reachable_unobserved:string[];per_domain:Record<string,number>};
export type ImprovementData={target_percentage:number;conditions:{id:string;met:boolean;text:string}[];domains:Domain[];suggestions:Suggestion[];limits:string[];ready:boolean};
const short=(id:string)=>id.slice(id.lastIndexOf('.',id.lastIndexOf('.')-1)+1);

/** What would move this version toward the evidence level the modernization plan asks for, as upper bounds. */
export function Improvement({versionId}:{versionId:string}){
  const q=useQuery({queryKey:['improvement',versionId],queryFn:()=>api<ImprovementData>('/architecture-versions/'+versionId+'/improvement'),enabled:!!versionId,refetchInterval:5000});
  if(q.error)return <p role="alert">The improvement estimate could not be loaded for this version.</p>;
  const d=q.data;if(!d)return <p role="status">Estimating what would improve this version…</p>;
  const open=d.domains.filter(x=>!x.met);
  return <section className="runtime-card evidence-improvement" aria-label="What would improve this plan"><h2>What would improve this plan</h2>
    <p>{d.ready?`This version already meets every condition the plan checks, including the ${d.target_percentage}% class coverage per domain.`:`The plan asks for ${d.target_percentage}% of each domain's classes to be observed, a runtime session and reviewed domain boundaries. ${open.length} of ${d.domains.length} domains are below the target.`}</p>
    <ul className="evidence-list">{d.conditions.map(c=><li key={c.id}>{c.met?'Met: ':'Not met: '}{c.text}</li>)}</ul>
    {open.length>0&&<div className="sequence-table"><table><thead><tr><th>Domain</th><th>Observed</th><th>More classes needed</th><th>Open suggestions can reach</th><th>Target reachable this way</th></tr></thead><tbody>{open.map(x=><tr key={x.id}><td><strong>{x.name}</strong></td><td>{x.observed} of {x.total} ({x.percentage}%)</td><td>{x.classes_needed}</td><td>up to {x.reachable_by_open_suggestions}</td><td>{x.can_reach_target?'Yes':'No: needs other flows'}</td></tr>)}</tbody></table></div>}
    {d.suggestions.length>0&&<><h3>Best next flows to exercise</h3><ol className="evidence-list">{d.suggestions.slice(0,5).map(s=><li key={s.discovery_id}><strong>{short(s.entry_class)}.{s.method}</strong> in {s.domain_name}: up to {s.up_to_new_classes} more {s.up_to_new_classes===1?'class':'classes'}{s.up_to_new_classes>0&&<> ({Object.entries(s.per_domain).map(([n,c])=>`${n} ${c}`).join(', ')})</>}</li>)}</ol></>}
    <p className="fine-print">{d.limits.join(' ')}</p></section>;
}
