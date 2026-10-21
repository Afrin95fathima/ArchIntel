import {useState} from 'react';
import {useQuery,useQueryClient} from '@tanstack/react-query';
import {api} from '../api';
import {ErrorBox} from '../components';

type Step={name:string;state:string;detail:string|null;at:string|null};
type Route={method:string;shape:string;statuses:number[]};
type FormResult={method:string;shape:string;completed:boolean;statuses:number[];error:string|null};
export type ExplorationJob={id:string;state:string;created_at:string;options:{max_pages:number;max_forms:number;mode:string;artifact_name?:string};steps:Step[];session_id?:string;
  error?:{step:string;code:string;detail:string};limitations:string[];
  exploration?:{summary:{pages:number;forms:number;forms_completed:number;routes:number;failures:number;skipped:number;duration_ms:number};routes:Route[];forms:FormResult[];
    skipped:{url:string;reason:string}[];failures:{url:string;error:string}[];unvisited:string[];stopped_by_time:boolean};
  coverage?:{spans:number;classes:{observed:number|null;total:number|null;percentage:number|null};entry_points?:{observed:number|null;total:number|null;percentage:number|null}}};
type Status={configured:boolean;reachable:boolean;reason?:string;tools?:Record<string,string|boolean|null>};

export const STEP_LABEL:Record<string,string>={CHECK_RUNNER:'Check the runner',CREATE_SESSION:'Create a runtime session',UPLOAD_ARTIFACT:'Send the application to the runner',
  START_APPLICATION:'Start it with the OpenTelemetry agent',EXPLORE:'Explore with REA',STOP_APPLICATION:'Stop the application',COMPLETE_SESSION:'Complete the session'};
const TOOL_LABEL:Record<string,string>={java:'Java',chrome:'Chrome',otel_agent:'OpenTelemetry agent',rea:'REA',docker:'Docker'};

/** Replaces manual testing: the runner starts the application with the agent and REA visits its pages and submits its forms. */
export function AutoExplore({applicationId,analysisId}:{applicationId:string;analysisId:string}){
  const client=useQueryClient();
  const [file,setFile]=useState<File|null>(null);const [pages,setPages]=useState(40);const [formsMax,setForms]=useState(12);const [consent,setConsent]=useState(false);const [mode,setMode]=useState('DEEP');
  const [error,setError]=useState<unknown>(null);const [busy,setBusy]=useState(false);const [open,setOpen]=useState('');
  const status=useQuery({queryKey:['runner-status',applicationId],queryFn:()=>api<Status>('/applications/'+applicationId+'/runtime-sessions/automation'),enabled:!!applicationId,refetchInterval:30000});
  const jobs=useQuery({queryKey:['explorations',applicationId],queryFn:()=>api<{items:ExplorationJob[]}>('/applications/'+applicationId+'/runtime-sessions/explorations'),enabled:!!applicationId,
    refetchInterval:q=>(q.state.data?.items||[]).some(j=>j.state==='RUNNING'||j.state==='QUEUED')?2000:15000});
  const running=(jobs.data?.items||[]).some(j=>j.state==='RUNNING'||j.state==='QUEUED');
  const ready=!!status.data?.configured&&!!status.data?.reachable;
  async function start(){
    if(!file)return;setBusy(true);setError(null);
    try{
      const data=new FormData();data.append('file',file);data.append('analysis_id',analysisId);data.append('max_pages',String(pages));data.append('max_forms',String(formsMax));
      data.append('mode',mode);data.append('confirm_disposable_data',String(consent));
      const job=await api<ExplorationJob>('/applications/'+applicationId+'/runtime-sessions/explore',{method:'POST',body:data});
      setOpen(job.id);await client.invalidateQueries({queryKey:['explorations',applicationId]});
    }catch(e){setError(e);}finally{setBusy(false);}
  }
  const latest=jobs.data?.items||[];
  return <section className="runtime-card auto-explore" aria-label="Explore automatically">
    <h2>Explore automatically</h2>
    <p>Instead of clicking through the application yourself, ArchIntel's runner starts it with the OpenTelemetry agent and REA visits its pages and submits its forms with synthetic values. The result is an ordinary runtime session below.</p>
    <p className="fine-print" role="status">{status.isPending?'Checking the runner…':!status.data?.configured?'The runner is not configured. Start it with scripts/runner-start.sh, then restart ArchIntel so it reads the shared token.'
      :!status.data.reachable?`The runner is not reachable (${status.data.reason}). Start it with scripts/runner-start.sh.`
      :`Runner ready: ${Object.entries(status.data.tools||{}).map(([k,v])=>`${TOOL_LABEL[k]||k} ${v===true?'available':v||'missing'}`).join(', ')}.`}</p>
    {ready&&<div className="runtime-form">
      <label>Runnable application JAR or WAR<input type="file" accept=".jar,.war" aria-label="Runnable application JAR or WAR" onChange={e=>setFile(e.target.files?.[0]||null)}/></label>
      <label>Most pages<input type="number" min={1} max={200} value={pages} onChange={e=>setPages(Number(e.target.value))}/></label>
      <label>Most forms<input type="number" min={0} max={60} value={formsMax} onChange={e=>setForms(Number(e.target.value))}/></label>
      <label>Instrumentation<select aria-label="Instrumentation depth" value={mode} onChange={e=>setMode(e.target.value)}><option value="DEEP">Deep: every application method (recommended for a local copy)</option><option value="STANDARD">Standard</option><option value="BOUNDARY">Boundary only</option></select></label>
      <label className="consent"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>This copy of the application uses a disposable test database. Exploration submits forms and creates data.</label>
      <button disabled={busy||running||!file||!consent||!analysisId} onClick={()=>void start()}>{busy?'Sending…':running?'Exploration running…':'Start exploration'}</button>
    </div>}
    {error?<ErrorBox error={error}/>:null}
    {latest.slice(0,5).map(job=><ExplorationView key={job.id} job={job} open={open===job.id||(open===''&&job===latest[0])} toggle={()=>setOpen(open===job.id?'-':job.id)}/>)}
  </section>;
}

export function ExplorationView({job,open,toggle}:{job:ExplorationJob;open:boolean;toggle:()=>void}){
  const s=job.exploration?.summary;const c=job.coverage?.classes;
  return <article className="exploration">
    <button className="node-link" aria-expanded={open} onClick={toggle}>{new Date(job.created_at).toLocaleString()} · {job.state.toLowerCase()}{job.options.artifact_name?` · ${job.options.artifact_name}`:''}</button>
    {open&&<>
      <ol className="exploration-steps">{job.steps.map(st=><li key={st.name} className={'step-'+st.state.toLowerCase()}><strong>{STEP_LABEL[st.name]||st.name}</strong> <span>{st.state.toLowerCase()}</span>{st.detail&&<small>{st.detail}</small>}</li>)}</ol>
      {job.error&&<p role="alert">Stopped at “{STEP_LABEL[job.error.step]||job.error.step}”: {job.error.code}{job.error.detail?` (${job.error.detail})`:''}.</p>}
      {s&&<p><strong>{s.pages} pages</strong> visited, <strong>{s.forms_completed} of {s.forms} forms</strong> submitted, <strong>{s.routes} routes</strong> observed in {(s.duration_ms/1000).toFixed(0)} s{c?.total?`; classes reached ${c.observed} of ${c.total} (${c.percentage}%)`:''}{job.coverage?`, ${job.coverage.spans.toLocaleString()} spans`:''}.</p>}
      {job.exploration&&<details><summary>Routes observed ({job.exploration.routes.length})</summary><div className="sequence-table"><table><thead><tr><th>Method</th><th>Route</th><th>Status</th></tr></thead><tbody>{job.exploration.routes.map(r=><tr key={r.method+r.shape}><td>{r.method}</td><td><code>{r.shape}</code></td><td>{r.statuses.join(', ')||'none'}</td></tr>)}</tbody></table></div></details>}
      {job.exploration&&job.exploration.forms.length>0&&<details><summary>Forms ({job.exploration.forms.length})</summary><ul className="evidence-list">{job.exploration.forms.map((f,i)=><li key={i}>{f.method} <code>{f.shape}</code>: {f.completed?`submitted (${f.statuses.join(', ')||'no response'})`:`not completed: ${f.error}`}</li>)}</ul></details>}
      {job.exploration&&(job.exploration.skipped.length>0||job.exploration.failures.length>0||job.exploration.unvisited.length>0)&&<details><summary>Not covered</summary><ul className="evidence-list">
        {job.exploration.skipped.map((x,i)=><li key={'s'+i}>Skipped <code>{x.url}</code>: {x.reason.replace(/_/g,' ').toLowerCase()}</li>)}
        {job.exploration.failures.map((x,i)=><li key={'f'+i}>Failed <code>{x.url}</code>: {x.error}</li>)}
        {job.exploration.unvisited.map(u=><li key={u}>Not visited (page limit): <code>{u}</code></li>)}
        {job.exploration.stopped_by_time&&<li>The exploration stopped at its time limit.</li>}</ul></details>}
      <p className="fine-print">{job.limitations.join(' ')}</p>
    </>}
  </article>;
}
