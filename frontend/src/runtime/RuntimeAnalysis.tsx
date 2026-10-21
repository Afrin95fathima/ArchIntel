import {useEffect,useState} from 'react';
import {useQuery,useQueryClient} from '@tanstack/react-query';
import {api,post} from '../api';
import {PageTitle,ErrorBox} from '../components';
import type {Application,Analysis} from '../types';
import type {RuntimeSession,RuntimeEvidence,AgentConfiguration,RuntimeGraphData,RuntimeEdge,InstrumentationPlan} from './types';
import {RuntimeGraph,evidenceColors} from './RuntimeGraph';
import {SuggestedTests} from '../insight/SuggestedTests';
import {Performance} from '../insight/Performance';
import {publishAssistantContext} from '../assistantContext';
import {MappingDetails,DatabaseCallers} from './RuntimeMappingTables';
import './runtime.css';

type CoverageKind='classes'|'entry_points'|'methods'|'dependencies'|'domains';
type CoverageState='ALL'|'OBSERVED'|'NOT_OBSERVED';
type CoverageDetailItem={id:string;name:string;state:'OBSERVED'|'NOT_OBSERVED'|'UNKNOWN';observation_state?:string;package_name?:string;domain_name?:string;class_name?:string;signature?:string;annotations?:string[];evidence?:string[];evidence_refs?:{session_id:string;trace_id:string;span_id:string}[];observed_spans?:number|null;observed_calls?:number;source?:string;target?:string;source_domain?:string;target_domain?:string;observed?:number;total?:number;observed_classes?:string[];unobserved_classes?:string[];suggestion?:string|null};
type CoverageDetailPage={kind:CoverageKind;status:'AVAILABLE'|'UNAVAILABLE';metric:{observed:number|null;total:number|null;percentage:number|null;status:string;reason?:string};reason:string;items:CoverageDetailItem[];total:number;offset:number;limit:number};

export function RuntimeAnalysis({applications,analyses,currentApplicationId,onApplication}:{applications:Application[];analyses:Analysis[];currentApplicationId?:string;onApplication?:(applicationId:string)=>void}){
  const client=useQueryClient();const [appId,setApp]=useState('');const [analysisId,setAnalysis]=useState('');
  const [name,setName]=useState('Runtime observation');const [environment,setEnvironment]=useState('LOCAL');
  const [mode,setMode]=useState('BOUNDARY');const [packages,setPackages]=useState('');
  const [excluded,setExcluded]=useState('');const [binding,setBinding]=useState('STRICT');
  const [preview,setPreview]=useState<{request:string;plan:InstrumentationPlan}|null>(null);
  const [selected,setSelected]=useState<string[]>([]);const [agent,setAgent]=useState<AgentConfiguration|null>(null);
  const [error,setError]=useState<unknown>(null);const [busy,setBusy]=useState(false);
  const [tab,setTab]=useState('Coverage');const [view,setView]=useState('unified');const [level,setLevel]=useState('domains');
  const [coverageKind,setCoverageKind]=useState<CoverageKind|null>(null);const [coverageFilter,setCoverageFilter]=useState<CoverageState>('ALL');const [coverageSearch,setCoverageSearch]=useState('');const [coverageOffset,setCoverageOffset]=useState(0);
  const [edge,setEdge]=useState<RuntimeEdge|null>(null);const [question,setQuestion]=useState('What does runtime coverage show?');
  const [answer,setAnswer]=useState<{answer:string;facts:{text:string;source:string}[]}|null>(null);
  const effectiveApp=appId||currentApplicationId||applications[0]?.id||'';
  useEffect(()=>{if(effectiveApp)onApplication?.(effectiveApp);},[effectiveApp]);
  const available=analyses.filter(a=>a.application_id===effectiveApp&&a.status==='COMPLETED');
  const effectiveAnalysis=analysisId||available[0]?.id||'';
  const sessions=useQuery({queryKey:['runtime-sessions',effectiveApp],queryFn:()=>api<RuntimeSession[]>('/applications/'+effectiveApp+'/runtime-sessions'),enabled:!!effectiveApp,refetchInterval:3000});
  const selection=selected.join(',');const sid=selected[0];
  useEffect(()=>{const found=sessions.data?.find(x=>x.id===sid);publishAssistantContext(found?{kind:'session',id:found.id,label:found.name}:null);return()=>publishAssistantContext(null);},[sid,sessions.data]);
  const evidence=useQuery({queryKey:['runtime-evidence',effectiveApp,selection],queryFn:()=>api<RuntimeEvidence>('/applications/'+effectiveApp+'/architecture/unified?runtime_session_ids='+selection),enabled:!!selection,refetchInterval:10000});
  const coverageDetails=useQuery({queryKey:['runtime-coverage-details',effectiveApp,selection,coverageKind,coverageFilter,coverageSearch,coverageOffset],queryFn:()=>{const params=new URLSearchParams({runtime_session_ids:selection,kind:coverageKind||'classes',state:coverageFilter,offset:String(coverageOffset),limit:'50'});if(coverageSearch.trim())params.set('q',coverageSearch.trim());return api<CoverageDetailPage>('/applications/'+effectiveApp+'/architecture/unified/coverage-details?'+params.toString());},enabled:!!selection&&!!coverageKind});
  const graph=useQuery({queryKey:['runtime-view',effectiveApp,selection,level,view],queryFn:()=>api<RuntimeGraphData>('/applications/'+effectiveApp+'/architecture/unified/'+level+'?runtime_session_ids='+selection+'&graph_kind='+view),enabled:!!selection&&tab==='Graph',refetchInterval:10000});
  async function action(fn:()=>Promise<void>){setError(null);setBusy(true);try{await fn();await client.invalidateQueries({queryKey:['runtime-sessions']});await client.invalidateQueries({queryKey:['runtime-evidence']});}catch(e){setError(e);}finally{setBusy(false);}}
  const data=evidence.data;
  const requestBody={analysis_id:effectiveAnalysis,name,environment,mode,include_packages:packages.split(',').map(x=>x.trim()).filter(Boolean),exclude_packages:excluded.split(',').map(x=>x.trim()).filter(Boolean),binding_mode:binding};
  const previewPlan=preview?.request===JSON.stringify(requestBody)?preview.plan:null;
  function download(){if(!data)return;const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='archintel-runtime-report.json';a.click();URL.revokeObjectURL(url);}
  return <div className="runtime-page"><PageTitle eyebrow="DYNAMIC ANALYSIS" title="Observe architecture in motion." description="Connect a Java application, exercise representative flows, and compare observed behavior with its static architecture."/>
    <div className="notice">Runtime evidence is scoped to selected sessions. Unobserved does not mean unused. Keep this prototype on localhost; management access requires a workspace account.</div>
    <p><a href="/api/v1/manual/phase3-user">Runtime user-flow guide</a> · <a href="/api/v1/manual/phase3-developer">Developer documentation</a></p>
    {(error||sessions.error||evidence.error)&&<ErrorBox error={error||sessions.error||evidence.error}/>}
    <section className="runtime-card"><h2>Create an observation session</h2><form className="runtime-form" onSubmit={e=>{e.preventDefault();void action(async()=>{const created=await post<{session:RuntimeSession;agent:AgentConfiguration}>('/applications/'+effectiveApp+'/runtime-sessions',requestBody);setSelected([created.session.id]);setAgent(created.agent);});}}>
      <label>Application<select aria-label="Runtime application" value={effectiveApp} onChange={e=>{setApp(e.target.value);setAnalysis('');setSelected([]);setCoverageKind(null);setAgent(null);}}>{applications.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
      <label>Static baseline<select aria-label="Runtime static baseline" value={effectiveAnalysis} onChange={e=>setAnalysis(e.target.value)}>{available.map(a=><option key={a.id} value={a.id}>{a.id.slice(0,8)} · {a.created_at.slice(0,10)}</option>)}</select></label>
      <label>Session name<input required value={name} onChange={e=>setName(e.target.value)} maxLength={160}/></label><label>Environment<input value={environment} onChange={e=>setEnvironment(e.target.value)} maxLength={80}/></label>
      <label>Instrumentation depth<select value={mode} onChange={e=>setMode(e.target.value)}><option>BOUNDARY</option><option>STANDARD</option><option>DEEP</option></select></label>
      <label>Application package prefixes<input placeholder="com.example., org.example." value={packages} onChange={e=>setPackages(e.target.value)}/></label>
      <label>Exclude package prefixes<input placeholder="com.example.internal" value={excluded} onChange={e=>setExcluded(e.target.value)}/></label>
      <label>Telemetry binding<select value={binding} onChange={e=>setBinding(e.target.value)}><option value="STRICT">Strict service + artifact declaration</option><option value="COMPATIBLE">Compatible (missing identity stays unverified)</option></select></label>
      <button disabled={busy||!effectiveAnalysis} type="button" onClick={()=>void action(async()=>{const plan=await post<InstrumentationPlan>('/applications/'+effectiveApp+'/runtime-sessions/plan',requestBody);setPreview({request:JSON.stringify(requestBody),plan});})}>Preview instrumentation plan</button>
      <button disabled={busy||!effectiveAnalysis} type="submit">Create runtime session</button>
    </form>{previewPlan&&<PlanDetails plan={previewPlan}/>}<p>Strict binding requires the generated service.name and the archintel.artifact.sha256 resource attribute. Both are declared by the sender (service.name, SHA-256), not proof of the running binary.</p>{!effectiveAnalysis&&<p>Complete a static analysis first to establish the correct application baseline.</p>}</section>
    {agent&&<section className="runtime-card"><h2>Connect your Java application</h2><p>Set these variables in the PowerShell terminal that will launch your application. The bearer token is shown only now; it is not saved in browser storage.</p><pre>{Object.entries(agent.environment).map(([key,value])=>`$env:${key} = '${value.replaceAll("'","''")}'`).join('\n')+'\n'+agent.command}</pre><p>{agent.note}</p>{agent.plan&&<PlanDetails plan={agent.plan}/>}<details><summary>Review {agent.instrumentation_plan.length} selected application classes</summary>{agent.instrumentation_plan.map(p=><p key={p.class_name}><code>{p.class_name}</code> — {p.reason}</p>)}</details><button onClick={()=>setAgent(null)}>Hide connection settings</button></section>}
    <section className="runtime-card"><h2>Runtime sessions</h2><p>Select one or more sessions with the same static baseline to combine evidence. Connection status comes from received telemetry.</p>
      <table><thead><tr><th>Select</th><th>Session / environment</th><th>Status</th><th>Agent</th><th>Traces / spans</th><th>Actions</th></tr></thead><tbody>{sessions.data?.map(s=><tr key={s.id}><td><input type="checkbox" aria-label={'Select '+s.name} checked={selected.includes(s.id)} onChange={e=>{setSelected(e.target.checked?[...selected,s.id]:selected.filter(i=>i!==s.id));setEdge(null);setCoverageKind(null);}}/></td><td>{s.name}<small>{s.environment} · {s.id.slice(0,8)}</small></td><td>{s.status}{s.dropped_count>0&&<small>{s.dropped_count} dropped</small>}</td><td>{s.agent_status}</td><td>{s.trace_count} / {s.span_count}</td><td><button disabled={busy||s.status!=='CREATED'} onClick={()=>void action(async()=>{await post('/runtime-sessions/'+s.id+'/start');})}>Start</button> <button disabled={busy||s.status==='COMPLETED'} onClick={()=>void action(async()=>{await post('/runtime-sessions/'+s.id+'/stop');})}>Stop</button> <button disabled={busy} onClick={()=>void action(async()=>{const r=await post<{agent:AgentConfiguration}>('/runtime-sessions/'+s.id+'/rotate-token');setAgent(r.agent);})}>New token</button></td></tr>)}</tbody></table>
      {!sessions.data?.length&&<p>No runtime sessions yet. Creating a session does not start or execute the Java application.</p>}</section>
    {data&&<><div className="runtime-tabs">{['Coverage','Next tests','Performance','Graph','Mapping','Flows','Database','Modernization','Assistant'].map(t=><button className={tab===t?'active':''} key={t} onClick={()=>setTab(t)}>{t}</button>)}<button onClick={download}>Export evidence</button></div>
      {tab==='Coverage'&&<>
        <p className="coverage-help">Select a card to inspect the exact static items and what the chosen runtime sessions observed. Unobserved means “not seen in these sessions,” not “unused.”</p>
        <div className="runtime-metrics">
          {(['classes','entry_points','methods','dependencies','domains'] as const).map(key=>{
            const metric=data.coverage[key];
            const label=({classes:'Classes','entry_points':'Entry points',methods:'Methods',dependencies:'Dependencies',domains:'Domains'} as const)[key];
            const isOpen=coverageKind===key;
            return <button type="button" className={'runtime-card coverage-tile'+(isOpen?' selected':'')} key={key} aria-expanded={isOpen} aria-controls="coverage-detail-panel" onClick={()=>{setCoverageKind(isOpen?null:key);setCoverageFilter('ALL');setCoverageSearch('');setCoverageOffset(0);}}>
              <span className="coverage-tile__label">{label}</span>
              <strong>{metric.percentage===null?'Unavailable':metric.percentage+'%'}</strong>
              <span className="coverage-tile__count">{metric.observed??'—'} / {metric.total??'—'} observed</span>
              <span className="coverage-tile__action">{isOpen?'Hide details':'View observed and unobserved items'}</span>
              {metric.reason&&<small>{metric.reason}</small>}
            </button>;
          })}
        </div>
        {coverageKind&&<CoverageDetailsPanel kind={coverageKind} filter={coverageFilter} setFilter={value=>{setCoverageFilter(value);setCoverageOffset(0);}} search={coverageSearch} setSearch={value=>{setCoverageSearch(value);setCoverageOffset(0);}} offset={coverageOffset} setOffset={setCoverageOffset} result={coverageDetails} onRefresh={()=>void coverageDetails.refetch()} onClose={()=>setCoverageKind(null)}/>}
        <section className="runtime-card"><h2>Observed versus unobserved code</h2><p>Dynamic coverage confidence is {data.coverage.classes.observed ?? 'Unavailable'} observed of {data.coverage.classes.total ?? 'Unavailable'} classes{data.coverage.classes.percentage===null?'':` (${data.coverage.classes.percentage}%)`}. It is not tool accuracy and not a vulnerability score. Exercise representative routes, jobs, and message flows to improve observation; unobserved does not prove unused.</p><p>{data.coverage.note}</p><p>{data.coverage.unresolved_node_count} unresolved/resource nodes · {data.coverage.missing_parent_count} missing parents</p>{data.coverage.domain_observations.map(d=><details key={d.id}><summary>{d.name}: {d.state.replaceAll('_',' ')} ({d.observed}/{d.total} classes)</summary><p>{d.unobserved_classes.join(', ')||'All static classes observed; observed = a mapped span, not complete behavior.'}</p></details>)}{data.recommendations.map((r,i)=><p key={i}><b>{r.kind}</b>: {r.text} {r.note}</p>)}</section>
      </>}      {tab==='Next tests'&&<SuggestedTests analysisId={data.analysis_id} sessions={selection}/>}
      {tab==='Performance'&&<Performance analysisId={data.analysis_id} sessions={selection} revision={(sessions.data||[]).filter(x=>selected.includes(x.id)).map(x=>x.id+':'+x.status+':'+x.span_count).join(',')}/>}
      {tab==='Coverage'&&<section className="runtime-card"><h2>Evidence quality</h2>{data.quality?.scope?<><p>{data.quality.binding_note}</p><p>{data.quality.accepted_spans} accepted spans · {data.quality.duplicate_spans} duplicates · {data.quality.conflicting_spans} conflicts · {data.quality.dropped_spans} dropped</p><p>{data.quality.declared_match_spans} declared matches · {data.quality.unverified_spans} unverified spans · {data.quality.missing_parents} missing parents · {data.quality.invalid_parent_links} invalid parent links</p>{data.quality.warnings.map(w=><p key={w}>{w}</p>)}<h3>Method mapping</h3>{Object.entries(data.quality.method_mapping).map(([key,value])=><p key={key}>{key}: {value}</p>)}<h3>Observation scope</h3>{data.quality.scope.map(scope=><p key={scope.session_id}>{scope.session_id.slice(0,8)} · {scope.binding_mode} · {scope.plan_version}<br/><code>{scope.plan_sha256||'Plan digest unavailable'}</code></p>)}<p>Derived with {data.derivation_version}. Counts describe the selected evidence; they do not establish complete behavior coverage.</p></>:<p>This archived report predates quality diagnostics. Its original evidence is preserved.</p>}</section>}
      {tab==='Graph' &&<section className="runtime-card"><div className="runtime-tabs"><select aria-label="Runtime graph mode" value={view} onChange={e=>{setView(e.target.value);setEdge(null);}}><option value="unified">Unified selected sessions</option><option value="runtime">Runtime selected sessions</option><option value="static">Static baseline</option></select><select aria-label="Runtime graph level" value={level} onChange={e=>{setLevel(e.target.value);setEdge(null);}}>{['domains','packages','classes'].map(l=><option key={l}>{l}</option>)}</select></div><div className="runtime-legend">{Object.entries(evidenceColors).map(([k,c])=><span key={k}><i style={{background:c}}/>{k.replaceAll('_',' ')}</span>)}</div>{graph.error?<ErrorBox error={graph.error}/>:graph.data&&<RuntimeGraph data={view==='static'?{nodes:graph.data.nodes.filter(n=>n.evidence_type!=='DYNAMIC_ONLY'),edges:graph.data.edges.filter(e=>e.evidence_type!=='DYNAMIC_ONLY'&&!(e.evidence_types?.length===1&&e.evidence_types[0]==='DYNAMIC_ONLY'))}:graph.data} onEdge={setEdge}/>}{edge&&<div className="runtime-edge"><h3>{edge.source} → {edge.target}</h3><p>{edge.evidence_type||edge.evidence_types?.join(', ')||'Observed runtime dependency'} · {edge.call_count} calls</p><p>Static types: {edge.static_types?.join(', ')||'See class-level evidence'}</p>{edge.evidence?.map((e,i)=><a key={i} href={`/api/v1/runtime-sessions/${e.session_id}/spans/${e.trace_id}/${e.span_id}`} target="_blank" rel="noreferrer">Inspect sanitized span {e.span_id}</a>)}</div>}</section>}
      {tab==='Mapping'&&<MappingDetails report={data.mapping_report}/>}
      {tab==='Flows'&&<section className="runtime-card"><h2>Observed request groups</h2><p>Grouped by entry route and participating classes; class lists do not imply a complete execution order.</p>{data.flows.map(f=><details key={f.id}><summary>{f.http_method} {f.entry_point} · {f.trace_count} traces · {f.error_count} errors</summary><p>{f.classes.join(', ')}</p><p>Average entry duration: {(f.total_duration_ms/f.trace_count).toFixed(2)} ms</p></details>)}</section>}
      {tab==='Database'&&<DatabaseCallers rows={data.database} summary={data.database_summary}/>}
      {tab==='Modernization'&&<section className="runtime-card"><h2>Structural and runtime readiness</h2><p>Low coverage reduces confidence. It does not subtract points from the structural Readiness score. The static dependency-first order is retained.</p><table><thead><tr><th>Domain</th><th>Structural</th><th>Runtime</th><th>Combined</th><th>Observation confidence</th><th>Difficulty</th></tr></thead><tbody>{data.modernization.map(m=><tr key={m.domain_id}><td><details><summary>{m.recommended_order}. {m.domain_name}</summary><p>{m.formula}</p><p>{m.risks.join(' ')}</p></details></td><td>{m.structural_score}</td><td>{m.runtime_score??'Unknown'}</td><td>{m.combined_score}</td><td>{Math.round(m.coverage_confidence*100)}%<small>{m.confidence}</small></td><td>{m.extraction_difficulty}</td></tr>)}</tbody></table></section>}
      {tab==='Assistant'&&<section className="runtime-card"><h2>Ask about the first selected session</h2><form onSubmit={e=>{e.preventDefault();void action(async()=>setAnswer(await post('/runtime-sessions/'+sid+'/assistant/query',{question})));}}><label>Runtime question<input value={question} onChange={e=>setQuestion(e.target.value)}/></label><button disabled={busy}>Ask runtime assistant</button></form>{answer&&<><p>{answer.answer}</p>{answer.facts.map((f,i)=><p key={i}>{f.text} <a href={f.source} target="_blank" rel="noreferrer">Evidence</a></p>)}</>}</section>}
      <details className="runtime-card"><summary>Evidence limitations</summary>{data.limitations.map(l=><p key={l}>{l}</p>)}</details>
    </>}
  </div>;
}

function CoverageDetailsPanel({kind,filter,setFilter,search,setSearch,offset,setOffset,result,onRefresh,onClose}:{kind:CoverageKind;filter:CoverageState;setFilter:(value:CoverageState)=>void;search:string;setSearch:(value:string)=>void;offset:number;setOffset:(value:number)=>void;result:{data?:CoverageDetailPage;isPending:boolean;error:unknown};onRefresh:()=>void;onClose:()=>void}){
  const labels:Record<CoverageKind,string>={classes:'Classes',entry_points:'Entry points',methods:'Methods',dependencies:'Dependencies',domains:'Domains'};
  const data=result.data;
  return <section id="coverage-detail-panel" className="runtime-card coverage-detail" aria-live="polite">
    <header className="coverage-detail__header"><div><span className="coverage-eyebrow">STATIC BASELINE + SELECTED RUNTIME SESSIONS</span><h2>{labels[kind]}: what was observed</h2><p>Each item is compared with the static baseline. “Not observed” means no matching evidence was found in these selected sessions.</p></div><div><button type="button" onClick={onRefresh} disabled={result.isPending}>Refresh details</button> <button type="button" onClick={onClose} aria-label="Close coverage details">Close</button></div></header>
    {data&&<><div className="coverage-detail__summary"><strong>{data.metric.observed??'Unavailable'} / {data.metric.total??'Unavailable'}</strong><span>{data.metric.percentage===null?'Coverage unavailable':`${data.metric.percentage}% observed`}</span><p>{data.status==='UNAVAILABLE'?data.reason:data.metric.reason||data.reason}</p></div>
      {data.status==='UNAVAILABLE'&&<div className="notice">Exact item-by-item comparison is not measured for this snapshot. The report will not label unknown items as unobserved (state UNKNOWN).</div>}</>}
    <div className="coverage-detail__controls" role="group" aria-label="Filter coverage items">
      {(['ALL','OBSERVED','NOT_OBSERVED'] as const).map(value=><button type="button" className={filter===value?'active':''} key={value} onClick={()=>setFilter(value)}>{value==='ALL'?'All items':value==='OBSERVED'?'Observed':'Not observed'}</button>)}
      <label>Search static items<input value={search} onChange={event=>setSearch(event.target.value)} placeholder="Class, method, route, domain…"/></label>
    </div>
    {result.error!==null&&result.error!==undefined&&<ErrorBox error={result.error}/>}
    {result.isPending&&!data&&<p>Loading static and runtime evidence…</p>}
    {data&&<>
      {!data.items.length&&!result.isPending&&<p>No items match this filter.</p>}
      <div className="coverage-detail__list">{data.items.map(item=><article className="coverage-item" key={item.id}>
        <header><strong>{item.name}</strong><span className={'coverage-state coverage-state--'+item.state.toLowerCase()}>{item.state.replaceAll('_',' ')}</span></header>
        {item.class_name&&<p><b>Class:</b> <code>{item.class_name}</code></p>}
        {item.package_name&&<p><b>Package:</b> <code>{item.package_name}</code></p>}
        {item.domain_name&&<p><b>Domain:</b> {item.domain_name}</p>}
        {item.signature&&<p><b>Method signature:</b> <code>{item.signature}</code></p>}
        {item.annotations?.length? <p><b>Static annotations:</b> <code>{item.annotations.join(', ')}</code></p>:null}
        {item.observed_spans!==undefined&&<p><b>Matching runtime spans:</b> {item.observed_spans??'Unavailable (raw span detail expired)'}</p>}
        {item.source&&item.target&&<><p><b>Static call:</b> <code>{item.source}</code> → <code>{item.target}</code>{item.observed_calls!==undefined&&` · ${item.observed_calls} matching calls`}</p>{(item.source_domain||item.target_domain)&&<p><b>Domains:</b> {item.source_domain||'Unknown'} → {item.target_domain||'Unknown'}</p>}</>}
        {item.observed!==undefined&&item.total!==undefined&&<p><b>Domain classes:</b> {item.observed} observed of {item.total} · {item.observation_state?.replaceAll('_',' ').toLowerCase()}</p>}
        {item.evidence?.length? <p><b>Runtime identity evidence:</b> {item.evidence.join(' ')}</p>:null}
        {item.evidence_refs?.length? <details><summary>Inspect matching spans ({item.evidence_refs.length}{item.evidence_refs.length===20?' shown; may be more':''})</summary>{item.evidence_refs.map((ref,index)=><a className="coverage-span-link" key={ref.session_id+ref.trace_id+ref.span_id} href={`/api/v1/runtime-sessions/${ref.session_id}/spans/${ref.trace_id}/${ref.span_id}`} target="_blank" rel="noreferrer">Open span {index+1} · trace {ref.trace_id.slice(0,12)} · span {ref.span_id.slice(0,12)}</a>)}</details>:null}
        {item.observed_classes?.length? <details><summary>Observed classes ({item.observed_classes.length})</summary><ul>{item.observed_classes.map(name=><li key={name}><code>{name}</code></li>)}</ul></details>:null}
        {item.unobserved_classes?.length? <details open={item.state==='NOT_OBSERVED'}><summary>Static classes not seen ({item.unobserved_classes.length})</summary><ul>{item.unobserved_classes.map(name=><li key={name}><code>{name}</code></li>)}</ul></details>:null}
        {item.state==='NOT_OBSERVED'&&<p className="fine-print">Not observed in the selected sessions (this does not mean unused). See the Next tests tab for specific steps.</p>}
      </article>)}</div>
      <div className="coverage-detail__pager"><span>Showing {data.total?offset+1:0}–{Math.min(offset+data.limit,data.total)} of {data.total}</span><div><button type="button" disabled={offset===0||result.isPending} onClick={()=>setOffset(Math.max(0,offset-data.limit))}>Previous</button><button type="button" disabled={offset+data.limit>=data.total||result.isPending} onClick={()=>setOffset(offset+data.limit)}>Next</button></div></div>
    </>}
  </section>;
}

function PlanDetails({plan}:{plan:InstrumentationPlan}){
  return <details className="runtime-card"><summary>Instrumentation plan: {plan.classes.length} classes / {plan.selected_method_names} method names</summary><p>{plan.version} · {plan.encoded_bytes} encoded bytes</p><code>{plan.sha256}</code><h3>Omissions</h3>{Object.entries(plan.omissions).map(([reason,count])=><p key={reason}>{reason.replaceAll('_',' ')}: {count}</p>)}{plan.classes.map(c=><p key={c.class_name}><code>{c.class_name}[{c.methods}]</code> · {c.reason}</p>)}{plan.limitations.map(l=><p key={l}>{l}</p>)}</details>;
}
