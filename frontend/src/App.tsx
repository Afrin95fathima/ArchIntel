import { lazy, Suspense, useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, ArrowDownToLine, Boxes, CircleHelp, Compass, History, FileText, FolderKanban, GitBranch, LayoutDashboard, Layers3, Network, PanelLeftClose, Route, Search, ShieldAlert, Sparkles, Wrench } from 'lucide-react';
import { ArchIntelBrand } from './Brand';
import { api } from './api';
import { Empty, ErrorBox, Loading } from './components';
import { Workspace, Progress } from './Workspace';
const Overview=lazy(()=>import('./Overview').then(module=>({default:module.Overview})));
const ArchitectureBlueprint=lazy(()=>import('./ArchitectureBlueprint').then(module=>({default:module.ArchitectureBlueprint})));
const GraphExplorer=lazy(()=>import('./GraphExplorer').then(module=>({default:module.GraphExplorer})));
const Domains=lazy(()=>import('./Insights').then(module=>({default:module.Domains})));
const Issues=lazy(()=>import('./Insights').then(module=>({default:module.Issues})));
const Dependencies=lazy(()=>import('./Dependencies').then(module=>({default:module.Dependencies})));
const Modernization=lazy(()=>import('./Insights').then(module=>({default:module.Modernization})));
const Assistant=lazy(()=>import('./Assistant').then(module=>({default:module.Assistant})));
const RuntimeAnalysis=lazy(()=>import('./runtime/RuntimeAnalysis').then(module=>({default:module.RuntimeAnalysis})));
const TaskWorkspace=lazy(()=>import('./transformation/TaskWorkspace').then(module=>({default:module.TaskWorkspace})));
const EvidenceWorkspace=lazy(()=>import('./evidence/EvidenceWorkspace').then(module=>({default:module.EvidenceWorkspace})));
const LocalDiagnostics=lazy(()=>import('./LocalDiagnostics').then(module=>({default:module.LocalDiagnostics})));
const Reports=lazy(()=>import('./Reports').then(module=>({default:module.Reports})));
const ModernizationHub=lazy(()=>import('./modernization/ModernizationHub').then(module=>({default:module.ModernizationHub})));
const TechnologyLifecycle=lazy(()=>import('./insight/TechnologyLifecycle').then(module=>({default:module.TechnologyLifecycle})));
const UIKit=lazy(()=>import('./UIKit').then(module=>({default:module.UIKit})));
import type { Analysis, Application, Project, Summary, Domain, Assessment, Issue, Metric, Cycle, Items, View } from './types';

const navigation: {label:string;items:{id:View;label:string;icon:typeof Activity}[]}[] = [
  {label:'Analyze',items:[
    {id:'overview',label:'Overview',icon:LayoutDashboard},{id:'architecture',label:'Application architecture',icon:Layers3},{id:'explorer',label:'Architecture explorer',icon:Network},
    {id:'domains',label:'Candidate domains',icon:Boxes},{id:'issues',label:'Technical debt',icon:ShieldAlert},{id:'lifecycle',label:'Technology lifecycle',icon:History},
    {id:'cycles',label:'Dependencies',icon:GitBranch},
    {id:'assistant',label:'Architecture assistant',icon:Sparkles}
  ]},
  {label:'Runtime',items:[{id:'runtime',label:'Dynamic analysis',icon:Activity}]},
  {label:'Plan',items:[{id:'planning',label:'Modernization',icon:Route}]},
  {label:'Evidence',items:[{id:'evidence',label:'Evidence & digital twin',icon:Network}]},
  {label:'Deliver',items:[{id:'reports',label:'Reports',icon:FileText},{id:'tasks',label:'Source tasks',icon:GitBranch}]}
];

export function App() {
  const client=useQueryClient();
  const [view,setViewState]=useState<View>(()=>window.location.pathname==='/ui-kit'?'uikit':'workspace');
  const [selected,setSelected]=useState(()=>localStorage.getItem('archintel-analysis')||'');
  const [sidebar,setSidebar]=useState(true);
  const [help,setHelp]=useState(false);
  const [commandOpen,setCommandOpen]=useState(false);
  const [focusNode,setFocusNode]=useState('');
  function setView(next:View){
    if(next==='uikit'&&window.location.pathname!=='/ui-kit')window.history.pushState({archintelView:next},'','/ui-kit');
    else if(next!=='uikit'&&window.location.pathname==='/ui-kit')window.history.pushState({archintelView:next},'','/');
    setViewState(next);
  }
  const projects=useQuery({queryKey:['projects'],queryFn:()=>api<Project[]>('/projects')});
  const applications=useQuery({queryKey:['applications'],queryFn:()=>api<Application[]>('/applications')});
  const analyses=useQuery({queryKey:['analyses'],queryFn:()=>api<Analysis[]>('/analyses'),refetchInterval:3000});
  const ready=useQuery({queryKey:['ready'],queryFn:()=>api<{status:string;database:string}>('/ready'),retry:false,refetchInterval:15000});
  const run=analyses.data?.find(a=>a.id===selected);
  const enabled=run?.status==='COMPLETED';
  const summary=useQuery({queryKey:['summary',selected],queryFn:()=>api<Summary>('/analyses/'+selected+'/summary'),enabled});
  const domains=useQuery({queryKey:['domains',selected],queryFn:()=>api<Items<Domain>>('/analyses/'+selected+'/domains'),enabled});
  const assessments=useQuery({queryKey:['modernization',selected],queryFn:()=>api<Items<Assessment>>('/analyses/'+selected+'/modernization'),enabled});
  const issues=useQuery({queryKey:['issues',selected],queryFn:()=>api<Items<Issue>>('/analyses/'+selected+'/issues?limit=500'),enabled});
  const metrics=useQuery({queryKey:['metrics',selected],queryFn:()=>api<Items<Metric>>('/analyses/'+selected+'/metrics'),enabled});
  const cycles=useQuery({queryKey:['cycles',selected],queryFn:()=>api<Items<Cycle>>('/analyses/'+selected+'/cycles'),enabled});
  useEffect(()=>{if(!selected&&analyses.data?.length)setSelected(analyses.data[0].id);},[analyses.data,selected]);
  useEffect(()=>{if(selected)localStorage.setItem('archintel-analysis',selected);},[selected]);
  useEffect(()=>{
    const onKeyDown=(event:KeyboardEvent)=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){event.preventDefault();setCommandOpen(value=>!value);}if(event.key==='Escape')setCommandOpen(false);};
    window.addEventListener('keydown',onKeyDown);return()=>window.removeEventListener('keydown',onKeyDown);
  },[]);
  useEffect(()=>{const onOpen=(event:Event)=>{const id=(event as CustomEvent<{id:string}>).detail?.id;if(id){setFocusNode(id);setViewState('explorer');}};window.addEventListener('archintel-open-node',onOpen);return()=>window.removeEventListener('archintel-open-node',onOpen);},[]);
  useEffect(()=>{const onPopState=()=>setViewState(window.location.pathname==='/ui-kit'?'uikit':'workspace');window.addEventListener('popstate',onPopState);return()=>window.removeEventListener('popstate',onPopState);},[]);
  function refresh(){for(const key of ['projects','applications','analyses'])client.invalidateQueries({queryKey:[key]});}
  function select(id:string){setSelected(id);setView('overview');}
  function startService(intent:{applicationId:string;versionId:string;assessmentId:string;decisionId:string;candidateId:string;candidateName:string;rolloutMode:string}){
    sessionStorage.setItem('archintel-service-task-intent',JSON.stringify(intent));
    setView('tasks');
  }
  const app=applications.data?.find(a=>a.id===run?.application_id);
  const dataError=summary.error||domains.error||assessments.error||issues.error||metrics.error||cycles.error;
  const loaded=summary.data&&domains.data&&assessments.data&&issues.data&&metrics.data&&cycles.data;
  return <div className={'app-shell '+(!sidebar?'collapsed':'')}>
    <aside className="sidebar"><button className="brand" onClick={()=>setView('workspace')} aria-label="ArchIntel applications"><ArchIntelBrand compact={!sidebar}/></button>
      <div className="workspace-label">PORTFOLIO</div><button title="Applications" className={'nav-item '+(view==='workspace'?'active':'')} onClick={()=>setView('workspace')}><FolderKanban size={18}/><span>Applications</span><span className="nav-count">{applications.data?.length||0}</span></button>
      <nav className="nav-groups">{navigation.map(group=><section className="nav-group" key={group.label}><div className="workspace-label">{group.label}</div>{group.items.map(n=><button title={n.label} aria-label={n.label} key={n.id} className={'nav-item '+(view===n.id?'active':'')} onClick={()=>setView(n.id)}><n.icon size={18}/><span>{n.label}</span>{n.id==='issues'&&summary.data&&<span className="nav-count">{summary.data.issue_count}</span>}</button>)}</section>)}</nav>
      <div className="sidebar-bottom"><button className={'nav-item '+(view==='diagnostics'?'active':'')} title="Local setup" onClick={()=>setView('diagnostics')}><Wrench size={18}/><span>Local setup</span></button><button className={'nav-item '+(view==='uikit'?'active':'')} title="UI component catalog" onClick={()=>setView('uikit')}><Boxes size={18}/><span>Design system</span></button><button className="nav-item" title="Help and documentation" onClick={()=>setHelp(!help)}><CircleHelp size={18}/><span>Help & documentation</span></button><div className="profile"><span className="profile-mark"><ArchIntelBrand compact/></span><span>ArchIntel workspace<small>Local deployment</small></span></div></div>
    </aside>
    <div className="main-shell"><header className="topbar"><div className="breadcrumbs"><button className="icon-button" aria-label="Toggle sidebar" onClick={()=>setSidebar(!sidebar)}><PanelLeftClose size={18}/></button><span>Workspace</span>{app&&<><span>/</span><span>{app.name}</span></>}<span>/</span><strong>{view==='workspace'?'Applications':view==='runtime'?'Dynamic analysis':view==='architecture'?'Application architecture':view==='evidence'?'Evidence & digital twin':view==='planning'?'Modernization':view==='tasks'?'Source tasks':view==='reports'?'Reports':view==='diagnostics'?'Local setup':view==='uikit'?'Design system':view==='assistant'?'Architecture assistant':view==='explorer'?'Architecture explorer':view==='domains'?'Candidate domains':view==='issues'?'Technical debt':view==='lifecycle'?'Technology lifecycle':view==='cycles'?'Dependencies · Cycles':view==='metrics'?'Dependencies · Metrics':view==='modernization'?'Modernization':'Overview'}</strong></div><div className="top-actions"><button className="command-trigger" onClick={()=>setCommandOpen(true)}><Search size={15}/><span>Search</span><kbd>Ctrl K</kbd></button><span className={'service-status '+(ready.isSuccess?'online':'offline')}><i/>{ready.isSuccess?'Services ready':'Services unavailable'}</span>{view!=='workspace'&&view!=='runtime'&&view!=='evidence'&&view!=='planning'&&view!=='tasks'&&view!=='diagnostics'&&view!=='reports'&&view!=='uikit'&&analyses.data?.length?<select aria-label="Select analysis" value={selected} onChange={e=>select(e.target.value)}>{analyses.data.map(a=><option key={a.id} value={a.id}>{applications.data?.find(x=>x.id===a.application_id)?.name||'Application'} · {a.status.toLowerCase()} · {a.id.slice(0,5)}</option>)}</select>:null}{enabled&&view!=='workspace'&&view!=='runtime'&&view!=='evidence'&&view!=='planning'&&view!=='tasks'&&view!=='diagnostics'&&view!=='reports'&&view!=='uikit'&&<a className="export-button" href={'/api/v1/analyses/'+selected+'/export'}><ArrowDownToLine size={16}/>Export analysis</a>}</div></header>
      <main className="main-content">
        {help&&<section className="help-panel"><h2>Demo quick start</h2><p>Open Applications → Explore demo application. Review Overview, expand the Architecture explorer, inspect Technical debt, then open Modernization plan and ask the Architecture assistant where to begin.</p><p>To analyze your own application, choose Analyze application and upload a compiled JAR/WAR or a project ZIP containing compiled module outputs. Source-only ZIPs are not supported. Larger artifacts take longer than the bundled sample.</p><div className="banner-actions"><a href="/api/v1/manual/user" className="text-link">User manual ↓</a><a href="/api/v1/manual/developer" className="text-link">Developer guide ↓</a><button className="text-link" onClick={()=>setHelp(false)}>Close help</button></div></section>}
        {run&&view!=='workspace'&&<Journey run={run} onNavigate={setView}/>}
        <Suspense fallback={<Loading/>}>{view==='uikit'?<UIKit/>:view==='diagnostics'?<LocalDiagnostics/>:
        view==='workspace'?<>{projects.error||applications.error||analyses.error?<ErrorBox error={projects.error||applications.error||analyses.error}/>:null}<Workspace projects={projects.data||[]} applications={applications.data||[]} analyses={analyses.data||[]} onSelect={select} onStarted={r=>{select(r.id);refresh();}} refresh={refresh}/></>:
        view==='runtime'?<RuntimeAnalysis applications={applications.data||[]} analyses={analyses.data||[]}/>:
        view==='tasks'?<TaskWorkspace applications={applications.data||[]}/>: 
        view==='planning'||view==='modernization'?<ModernizationHub applications={applications.data||[]} onStartService={startService} assessments={loaded?assessments.data!.items:[]} confidenceByDomain={loaded?Object.fromEntries(domains.data!.items.map(domain=>[domain.id,domain.confidence])):{}} initialTab={view==='modernization'?'sequence':'proposal'}/>: 
        view==='evidence'?<EvidenceWorkspace applications={applications.data||[]} analyses={analyses.data||[]}/>: 
        view==='reports'?<Reports applications={applications.data||[]}/>: 
        !run?<Empty title="Choose an application to explore.">Open Applications and select an analysis, or start with the Northstar Commerce demo.</Empty>:
        run.status!=='COMPLETED'?<Progress run={run} onUpload={()=>setView('workspace')}/>:
        dataError?<ErrorBox error={dataError}/>:!loaded?<Loading/>:
        <div key={selected}>
          {view==='overview'&&<Overview summary={summary.data!} domains={domains.data!.items} assessments={assessments.data!.items} issues={issues.data!.items} analysisId={selected} navigate={setView}/>}
          {view==='architecture'&&<ArchitectureBlueprint analysisId={selected} applicationId={run.application_id} analyses={(analyses.data||[]).filter(row=>row.application_id===run.application_id)} applicationName={app?.name||'Analyzed application'} summary={summary.data!} domains={domains.data!.items}/>}
          {view==='explorer'&&<GraphExplorer analysisId={selected} domains={domains.data!.items} focusId={focusNode}/>}
          {view==='domains'&&<Domains domains={domains.data!.items} assessments={assessments.data!.items} issues={issues.data!.items}/>}
          {view==='issues'&&<><Issues issues={issues.data!.items} domains={domains.data!.items}/>{issues.data!.total>500&&<div className="notice">Showing the first 500 findings. Use the paginated API or export for the complete report.</div>}</>}
          {(view==='cycles'||view==='metrics')&&<Dependencies analysisId={selected} cycles={cycles.data!.items} metrics={metrics.data!.items} initialTab={view==='metrics'?'metrics':'cycles'}/>}
          {view==='lifecycle'&&<TechnologyLifecycle analysisId={selected}/>}
          {view==='assistant'&&<Assistant analysisId={selected} domains={domains.data!.items}/>}
        </div>}</Suspense>
      </main><footer className="app-footer"><span><Compass size={13}/> ArchIntel · Architecture & modernization intelligence</span><span>Evidence-backed analysis · Local deployment</span></footer>
    </div>
    {commandOpen&&<div className="command-backdrop" onMouseDown={event=>{if(event.target===event.currentTarget)setCommandOpen(false);}}><section className="command-palette" role="dialog" aria-modal="true" aria-label="Go to a workspace screen"><div className="command-search"><Search size={17}/><input autoFocus placeholder="Go to a workspace screen…" aria-label="Search workspace" onChange={event=>{const query=event.target.value.toLowerCase();document.querySelectorAll<HTMLButtonElement>('.command-list button').forEach(button=>{button.hidden=!button.textContent?.toLowerCase().includes(query);});}}/><kbd>ESC</kbd></div><div className="command-list">{[{id:'workspace' as View,label:'Applications',icon:FolderKanban},...navigation.flatMap(group=>group.items),{id:'reports' as View,label:'Reports',icon:FileText},{id:'diagnostics' as View,label:'Local setup',icon:Wrench},{id:'uikit' as View,label:'Design system',icon:Boxes}].map(item=><button key={item.id} onClick={()=>{setView(item.id);setCommandOpen(false);}}><item.icon size={16}/>{item.label}</button>)}</div><footer>Use Ctrl K to open · Esc to close</footer></section></div>}
  </div>;
}

function Journey({run,onNavigate}:{run:Analysis;onNavigate:(view:View)=>void}){
  const applicationId=run.application_id;
  const versions=useQuery({queryKey:['versions',applicationId],queryFn:()=>api<{id:string;name:string;analysis_id:string;manifest:{domain_review?:unknown;runtime_session_ids:string[]}}[]>('/applications/'+applicationId+'/architecture-versions'),enabled:!!applicationId});
  const sessions=useQuery({queryKey:['runtime-sessions',applicationId],queryFn:()=>api<{id:string;analysis_id:string;status:string;trace_count:number;span_count:number;agent_status:string}[]>('/applications/'+applicationId+'/runtime-sessions'),enabled:!!applicationId,refetchInterval:5000});
  const version=versions.data?.find(item=>item.analysis_id===run.id);
  const plans=useQuery({queryKey:['plans',version?.id||''],queryFn:()=>api<{id:string}[]>('/architecture-versions/'+version!.id+'/modernization'),enabled:!!version});
  const observedSessions=(sessions.data||[]).filter(session=>session.analysis_id===run.id);
  const completedSessions=observedSessions.filter(session=>session.status==='COMPLETED');
  const spans=completedSessions.reduce((total,session)=>total+session.span_count,0);
  const runtimeState=spans>0?`${spans.toLocaleString()} spans received`:completedSessions.length?'Session complete; no spans received':observedSessions.length?'Session created; waiting for telemetry':'No runtime session';
  const reviewState=version?.manifest.domain_review?'Domain review recorded':version?'Review not recorded':'Capture a version first';
  const proposalReady=!!plans.data?.length;
  const reportState=proposalReady?'PDF report available':'Save a proposal first';
  const complete=run.status==='COMPLETED';
  const failed=run.status==='FAILED';
  const steps:[string,View,string,string][]=[['Upload','workspace','Application and artifact are present','Done'],['Static analysis','overview',failed?run.error_message||'Analysis failed':complete?'Analysis completed':`Analysis ${run.progress}% complete`,failed?'Failed':complete?'Done':'In progress'],['Runtime evidence','runtime',runtimeState,spans?'Observed':completedSessions.length?'No spans':'Next'],['Review architecture','evidence',reviewState,version?.manifest.domain_review?'Done':version?'Review':'Next'],['Modernization proposal','planning',proposalReady?'Saved proposal available':'Generate and review a proposal',proposalReady?'Done':version?'Next':'Blocked'],['Report','reports',reportState,proposalReady?'Ready':'Blocked']];
  const next=failed?['Review analysis status','overview']:!complete?['View analysis progress','overview']:!spans?['Connect and exercise the application','runtime']:!version?['Capture architecture version','evidence']:!version.manifest.domain_review?['Review candidate domains','evidence']:!proposalReady?['Prepare modernization proposal','planning']:['Open the report','reports'];
  return <section className="journey" aria-label="Modernization workflow"><div className="journey-heading"><div><span className="eyebrow">WORKFLOW</span><strong>{complete?'Analysis ready for review':failed?'Analysis needs attention':'Analysis in progress'}</strong></div><span className="journey-next-label">Next recommended action</span></div><div className="journey-steps">{steps.map(([label,target,description,state],index)=><button key={label} className={'journey-step '+(state==='Done'?'complete':state==='Blocked'||state==='Failed'?'blocked':'')} onClick={()=>onNavigate(target)} aria-label={`${label}: ${state}. ${description}`} title={description}><span className="journey-number">{state==='Done'?'✓':index+1}</span><span>{label}<small>{state}</small></span></button>)}</div><button className="journey-next" onClick={()=>onNavigate(next[1] as View)}>{next[0]}<ArrowDownToLine size={15}/></button></section>;
}
