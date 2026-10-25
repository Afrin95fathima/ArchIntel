import {useState} from 'react';
import {useQuery,useQueryClient} from '@tanstack/react-query';
import {api} from '../api';
import {ErrorBox} from '../components';

type Step={name:string;state:string;detail:string|null;at:string|null};
type Route={method:string;shape:string;statuses:number[]};
type FormResult={method:string;shape:string;completed:boolean;statuses:number[];error:string|null};
type ApiSummary={requests:number;get_routes:number;get_routes_called:number;statuses:Record<string,number>;scenario_steps:number;scenario_steps_passed:number};
type ScenarioStep={id:string;kind:string;method:string;path:string;status:number|null;state:string;error:string|null;reached?:string|null};
type ApiRequest={phase:string;method:string;template:string;path:string;status:number|null;duration_ms:number|null;error:string|null};
export type ApiExploration={method:'API';summary:ApiSummary;scenarios:{name:string;steps:ScenarioStep[];cleanup?:ScenarioStep[]}[];unresolved:{template:string;missing:string[]}[];
  skipped:string[];requests:ApiRequest[];stopped_by_budget:boolean;duration_ms:number};
type BrowserExploration={summary:{pages:number;forms:number;forms_completed:number;routes:number;failures:number;skipped:number;duration_ms:number};routes:Route[];forms:FormResult[];
    skipped:{url:string;reason:string}[];failures:{url:string;error:string}[];unvisited:string[];stopped_by_time:boolean};
export type ExplorationJob={id:string;state:string;created_at:string;method?:'API';recipe?:{id:string;title:string;name:string};
  options:{max_pages?:number;max_forms?:number;mode:string|null;artifact_name?:string;max_requests?:number|null;scenario_source?:string;passes?:number};steps:Step[];session_id?:string;
  error?:{step:string;code:string;detail:string};limitations:string[];instrumentation?:{mode:string;classes:number;methods:number};
  passes?:{index:number;session_id:string;plan_classes:number;spans:number;requests:number;scenario_steps_passed:number;classes:{observed:number|null;total:number|null;percentage:number|null}}[];
  exploration?:BrowserExploration|ApiExploration;
  coverage?:{spans:number;classes:{observed:number|null;total:number|null;percentage:number|null};entry_points?:{observed:number|null;total:number|null;percentage:number|null}}};
type Status={configured:boolean;reachable:boolean;reason?:string;tools?:Record<string,string|boolean|null>};
type Distribution={id:string;title:string;hint?:string;primary?:boolean};
type Recipe={id:string;title:string;description:string;distribution_hint?:string;distributions:Distribution[];mode:string;passes:number;dependencies:string[];scenarios:{name:string;description:string;steps:number;cleanup:number}[]};

export const STEP_LABEL:Record<string,string>={CHECK_RUNNER:'Check the runner',CREATE_SESSION:'Create a runtime session',UPLOAD_ARTIFACT:'Send the application to the runner',
  START_APPLICATION:'Start it with the OpenTelemetry agent',EXPLORE:'Explore with REA',STOP_APPLICATION:'Stop the application',COMPLETE_SESSION:'Complete the session',
  UPLOAD_DISTRIBUTION:'Send the distribution to the runner',EXPLORE_API:'Call the API routes and run the scenarios',COMBINE_PASSES:'Combine the coverage passes'};
const TOOL_LABEL:Record<string,string>={java:'Java',chrome:'Chrome',otel_agent:'OpenTelemetry agent',rea:'REA',docker:'Docker'};

/**
 * Replaces manual testing. Browser: the runner starts a runnable JAR with the agent and REA visits its pages and submits its forms.
 * API: a launch recipe starts a distribution next to disposable dependencies, and the runner calls the API routes and scenario files.
 */
export function AutoExplore({applicationId,analysisId}:{applicationId:string;analysisId:string}){
  const client=useQueryClient();
  const [method,setMethod]=useState<'BROWSER'|'API'>('BROWSER');
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
    <p>Instead of exercising the application yourself, ArchIntel's runner starts it with the OpenTelemetry agent and drives it: REA visits the pages and submits the forms of a web application, or the runner calls the REST API routes of an application started from a launch recipe. Both methods record an ordinary runtime session, listed under Sessions below.</p>
    <div className="runtime-tabs" role="tablist" aria-label="Exploration method">{([['BROWSER','Web pages (runnable JAR or WAR)'],['API','REST API (distribution with a launch recipe)']] as const).map(([id,label])=>
      <button key={id} role="tab" aria-selected={method===id} className={method===id?'active':''} onClick={()=>setMethod(id)}>{label}</button>)}</div>
    <p className="fine-print" role="status">{status.isPending?'Checking the runner…':!status.data?.configured?'The runner is not configured. Start it with scripts/runner-start.sh, then restart ArchIntel so it reads the shared token.'
      :!status.data.reachable?`The runner is not reachable (${status.data.reason}). Start it with scripts/runner-start.sh.`
      :`Runner ready: ${Object.entries(status.data.tools||{}).map(([k,v])=>`${TOOL_LABEL[k]||k} ${v===true?'available':v||'missing'}`).join(', ')}.`}</p>
    {ready&&method==='API'&&<ApiExploreForm applicationId={applicationId} analysisId={analysisId} running={running} onStarted={async id=>{setOpen(id);await client.invalidateQueries({queryKey:['explorations',applicationId]});}}/>}
    {ready&&method==='BROWSER'&&<div className="runtime-form">
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

function ApiExploreForm({applicationId,analysisId,running,onStarted}:{applicationId:string;analysisId:string;running:boolean;onStarted:(id:string)=>Promise<void>}){
  const recipes=useQuery({queryKey:['launch-recipes',applicationId],queryFn:()=>api<{items:Recipe[]}>('/applications/'+applicationId+'/runtime-sessions/recipes'),enabled:!!applicationId});
  const [recipeId,setRecipeId]=useState('');const [files,setFiles]=useState<Record<string,File|null>>({});const [scenario,setScenario]=useState<File|null>(null);
  const [mode,setMode]=useState('');const [maxRequests,setMaxRequests]=useState(0);const [passes,setPasses]=useState(0);const [busy,setBusy]=useState(false);const [error,setError]=useState<unknown>(null);
  const recipe=recipes.data?.items.find(r=>r.id===recipeId)||recipes.data?.items[0];
  const complete=!!recipe&&recipe.distributions.every(d=>files[d.id]);
  async function start(){
    if(!complete||!recipe)return;setBusy(true);setError(null);
    try{
      const data=new FormData();
      for(const d of recipe.distributions)data.append(d.primary?'file':'file_'+d.id,files[d.id] as File);data.append('analysis_id',analysisId);data.append('recipe_id',recipe.id);data.append('mode',mode);data.append('max_requests',String(maxRequests||0));data.append('passes',String(passes||0));
      if(scenario)data.append('scenario_file',scenario);
      const job=await api<ExplorationJob>('/applications/'+applicationId+'/runtime-sessions/explore-api',{method:'POST',body:data});
      await onStarted(job.id);
    }catch(e){setError(e);}finally{setBusy(false);}
  }
  if(recipes.isPending)return <p className="fine-print">Loading launch recipes…</p>;
  if(!recipes.data?.items.length)return <p className="fine-print">No launch recipe is installed.</p>;
  return <div className="runtime-form">
    <label>Launch recipe<select aria-label="Launch recipe" value={recipe?.id||''} onChange={e=>setRecipeId(e.target.value)}>{recipes.data.items.map(r=><option key={r.id} value={r.id}>{r.title}</option>)}</select></label>
    {recipe&&<p className="fine-print">{recipe.description} Dependencies: {recipe.dependencies.join(', ')||'none'}, each started fresh and removed afterwards. Built-in scenarios: {recipe.scenarios.map(s=>`${s.name} (${s.steps} steps, ${s.cleanup} cleanup)`).join('; ')||'none'}.</p>}
    {recipe?.distributions.map(d=><label key={d.id}>{d.title} (.tar.gz){d.hint&&<small>{d.hint}</small>}<input type="file" accept=".tar.gz,.tgz" aria-label={d.title} onChange={e=>{const f=e.target.files?.[0]||null;setFiles(prev=>({...prev,[d.id]:f}));}}/></label>)}
    <label>Scenario file (optional, JSON; replaces the built-in scenarios)<input type="file" accept=".json" aria-label="Scenario file" onChange={e=>setScenario(e.target.files?.[0]||null)}/></label>
    <label>Instrumentation<select aria-label="API instrumentation depth" value={mode} onChange={e=>setMode(e.target.value)}><option value="">Recipe default ({recipe?.mode.toLowerCase()})</option><option value="DEEP">Deep</option><option value="STANDARD">Standard</option><option value="BOUNDARY">Boundary only</option></select></label>
    <label>Coverage passes (0 = recipe default, {recipe?.passes})<small>Each pass restarts the application on a fresh database and traces up to 400 classes that no earlier pass traced.</small><input type="number" min={0} max={6} value={passes} aria-label="Coverage passes" onChange={e=>setPasses(Number(e.target.value))}/></label>
    <label>Most requests (0 = recipe default)<input type="number" min={0} max={5000} value={maxRequests} onChange={e=>setMaxRequests(Number(e.target.value))}/></label>
    <button disabled={busy||running||!complete||!analysisId} onClick={()=>void start()}>{busy?'Sending…':running?'Exploration running…':'Start API exploration'}</button>
    {error?<ErrorBox error={error}/>:null}
  </div>;
}

export function ExplorationView({job,open,toggle}:{job:ExplorationJob;open:boolean;toggle:()=>void}){
  return <article className="exploration">
    <button className="node-link" aria-expanded={open} onClick={toggle}>{new Date(job.created_at).toLocaleString()} · {job.state.toLowerCase()}{job.recipe?` · ${job.recipe.name}`:''}{job.options.artifact_name?` · ${job.options.artifact_name}`:''}</button>
    {open&&<>
      <ol className="exploration-steps">{job.steps.map(st=><li key={st.name} className={'step-'+st.state.toLowerCase()}><strong>{STEP_LABEL[st.name]||st.name}</strong> <span>{st.state.toLowerCase()}</span>{st.detail&&<small>{st.detail}</small>}</li>)}</ol>
      {job.error&&<p role="alert">Stopped at “{STEP_LABEL[job.error.step]||job.error.step}”: {job.error.code}{job.error.detail?` (${job.error.detail.split('\n')[0]})`:''}.</p>}
      {job.method==='API'?<ApiResult job={job}/>:<BrowserResult job={job}/>}
      {job.coverage&&<p className="fine-print">Coverage counts every class of the static analysis, including modules this run did not start.</p>}
      <p className="fine-print">{job.limitations.join(' ')}</p>
    </>}
  </article>;
}

function ApiResult({job}:{job:ExplorationJob}){
  const x=job.exploration as ApiExploration|undefined;const c=job.coverage?.classes;const e=job.coverage?.entry_points;
  if(!x)return null;const s=x.summary;
  const steps=x.scenarios.flatMap(sc=>[...sc.steps,...(sc.cleanup||[])].map(st=>({...st,scenario:sc.name})));
  return <>
    <p><strong>{s.requests} requests</strong>, <strong>{s.get_routes_called} of {s.get_routes} GET routes</strong> called, <strong>{s.scenario_steps_passed} of {s.scenario_steps} scenario steps</strong> passed in {(x.duration_ms/1000).toFixed(0)} s
      ({Object.entries(s.statuses).map(([k,v])=>`${v} × ${k}`).join(', ')}){c?.total?`; classes reached ${c.observed} of ${c.total} (${c.percentage}%)`:''}{e?.total?`, entry points ${e.observed} of ${e.total} (${e.percentage}%)`:''}{job.coverage?`, ${job.coverage.spans.toLocaleString()} spans`:''}.</p>
    {job.instrumentation&&<p className="fine-print">Instrumentation plan: {job.instrumentation.mode.toLowerCase()}, {job.instrumentation.classes} classes{(job.passes?.length||0)>1?' over all passes':''}, {job.instrumentation.methods} method names{(job.passes?.length||0)>1?' in the last pass':''}.</p>}
    {(job.passes?.length||0)>1&&<details open><summary>Coverage passes ({job.passes!.length})</summary><div className="sequence-table"><table><thead><tr><th>Pass</th><th>Classes traced</th><th>Spans</th><th>Requests</th><th>Classes reached</th><th>Session</th></tr></thead><tbody>
      {job.passes!.map(p=><tr key={p.index}><td>{p.index}</td><td>{p.plan_classes}</td><td>{p.spans.toLocaleString()}</td><td>{p.requests}</td><td>{p.classes.observed} of {p.classes.total}</td><td><code>{p.session_id.slice(0,8)}</code></td></tr>)}</tbody></table></div>
      <p className="fine-print">The combined figures above merge these {job.passes!.length} sessions. Select them together under Sessions to inspect the combined evidence.</p></details>}
    {steps.length>0&&<details><summary>Scenario steps ({steps.length})</summary><div className="sequence-table"><table><thead><tr><th>Scenario</th><th>Step</th><th>Request</th><th>Status</th><th>Result</th></tr></thead><tbody>
      {steps.map((st,i)=><tr key={i}><td>{st.scenario}</td><td>{st.id}{st.kind==='cleanup'?' (cleanup)':''}</td><td><code>{st.method} {st.path}</code></td><td>{st.status??st.error??'none'}{st.reached?` · ${st.reached}`:''}</td><td>{st.state.toLowerCase().replace('_',' ')}</td></tr>)}</tbody></table></div></details>}
    <details><summary>Requests ({x.requests.length}{x.requests.length<s.requests?` of ${s.requests}`:''})</summary><div className="sequence-table"><table><thead><tr><th>Phase</th><th>Request</th><th>Route</th><th>Status</th><th>ms</th></tr></thead><tbody>
      {x.requests.map((r,i)=><tr key={i}><td>{r.phase}</td><td><code>{r.method} {r.path}</code></td><td><code>{r.template}</code></td><td>{r.status??r.error}</td><td>{r.duration_ms}</td></tr>)}</tbody></table></div></details>
    {(x.unresolved.length>0||x.skipped.length>0||x.stopped_by_budget)&&<details><summary>Not covered</summary><ul className="evidence-list">
      {x.unresolved.map(u=><li key={u.template}>Not called <code>{u.template}</code>: no value seen for {u.missing.map(m=>`{${m}}`).join(', ')}</li>)}
      {x.skipped.map(t=><li key={t}>Skipped by the recipe: <code>{t}</code></li>)}
      {x.stopped_by_budget&&<li>The exploration stopped at its Most requests budget or its 15-minute time limit.</li>}</ul></details>}
  </>;
}

function BrowserResult({job}:{job:ExplorationJob}){
  const x=job.exploration as BrowserExploration|undefined;const s=x?.summary;const c=job.coverage?.classes;
  return <>
    {s&&<p><strong>{s.pages} pages</strong> visited, <strong>{s.forms_completed} of {s.forms} forms</strong> submitted, <strong>{s.routes} routes</strong> observed in {(s.duration_ms/1000).toFixed(0)} s{c?.total?`; classes reached ${c.observed} of ${c.total} (${c.percentage}%)`:''}{job.coverage?`, ${job.coverage.spans.toLocaleString()} spans`:''}.</p>}
    {x&&<details><summary>Routes observed ({x.routes.length})</summary><div className="sequence-table"><table><thead><tr><th>Method</th><th>Route</th><th>Status</th></tr></thead><tbody>{x.routes.map(r=><tr key={r.method+r.shape}><td>{r.method}</td><td><code>{r.shape}</code></td><td>{r.statuses.join(', ')||'none'}</td></tr>)}</tbody></table></div></details>}
    {x&&x.forms.length>0&&<details><summary>Forms ({x.forms.length})</summary><ul className="evidence-list">{x.forms.map((f,i)=><li key={i}>{f.method} <code>{f.shape}</code>: {f.completed?`submitted (${f.statuses.join(', ')||'no response'})`:`not completed: ${f.error}`}</li>)}</ul></details>}
    {x&&(x.skipped.length>0||x.failures.length>0||x.unvisited.length>0)&&<details><summary>Not covered</summary><ul className="evidence-list">
      {x.skipped.map((item,i)=><li key={'s'+i}>Skipped <code>{item.url}</code>: {item.reason.replace(/_/g,' ').toLowerCase()}</li>)}
      {x.failures.map((item,i)=><li key={'f'+i}>Failed <code>{item.url}</code>: {item.error}</li>)}
      {x.unvisited.map(u=><li key={u}>Not visited (page limit): <code>{u}</code></li>)}
      {x.stopped_by_time&&<li>The exploration stopped at its time limit.</li>}</ul></details>}
  </>;
}
