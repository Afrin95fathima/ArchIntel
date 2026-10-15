import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Activity, CheckCircle2, CircleAlert, Clock3, Info } from 'lucide-react';
import { api, post } from './api';
import { ErrorBox, Loading } from './components';
import './diagnostics.css';

type Check = {id:string;label:string;state:string;required:boolean;detail:string;action?:string};
type Report = {mode:string;core_ready:boolean;summary:string;checks:Check[];workflows:Record<string,string>};
type SupportPreview = {fingerprint:string;manifest:{included:string[];excluded:string[];transfer:string;upload_performed:boolean};report:unknown};

const icon = (state:string) => state==='READY'||state==='AVAILABLE'||state==='CONFIGURED'
  ? <CheckCircle2 size={17}/> : state==='ACTION_REQUIRED'
  ? <CircleAlert size={17}/> : state==='DEFERRED'
  ? <Clock3 size={17}/> : <Info size={17}/>;

export function LocalDiagnostics() {
  const [support,setSupport]=useState<SupportPreview|null>(null);
  const [supportError,setSupportError]=useState('');
  const [supportBusy,setSupportBusy]=useState(false);
  const query=useQuery({queryKey:['local-diagnostics'],queryFn:()=>api<Report>('/system/diagnostics'),retry:false,refetchInterval:30000});
  if(query.error)return <div className="local-diagnostics"><ErrorBox error={query.error}/></div>;
  if(!query.data)return <Loading/>;
  const data=query.data;
  return <div className="local-diagnostics runtime-page">
    <div className="diagnostics-heading"><div><span className="diagnostics-kicker">LOCAL POC · SETUP</span><h1>Local setup diagnostics</h1><p>Check the services ArchIntel needs for local analysis. Optional tools and deferred container workflows do not block static analysis.</p></div><div className={'diagnostics-summary '+(data.core_ready?'ready':'attention')}><Activity size={20}/><strong>{data.core_ready?'Core ready':'Action needed'}</strong><span>{data.summary}</span></div></div>
    <section className="runtime-card"><h2>Environment checks</h2><div className="diagnostics-list">{data.checks.map(check=><article className="diagnostic-row" key={check.id}>
      <span className={'diagnostic-icon '+check.state.toLowerCase()}>{icon(check.state)}</span><div className="diagnostic-copy"><div className="diagnostic-title"><strong>{check.label}</strong><span className={'diagnostic-state '+check.state.toLowerCase()}>{check.state.replaceAll('_',' ')}</span>{check.required&&<small>Required for local analysis</small>}</div><p>{check.detail}</p>{check.action&&<p className="diagnostic-action">Next step: {check.action}</p>}</div>
    </article>)}</div></section>
    <section className="runtime-card"><h2>What works in local mode</h2><div className="diagnostic-workflows">{Object.entries(data.workflows).map(([name,state])=><div key={name}><span className={'diagnostic-state '+state.toLowerCase()}>{state.replaceAll('_',' ')}</span><strong>{name.replaceAll('_',' ')}</strong></div>)}</div><p className="diagnostic-footnote">Docker is not required for static analysis or the local runtime receiver. Runtime capture also needs a Java agent in the application being observed. Docker will be added later to validate isolated candidate builds, refactor execution, and security scanning.</p></section>
    <section className="runtime-card"><h2>Local support bundle</h2><p>Preview a small health-status report before downloading it. The bundle excludes source code, secrets, logs, database contents, runtime payloads, and architecture/customer data. ArchIntel does not upload the bundle.</p>{supportError&&<p role="alert">{supportError}</p>}<button disabled={supportBusy} onClick={()=>{setSupportBusy(true);setSupportError('');void api<SupportPreview>('/system/support-bundle/preview').then(setSupport).catch(e=>setSupportError(String(e))).finally(()=>setSupportBusy(false));}}>Preview included data</button>{support&&<><h3>Review before export</h3><p>Included: {support.manifest.included.join(', ')}. Transfer: local download only.</p><p>Excluded: {support.manifest.excluded.join(', ')}.</p><p><small>Preview fingerprint: {support.fingerprint}</small></p><button disabled={supportBusy} onClick={()=>{setSupportBusy(true);setSupportError('');void post<SupportPreview>('/system/support-bundle/export',{fingerprint:support.fingerprint}).then(result=>{const blob=new Blob([JSON.stringify({manifest:result.manifest,report:result.report},null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='archintel-support-bundle.json';link.click();window.setTimeout(()=>URL.revokeObjectURL(url),0);setSupport(null);}).catch(e=>setSupportError(String(e))).finally(()=>setSupportBusy(false));}}>Confirm and download</button><button disabled={supportBusy} onClick={()=>setSupport(null)}>Cancel</button></>}</section>
  </div>;
}
