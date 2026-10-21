import {useState} from 'react';
import {useQuery,useQueryClient} from '@tanstack/react-query';
import {api,post} from '../api';
import {ErrorBox} from '../components';

type Gate={id:string;met:boolean;text:string};
type Step={name:string;state:string;detail:string|null};
type Result={name:string;status:string;differences:string[];text_similarity:number|null};
export type ConversionJob={id:string;state:string;created_at:string;candidate_id:string;candidate_name:string;service_name:string;model:string;lane:string;steps:Step[];limitations:string[];
  verdict?:string;error?:{step:string;code:string;detail:string};source?:{commit:string;files:{path:string;bytes:number}[];excluded:{path:string;reason:string}[]};
  generation?:{files:{path:string;bytes:number;rationale:string}[];unresolved_questions:string[];usage:{model:string;prompt_tokens:number|null;output_tokens:number|null;duration_ms:number;estimated_cost_usd:number|null}};
  service?:{state:string;base_url:string|null;build_log_tail?:string};comparison?:{total:number;counts:Record<string,number>;results:Result[];method:string}};
type Repo={id:string;name:string;commit:string;granted:boolean};

export const CONVERT_STEP:Record<string,string>={PRECHECK:'Check every gate again',SELECT_SOURCE:'Select the candidate source inside your grant',GENERATE:'Generate the service with Claude',
  BUILD_SERVICE:'Build and start it in Docker',START_ORIGINAL:'Start the original application',COMPARE:'Replay recorded scenarios on both',STOP_ORIGINAL:'Stop the original application'};
const VERDICT:Record<string,string>={EQUIVALENT:'Every replayed scenario behaved the same',REVIEW_DIFFERENCES:'Some replayed scenarios behaved differently',NOT_COMPARED:'No recorded scenario covered this candidate'};
const ACK='I_APPROVE_SENDING_SELECTED_SOURCE_TO_ANTHROPIC_CLAUDE';

/** Local conversion trial of one service candidate: Claude regenerates it, the runner builds and runs it, REA compares it with the original. */
export function ConvertPanel({versionId,planId,candidate}:{versionId:string;planId:string;candidate:{id:string;name:string;proposal_state:string}}){
  const client=useQueryClient();
  const base=`/architecture-versions/${versionId}/modernization/${planId}/conversions`;
  const [repo,setRepo]=useState('');const [ack,setAck]=useState(false);const [busy,setBusy]=useState(false);const [error,setError]=useState<unknown>(null);
  const [file,setFile]=useState<{jobId:string;path:string}|null>(null);
  const repos=useQuery({queryKey:['convert-repos',base],queryFn:()=>api<{items:Repo[]}>(base+'/repositories')});
  const repoId=repo||repos.data?.items.find(r=>r.granted)?.id||'';
  const gates=useQuery({queryKey:['convert-gates',base,candidate.id,repoId],queryFn:()=>api<{ready:boolean;items:Gate[];model:string;limitations:string[]}>(`${base}/preconditions?candidate_id=${encodeURIComponent(candidate.id)}&repository_id=${encodeURIComponent(repoId)}`),refetchInterval:20000});
  const jobs=useQuery({queryKey:['conversions',base],queryFn:()=>api<{items:ConversionJob[]}>(base),
    refetchInterval:q=>(q.state.data?.items||[]).some(j=>j.state==='RUNNING'||j.state==='QUEUED')?2500:20000});
  const content=useQuery({queryKey:['convert-file',file?.jobId,file?.path],queryFn:()=>api<{path:string;content:string;rationale:string}>(`${base}/${file!.jobId}/files/${file!.path}`),enabled:!!file});
  const mine=(jobs.data?.items||[]).filter(j=>j.candidate_id===candidate.id);
  const running=mine.some(j=>j.state==='RUNNING'||j.state==='QUEUED');
  async function act(fn:()=>Promise<unknown>){setBusy(true);setError(null);try{await fn();await client.invalidateQueries({queryKey:['conversions',base]});await client.invalidateQueries({queryKey:['convert-gates']});}catch(e){setError(e);}finally{setBusy(false);}}
  if(candidate.proposal_state==='TECHNICAL_DOMAIN_NOT_A_SERVICE')return null;
  return <section className="runtime-card convert-panel" aria-label={`Convert ${candidate.name}`}>
    <h3>Convert {candidate.name} locally (trial)</h3>
    <p>Claude ({gates.data?.model||'Claude'}) regenerates this candidate as a standalone service from its source, the runner builds and starts it in Docker next to the original application, and REA replays the recorded scenarios against both. Nothing is merged or deployed.</p>
    <ul className="gate-list" aria-label="Conversion checklist">{(gates.data?.items||[]).map(g=><li key={g.id} className={g.met?'met':'missing'}>{g.met?'Met':'Missing'}: {g.text}</li>)}</ul>
    <label>Source repository<select aria-label="Source repository" value={repoId} onChange={e=>setRepo(e.target.value)}><option value="">Select a registered repository</option>{repos.data?.items.map(r=><option key={r.id} value={r.id} disabled={!r.granted}>{r.name} @ {r.commit.slice(0,7)}{r.granted?'':' (no grant)'}</option>)}</select></label>
    <label className="consent"><input type="checkbox" checked={ack} onChange={e=>setAck(e.target.checked)}/>I approve sending the selected source of {candidate.name} to Anthropic Claude for this one generation.</label>
    <button disabled={busy||running||!ack||!gates.data?.ready} onClick={()=>void act(()=>post(base,{candidate_id:candidate.id,repository_id:repoId,acknowledgement:ACK}))}>{running?'Conversion running…':busy?'Starting…':'Convert with Claude'}</button>
    {!gates.data?.ready&&gates.data&&<p className="fine-print">Complete the missing items above to enable the conversion.</p>}
    {error?<ErrorBox error={error}/>:null}
    {mine.slice(0,3).map(job=><ConversionView key={job.id} job={job} onStop={()=>void act(()=>api(`${base}/${job.id}/service`,{method:'DELETE'}))} onFile={path=>setFile({jobId:job.id,path})}/>)}
    {file&&content.data&&<div className="convert-file" role="region" aria-label={`Generated file ${content.data.path}`}><h4>{content.data.path}</h4><p className="fine-print">{content.data.rationale}</p><pre>{content.data.content}</pre><button onClick={()=>setFile(null)}>Close file</button></div>}
    {content.error?<ErrorBox error={content.error}/>:null}
  </section>;
}

export function ConversionView({job,onStop,onFile}:{job:ConversionJob;onStop:()=>void;onFile:(path:string)=>void}){
  const u=job.generation?.usage;const c=job.comparison;
  return <article className="exploration conversion">
    <strong>{new Date(job.created_at).toLocaleString()} · {job.state.toLowerCase()}</strong>
    <ol className="exploration-steps">{job.steps.map(s=><li key={s.name} className={'step-'+s.state.toLowerCase()}><strong>{CONVERT_STEP[s.name]||s.name}</strong> <span>{s.state.toLowerCase()}</span>{s.detail&&<small>{s.detail}</small>}</li>)}</ol>
    {job.error&&<p role="alert">Stopped at “{CONVERT_STEP[job.error.step]||job.error.step}”: {job.error.code}{job.error.detail?`: ${job.error.detail.slice(0,400)}`:''}</p>}
    {job.verdict&&<p className={'verdict verdict-'+job.verdict.toLowerCase()}><strong>{VERDICT[job.verdict]||job.verdict}</strong>{c?` (${c.counts.EQUIVALENT||0} of ${c.total} equivalent)`:''}.</p>}
    {job.service?.base_url&&job.service.state==='RUNNING'&&<p>Generated service running at <a href={job.service.base_url} target="_blank" rel="noreferrer">{job.service.base_url}</a> <button onClick={onStop}>Stop service</button></p>}
    {job.service?.state==='STOPPED'&&<p className="fine-print">The generated service was stopped.</p>}
    {u&&<p className="fine-print">{u.model}: {u.prompt_tokens?.toLocaleString()} input and {u.output_tokens?.toLocaleString()} output tokens in {Math.round(u.duration_ms/1000)} s{u.estimated_cost_usd!=null?`, estimated $${u.estimated_cost_usd}`:''}.</p>}
    {c&&c.results.length>0&&<details open={job.verdict==='REVIEW_DIFFERENCES'}><summary>Replayed scenarios ({c.total})</summary><ul className="evidence-list">{c.results.map(r=><li key={r.name}><strong>{r.name}</strong>: {r.status.toLowerCase()}{r.text_similarity!=null?` (text similarity ${r.text_similarity})`:''}{r.differences.length>0&&<ul>{r.differences.map((d,i)=><li key={i}>{d}</li>)}</ul>}</li>)}</ul></details>}
    {job.generation&&<details><summary>Generated files ({job.generation.files.length})</summary><ul className="evidence-list">{job.generation.files.map(f=><li key={f.path}><button className="node-link" onClick={()=>onFile(f.path)}>{f.path}</button> <small>{f.rationale}</small></li>)}</ul></details>}
    {job.generation&&job.generation.unresolved_questions.length>0&&<details open><summary>Open questions from Claude ({job.generation.unresolved_questions.length})</summary><ul className="evidence-list">{job.generation.unresolved_questions.map((q,i)=><li key={i}>{q}</li>)}</ul></details>}
    {job.source&&<details><summary>Source sent ({job.source.files.length} files at {job.source.commit.slice(0,7)}), left out ({job.source.excluded.length})</summary><ul className="evidence-list">{job.source.files.map(f=><li key={f.path}>{f.path}</li>)}{job.source.excluded.map(f=><li key={'x'+f.path}>Left out {f.path}: {f.reason.replace(/_/g,' ').toLowerCase()}</li>)}</ul></details>}
    {job.service?.build_log_tail&&<details><summary>Build log (end)</summary><pre>{job.service.build_log_tail}</pre></details>}
    <p className="fine-print">{job.limitations.join(' ')}</p>
  </article>;
}
