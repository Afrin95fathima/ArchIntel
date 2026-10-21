import {useState} from 'react';

export type DomainObservation={id:string;name:string;observed:number;total:number;state:string;unobserved_classes:string[]};
const short=(id:string)=>id.slice(id.lastIndexOf('.',id.lastIndexOf('.')-1)+1);

/** One bar per candidate domain: how many of its classes the selected sessions reached, against the plan's required share. */
export function CoverageMap({observations,target,kinds={},hasRuntime}:{observations:DomainObservation[];target:number;kinds?:Record<string,{kind:string}>;hasRuntime:boolean}){
  const [open,setOpen]=useState('');
  if(!observations.length)return <p>No per-domain coverage was recorded for this version.</p>;
  return <div className="coverage-map" role="list" aria-label="Coverage by domain">
    {observations.map(d=>{const pct=d.total?Math.round(1000*d.observed/d.total)/10:0;const met=hasRuntime&&pct>=target;const technical=kinds[d.id]?.kind==='TECHNICAL';
      return <article key={d.id} role="listitem" className={'coverage-row'+(met?' met':'')} aria-label={`${d.name} coverage`}>
        <div className="coverage-head"><strong>{d.name}</strong>{technical&&<small>technical domain: kept as a library, not a service</small>}<span>{hasRuntime?`${d.observed} of ${d.total} classes (${pct}%)`:`0 of ${d.total} classes: no runtime session`}</span></div>
        <div className="coverage-bar" role="img" aria-label={`${pct}% observed, target ${target}%`}><span className="coverage-fill" style={{width:`${hasRuntime?pct:0}%`}}/><span className="coverage-target" style={{left:`${target}%`}} title={`Plan target ${target}%`}/></div>
        <p className="fine-print">{met?`Meets the ${target}% target the plan asks for.`:hasRuntime?`${Math.max(0,Math.ceil(target*d.total/100)-d.observed)} more ${Math.max(0,Math.ceil(target*d.total/100)-d.observed)===1?'class':'classes'} must be reached to meet the ${target}% target.`:`The plan treats this domain as unobserved.`}</p>
        {d.unobserved_classes.length>0&&<><button aria-expanded={open===d.id} onClick={()=>setOpen(open===d.id?'':d.id)}>{open===d.id?'Hide':'Show'} {d.unobserved_classes.length} unobserved {d.unobserved_classes.length===1?'class':'classes'}</button>{open===d.id&&<ul className="evidence-list">{d.unobserved_classes.map(c=><li key={c}>{short(c)}</li>)}</ul>}</>}
      </article>;})}
  </div>;
}
