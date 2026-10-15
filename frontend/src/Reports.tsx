import { useEffect, useState } from 'react';
import { ArrowDownToLine, Eye, FileText, Printer } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { api } from './api';
import { Button, ErrorBox, PageTitle } from './components';
import type { Application, Domain, Issue, Summary, Items } from './types';

type Version = { id: string; name: string };
type Proposal = { id: string; strategy: string; objective: string };
type VersionDetail = Version & { analysis_id: string; fingerprint: string; counts: Record<string,number>; manifest: {runtime_session_ids:string[]} };
type CoverageRecord = {observed:number|null;total:number|null;percentage:number|null;status:string;reason?:string};
type Twin = {coverage:Record<string,unknown>;quality:Record<string,unknown>;unknowns:string[];projection:{state:string;attempts:number;error_code:string|null};counts:Record<string,number>;fingerprint:string;manifest:VersionDetail['manifest']};
type ProposalDetail = {document:{decision_brief?:{summary?:string;headline?:string;next_step?:string;unresolved_questions?:string[];strategy_fit?:{recommendation:string;rationale:string};top_actions?:string[];top_risks?:string[];overall_confidence?:string;effort_range?:string};domain_dependency_matrix?:{domain_ids:{id:string;name:string}[];rows:{source_domain:string;target_domain:string;edge_count:number;edge_groups?:Record<string,number>}[];top_boundary_classes:{class_name:string;boundary_edges:number;domain:string}[]};assessments?:{domain_id:string;domain_name?:string;readiness_score?:number;combined_score?:number;confidence_adjusted_score?:number;readiness_label?:string;confidence_label?:string;confidence_score?:number;blockers?:string[]}[];waves?:{number:number;domains:string[];reason:string;blockers?:string[]}[];validation?:{status:string}};reviews:{state:string}[];context:{state:string;note:string}};

export function Reports({ applications }: { applications: Application[] }) {
  const [applicationId, setApplicationId] = useState('');
  const [versionId, setVersionId] = useState('');
  const [proposalId, setProposalId] = useState('');
  const appId = applicationId || applications[0]?.id || '';
  const versions = useQuery({ queryKey: ['versions', appId], queryFn: () => api<Version[]>('/applications/' + appId + '/architecture-versions'), enabled: !!appId });
  const version = versionId || versions.data?.[0]?.id || '';
  const proposals = useQuery({ queryKey: ['plans', version], queryFn: () => api<Proposal[]>('/architecture-versions/' + version + '/modernization'), enabled: !!version });
  const proposal = proposalId || proposals.data?.[0]?.id || '';
  const versionDetail = useQuery({queryKey:['report-version',version],queryFn:()=>api<VersionDetail>('/architecture-versions/'+version),enabled:!!version});
  const twin = useQuery({queryKey:['twin',version],queryFn:()=>api<Twin>('/architecture-versions/'+version+'/twin'),enabled:!!version});
  const proposalDetail = useQuery({queryKey:['report-proposal',version,proposal],queryFn:()=>api<ProposalDetail>('/architecture-versions/'+version+'/modernization/'+proposal),enabled:!!version&&!!proposal});
  const analysisId=versionDetail.data?.analysis_id||'';
  const summary=useQuery({queryKey:['summary',analysisId],queryFn:()=>api<Summary>('/analyses/'+analysisId+'/summary'),enabled:!!analysisId});
  const domains=useQuery({queryKey:['domains',analysisId],queryFn:()=>api<Items<Domain>>('/analyses/'+analysisId+'/domains'),enabled:!!analysisId});
  const issues=useQuery({queryKey:['issues',analysisId],queryFn:()=>api<Items<Issue>>('/analyses/'+analysisId+'/issues?limit=500'),enabled:!!analysisId});
  const [preview,setPreview]=useState(false);
  useEffect(() => { setVersionId(''); setProposalId(''); }, [appId]);
  useEffect(() => { setProposalId(''); }, [version]);
  const reportHref = version && proposal ? `/api/v1/architecture-versions/${version}/modernization/${proposal}/report.pdf` : '';
  return <div className="reports-page">
    <PageTitle eyebrow="DELIVER" title="Reports" description="Download a frozen modernization report or export the source analysis evidence."/>
    {applications.length === 0 ? <div className="empty"><FileText size={28}/><h2>No applications yet</h2><p>Analyze an application to make its evidence available for export.</p></div> : <>
      {(versions.error || proposals.error || versionDetail.error || twin.error || proposalDetail.error || summary.error || domains.error || issues.error) && <ErrorBox error={versions.error || proposals.error || versionDetail.error || twin.error || proposalDetail.error || summary.error || domains.error || issues.error}/>} 
      <section className="panel report-picker">
        <div className="panel-heading"><div><h2>Consolidated report</h2><p>Combines static findings, selected runtime evidence, the captured digital twin, and its saved proposal.</p></div><FileText size={20}/></div>
        <div className="report-fields">
          <label>Application<select value={appId} onChange={e => setApplicationId(e.target.value)}>{applications.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
          <label>Architecture version<select value={version} onChange={e => setVersionId(e.target.value)} disabled={!versions.data?.length}><option value="">Select a captured version</option>{versions.data?.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}</select></label>
          <label>Saved proposal<select value={proposal} onChange={e => setProposalId(e.target.value)} disabled={!proposals.data?.length}><option value="">Select a saved proposal</option>{proposals.data?.map(p => <option key={p.id} value={p.id}>{p.strategy}: {p.objective}</option>)}</select></label>
        </div>
        {!versions.isPending && !versions.error && versions.data?.length === 0 && <p className="report-hint">Capture an architecture version in Evidence & Digital Twin to prepare a consolidated report.</p>}
        {version && !proposals.isPending && !proposals.error && proposals.data?.length === 0 && <p className="report-hint">Save a modernization proposal for this architecture version to enable the consolidated PDF.</p>}
        <div className="report-actions">
          <Button disabled={!version||!proposal} onClick={()=>setPreview(value=>!value)}><Eye size={16}/>{preview?'Hide HTML preview':'Preview report'}</Button>
          {reportHref ? <a className="button" href={reportHref}><ArrowDownToLine size={16}/>Download PDF report</a> : <Button disabled><ArrowDownToLine size={16}/>Download PDF report</Button>}
          {version && <a className="button secondary" href={`/api/v1/architecture-versions/${version}/export`}><ArrowDownToLine size={16}/>Export digital twin JSON</a>}
        </div>
      </section>
      {preview&&<ReportHtmlPreview summary={summary.data} domains={domains.data?.items||[]} issues={issues.data?.items||[]} twin={twin.data} proposal={proposalDetail.data} version={versionDetail.data} onPrint={()=>window.print()}/>}
    </>}
  </div>;
}

function ReportHtmlPreview({summary,domains,issues,twin,proposal,version,onPrint}:{summary?:Summary;domains:Domain[];issues:Issue[];twin?:Twin;proposal?:ProposalDetail;version?:VersionDetail;onPrint:()=>void}){
  const topIssues=[...issues].sort((a,b)=>({CRITICAL:0,HIGH:1,MEDIUM:2,LOW:3}[a.severity as 'CRITICAL'|'HIGH'|'MEDIUM'|'LOW']??4)-({CRITICAL:0,HIGH:1,MEDIUM:2,LOW:3}[b.severity as 'CRITICAL'|'HIGH'|'MEDIUM'|'LOW']??4)).slice(0,10);
  const coverage=Object.entries(twin?.coverage||{}).filter(([,value])=>!!value&&typeof value==='object'&&!Array.isArray(value)&&('observed' in value||'status' in value)).map(([key,value])=>[key,value as CoverageRecord] as const);
  const assessments=proposal?.document.assessments||[];
  const brief=proposal?.document.decision_brief;
  return <article className="report-preview" aria-label="HTML report preview">
    <header className="report-preview-header"><div><span className="eyebrow">ARCHINTEL · CONFIDENTIAL WORKING REPORT</span><h1>{summary?.artifact.filename||'Modernization report'}</h1><p>Analysis {version?.analysis_id.slice(0,8)||'Not detected'} · Architecture version {version?.id.slice(0,8)||'Not detected'} · Proposal {proposal&&version?'Selected':''}</p></div><button className="button secondary report-print-button" onClick={onPrint}><Printer size={16}/>Print / Save PDF</button></header>
    <section><h2>Executive summary</h2><p>{brief?.strategy_fit?.rationale||brief?.summary||brief?.headline||'A saved modernization proposal is available for review.'}</p><p><strong>Strategy fit:</strong> {brief?.strategy_fit?.recommendation?.replaceAll('_',' ')||'Review required'} · <strong>Confidence:</strong> {brief?.overall_confidence||'Not reported'} · <strong>Effort:</strong> {brief?.effort_range||'Not estimated'}</p>{brief?.top_actions?.length&&<><h3>Priority actions</h3><ol>{brief.top_actions.map(action=><li key={action}>{action}</li>)}</ol></>}<div className="report-kpis">{[['Classes',summary?.class_count],['Packages',summary?.package_count],['Dependencies',summary?.dependency_count],['Candidate domains',summary?.domain_count],['Findings',summary?.issue_count],['Runtime sessions',version?.manifest.runtime_session_ids.length]].map(([label,value])=><div key={String(label)}><span>{label}</span><strong>{value==null?'Not detected':Number(value).toLocaleString()}</strong></div>)}</div>{brief?.next_step&&<div className="report-next"><strong>Recommended next step</strong><p>{brief.next_step}</p></div>}</section>
    <section><h2>Evidence basis</h2><p>Artifact: <code>{summary?.artifact.filename||'Not detected'}</code> · SHA-256: <code>{summary?.artifact.sha256||'Not detected'}</code></p><p>Architecture fingerprint: <code>{version?.fingerprint||'Not detected'}</code></p><p>Projection state: <strong>{twin?.projection.state||'Not detected'}</strong> · Evidence records: {version?.counts.evidence?.toLocaleString()??'Not detected'} · Architecture facts: {version?.counts.facts?.toLocaleString()??'Not detected'}</p><p>Static findings describe submitted bytecode. Runtime evidence reflects only the selected sessions and workloads; unobserved means not seen, not unused.</p></section>
    <section><h2>Candidate domains</h2><div className="sequence-table"><table><thead><tr><th>Domain</th><th>Classes</th><th>Evidence confidence</th><th>Readiness</th></tr></thead><tbody>{domains.map(domain=>{const assessment=assessments.find(item=>item.domain_id===domain.id);return <tr key={domain.id}><td>{domain.name}</td><td>{domain.class_count.toLocaleString()}</td><td>{Math.round(domain.confidence*100)}%<small>Boundary evidence confidence; heuristic, not a probability or tool-accuracy score.</small></td><td>{assessment?.readiness_score??assessment?.combined_score??'Not detected'}<small>Modernization readiness: structural prioritization heuristic; not tool accuracy or a vulnerability score.</small></td></tr>;})}{!domains.length&&<tr><td colSpan={4}>Not detected</td></tr>}</tbody></table></div></section>
    <section><h2>Highest-priority findings</h2><div className="sequence-table"><table><thead><tr><th>Severity</th><th>Finding</th><th>Entity</th><th>Recommended investigation</th></tr></thead><tbody>{topIssues.map(issue=><tr key={issue.id}><td>{issue.severity}</td><td>{issue.title}</td><td><code>{issue.entity_id}</code></td><td>{issue.recommendation}</td></tr>)}{!topIssues.length&&<tr><td colSpan={4}>No findings returned for this analysis.</td></tr>}</tbody></table></div></section>
    <section><h2>Runtime observation</h2><p>Dynamic coverage confidence reflects code observed in the selected workload, not tool accuracy or vulnerability risk. Coverage is limited to sessions attached to this architecture version; unobserved does not prove unused.</p><div className="sequence-table"><table><thead><tr><th>Measure</th><th>Observed</th><th>Total</th><th>Coverage</th><th>State</th></tr></thead><tbody>{coverage.map(([key,metric])=><tr key={key}><td>{key.replaceAll('_',' ')}</td><td>{metric.observed==null?'Not observed':metric.observed.toLocaleString()}</td><td>{metric.total==null?'Not detected':metric.total.toLocaleString()}</td><td>{metric.percentage==null?'Not observed':`${metric.percentage}%`}</td><td>{metric.status}</td></tr>)}{!coverage.length&&<tr><td colSpan={5}>Not observed</td></tr>}</tbody></table></div></section>
    <section><h2>Modernization proposal</h2><p>{proposal?.context.note||'Review the selected proposal and validate all consequential decisions.'}</p><div className="sequence-table"><table><thead><tr><th>Candidate domain</th><th>Readiness</th><th>Evidence confidence</th><th>Adjusted readiness</th><th>Status</th><th>Blockers</th></tr></thead><tbody>{assessments.map((item,index)=><tr key={item.domain_id}><td>{item.domain_name||domains.find(domain=>domain.id===item.domain_id)?.name||'Candidate '+(index+1)}</td><td>{item.readiness_score??item.combined_score??'Not detected'}</td><td>{item.confidence_score==null?item.confidence_label||'Not detected':`${Math.round(item.confidence_score)}%`}</td><td>{item.confidence_adjusted_score??'Not detected'}</td><td>{item.readiness_label?.replaceAll('_',' ')||'Review required'}</td><td>{item.blockers?.length?item.blockers.join('; '):'None returned'}</td></tr>)}{!assessments.length&&<tr><td colSpan={6}>No proposal assessments are available.</td></tr>}</tbody></table></div>{proposal?.document.domain_dependency_matrix&&<><h3>Cross-domain dependency matrix</h3><div className="sequence-table"><table><thead><tr><th>Source</th><th>Target</th><th>Class-level edges</th><th>Dependency types</th></tr></thead><tbody>{proposal.document.domain_dependency_matrix.rows.map((row,index)=><tr key={index}><td>{row.source_domain}</td><td>{row.target_domain}</td><td>{row.edge_count}</td><td>{Object.entries(row.edge_groups||{}).map(([key,value])=>`${key}: ${value}`).join(', ')}</td></tr>)}</tbody></table></div><h3>Top boundary-crossing classes</h3><ul>{proposal.document.domain_dependency_matrix.top_boundary_classes.map(row=><li key={row.class_name}>{row.class_name}: {row.boundary_edges} edge(s), {row.domain}</li>)}</ul></>}{proposal?.document.waves?.map(wave=><div className="report-wave" key={wave.number}><strong>Wave {wave.number}</strong><span>{wave.domains.map(id=>domains.find(domain=>domain.id===id)?.name||id).join(', ')||'No candidate domains returned'}</span><p>{wave.reason}</p></div>)}</section>
    {!!brief?.unresolved_questions?.length&&<section><h2>Open questions</h2><ol>{brief.unresolved_questions.map((question,index)=><li key={index}>{question}</li>)}</ol></section>}
    <footer>This report is a review aid. Candidate boundaries, readiness and recommendations do not prove business ownership, behavioral equivalence or safe extraction. Human review is required before consequential changes.</footer>
  </article>;
}
