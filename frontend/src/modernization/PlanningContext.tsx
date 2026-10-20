import {useQuery} from '@tanstack/react-query';
import {api} from '../api';
import {ErrorBox} from '../components';

type Field={value:string|number|boolean|null;not_measured?:string;unit?:string;text?:string;observed?:number;total?:number};
type Session={id:string;name:string;environment:string;status:string;started_at:string|null;ended_at:string|null;traces:number;spans:number};
export type PlanningContextData={
  version:{id:Field;name:Field;fingerprint:Field;captured_at:Field};scan:{analysis_id:Field;scan_date:Field;algorithm_version:Field};artifact:{name:Field;sha256:Field};
  counts:{classes:Field;packages:Field;domains:Field;class_cycle_groups:Field;aging_technology_findings:Field;entry_points:Field};
  runtime:{sessions:Session[];session_count:number;traces:Field;class_coverage:Field;entry_point_coverage:Field;method_coverage:Field};
  review:{domain_review:Field&{actor?:string;reason?:string}};changes:{state?:string;text:string};takes_into_account:string[];does_not_take_into_account:string[]};

function show(field:Field){return field.not_measured?<span className="muted">not measured: {field.not_measured}</span>:<>{field.text??String(field.value)}{field.unit?` ${field.unit}`:''}</>;}

/** The facts the plan is built on, each with its source or a reason it is not measured. */
export function PlanningContext({versionId}:{versionId:string}){
  const query=useQuery({queryKey:['planning-context',versionId],queryFn:()=>api<PlanningContextData>('/architecture-versions/'+versionId+'/modernization/context'),enabled:!!versionId});
  if(!versionId)return null;
  if(query.error)return <ErrorBox error={query.error}/>;
  const c=query.data;
  if(c&&!c.version)return <section className="runtime-card"><h2>Planning context</h2><p role="alert">The /modernization/context response was incomplete, so no facts are shown.</p></section>;
  if(!c)return <section className="runtime-card"><h2>Planning context</h2><p>Loading the facts for this version…</p></section>;
  const rows:[string,Field][]=[['Architecture version',c.version.name],['Fingerprint',c.version.fingerprint],['Captured',c.version.captured_at],['Scan date',c.scan.scan_date],['Artifact',c.artifact.name],['Artifact SHA-256',c.artifact.sha256],
    ['Classes',c.counts.classes],['Packages',c.counts.packages],['Candidate domains',c.counts.domains],['Class-level cycle groups',c.counts.class_cycle_groups],['Aging-technology findings',c.counts.aging_technology_findings],['Entry points',c.counts.entry_points],
    ['Runtime traces',c.runtime.traces],['Class coverage',c.runtime.class_coverage],['Entry-point coverage',c.runtime.entry_point_coverage],['Method coverage',c.runtime.method_coverage],['Domain review',c.review.domain_review.not_measured?c.review.domain_review:{value:`recorded by ${c.review.domain_review.actor}${c.review.domain_review.reason?': '+c.review.domain_review.reason:''}`}]];
  return <section className="runtime-card" aria-label="Planning context"><h2>Planning context</h2>
    <dl className="context-facts">{rows.map(([label,field])=><div key={label}><dt>{label}</dt><dd>{show(field)}</dd></div>)}</dl>
    <h3>Runtime sessions included ({c.runtime.session_count})</h3>
    {c.runtime.sessions.length?<table><thead><tr><th>Session</th><th>Id</th><th>Status</th><th>Window</th><th>Traces</th><th>Spans</th></tr></thead><tbody>{c.runtime.sessions.map(s=><tr key={s.id}><td>{s.name} ({s.environment})</td><td><code>{s.id}</code></td><td>{s.status}</td><td>{s.started_at??'not started'} to {s.ended_at??'not ended'}</td><td>{s.traces}</td><td>{s.spans}</td></tr>)}</tbody></table>:<p>No runtime session is attached to this version.</p>}
    <h3>Changed since the previous version</h3><p>{c.changes.text}</p>
    <h3>What this plan takes into account</h3><ul>{c.takes_into_account.map(line=><li key={line}>{line}</li>)}</ul>
    <h3>What this plan does not take into account</h3><ul>{c.does_not_take_into_account.map(line=><li key={line}>{line}</li>)}</ul>
  </section>;
}
