import { useEffect, useState } from 'react';
import { ArrowDownToLine, Eye, FileText } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { api } from './api';
import { Button, ErrorBox, PageTitle } from './components';
import type { Application } from './types';

type Version = { id: string; name: string };
type Proposal = { id: string; strategy: string; objective: string };

/** In a srcDoc frame a bare "#section" link resolves against the app URL, which the server refuses to frame; keep contents links inside the document. */
export const keepAnchorsInFrame = (html: string) => html.replace(/href="#/g, 'href="about:srcdoc#');

/** The report is generated on the server from the same analysis, runtime evidence and proposal the app shows; this page previews and downloads it. */
export function Reports({ applications }: { applications: Application[] }) {
  const [applicationId, setApplicationId] = useState('');
  const [versionId, setVersionId] = useState('');
  const [proposalId, setProposalId] = useState('');
  const [preview, setPreview] = useState(false);
  const appId = applicationId || applications[0]?.id || '';
  const versions = useQuery({ queryKey: ['versions', appId], queryFn: () => api<Version[]>('/applications/' + appId + '/architecture-versions'), enabled: !!appId });
  const version = versionId || versions.data?.[0]?.id || '';
  const proposals = useQuery({ queryKey: ['plans', version], queryFn: () => api<Proposal[]>('/architecture-versions/' + version + '/modernization'), enabled: !!version });
  const proposal = proposalId || proposals.data?.[0]?.id || '';
  const base = version && proposal ? `/api/v1/architecture-versions/${version}/modernization/${proposal}` : '';
  const html = useQuery({ queryKey: ['report-html', version, proposal], enabled: preview && !!base, retry: false,
    queryFn: async () => { const response = await fetch(base + '/report.html', { headers: { 'X-ArchIntel-Request': '1' } }); if (!response.ok) throw new Error('The report could not be generated (HTTP ' + response.status + ').'); return response.text(); } });
  useEffect(() => { setVersionId(''); setProposalId(''); setPreview(false); }, [appId]);
  useEffect(() => { setProposalId(''); setPreview(false); }, [version]);
  return <div className="reports-page">
    <PageTitle eyebrow="DELIVER" title="Reports" description="Preview and download the modernization report for a saved proposal, or export the digital twin evidence."/>
    {applications.length === 0 ? <div className="empty"><FileText size={28}/><h2>No applications yet</h2><p>Analyze an application to make its evidence available for export.</p></div> : <>
      {(versions.error || proposals.error) && <ErrorBox error={versions.error || proposals.error}/>}
      <section className="panel report-picker">
        <div className="panel-heading"><div><h2>Modernization report</h2><p>Report = 10 sections, each with an In plain terms summary and the Technical detail beneath it. Every figure comes from the analysis, runtime sessions and saved proposal selected here.</p></div><FileText size={20}/></div>
        <div className="report-fields">
          <label>Application<select value={appId} onChange={e => setApplicationId(e.target.value)}>{applications.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
          <label>Architecture version<select value={version} onChange={e => setVersionId(e.target.value)} disabled={!versions.data?.length}><option value="">Select a captured version</option>{versions.data?.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}</select></label>
          <label>Saved proposal<select value={proposal} onChange={e => setProposalId(e.target.value)} disabled={!proposals.data?.length}><option value="">Select a saved proposal</option>{proposals.data?.map(p => <option key={p.id} value={p.id}>{p.strategy}: {p.objective}</option>)}</select></label>
        </div>
        {!versions.isPending && !versions.error && versions.data?.length === 0 && <p className="report-hint">Capture an architecture version in Evidence & Digital Twin to prepare a report.</p>}
        {version && !proposals.isPending && !proposals.error && proposals.data?.length === 0 && <p className="report-hint">Save a modernization proposal for this architecture version to enable the report.</p>}
        <div className="report-actions">
          <Button disabled={!base} onClick={() => setPreview(value => !value)}><Eye size={16}/>{preview ? 'Hide preview' : 'Preview report'}</Button>
          {base ? <a className="button" href={base + '/report.pdf'}><ArrowDownToLine size={16}/>Download PDF</a> : <Button disabled><ArrowDownToLine size={16}/>Download PDF</Button>}
          {base ? <a className="button secondary" href={base + '/report.html?download=true'}><ArrowDownToLine size={16}/>Download HTML</a> : <Button disabled><ArrowDownToLine size={16}/>Download HTML</Button>}
          {version && <a className="button secondary" href={`/api/v1/architecture-versions/${version}/export`}><ArrowDownToLine size={16}/>Export digital twin JSON</a>}
        </div>
      </section>
      {preview && html.isPending && <p role="status">Generating the report…</p>}
      {preview && html.error ? <ErrorBox error={html.error}/> : null}
      {preview && html.data && <iframe className="report-frame" title="Report preview" sandbox="" srcDoc={keepAnchorsInFrame(html.data)} style={{ width: '100%', height: '80vh', border: '1px solid var(--neutral-200)', borderRadius: 8 }}/>}
    </>}
  </div>;
}
