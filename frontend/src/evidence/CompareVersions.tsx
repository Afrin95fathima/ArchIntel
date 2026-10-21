import {useState} from 'react';
import {api} from '../api';
import {CLASSIFICATION_LABEL,humanize} from './verdict';

type Counts=Record<string,number>;
export type Comparison={from_version:string;to_version:string;percentage_point_delta:Record<string,number|null>;same_domain_review:boolean;runtime_sessions:{before:number;after:number};
  domains:{id:string;name:string;before:{observed:number;total:number}|null;after:{observed:number;total:number}}[];moved_classes:{cls:string;from_domain:string;to_domain:string}[];moved_total:number;renamed_domains:{id:string;from_name:string;to_name:string}[];
  facts:{before:Counts;after:Counts;changed:{source:string;target:string;before:string|null;after:string}[];changed_total:number};suggestions:{before:number;after:number;closed:string[];closed_total:number;opened:string[];opened_total:number}};
type V={id:string;name:string;analysis_id:string};
const short=(id:string)=>id.slice(id.lastIndexOf('.',id.lastIndexOf('.')-1)+1);
const signed=(n:number)=>`${n>0?'+':''}${n}`;

/** Earlier version versus the selected one: what moved, what was confirmed and which suggestions closed. */
export function CompareVersions({current,versions}:{current:V;versions:V[]}){
  const options=versions.filter(v=>v.id!==current.id&&v.analysis_id===current.analysis_id);
  const [other,setOther]=useState('');const [result,setResult]=useState<Comparison|null>(null);const [error,setError]=useState('');const [busy,setBusy]=useState(false);
  async function run(id:string){setOther(id);setResult(null);setError('');if(!id)return;setBusy(true);try{setResult(await api<Comparison>('/architecture-versions/'+id+'/compare/'+current.id));}catch(e){setError(e instanceof Error?e.message:'The comparison failed.');}finally{setBusy(false);}}
  if(!options.length)return <section className="runtime-card"><h2>Compare with an earlier version</h2><p>Only one version exists for this static baseline, so there is nothing to compare yet. Capture a second version after new telemetry or a domain review.</p></section>;
  return <section className="runtime-card evidence-compare" aria-label="Compare versions"><h2>Compare with an earlier version</h2>
    <label>Earlier version<select value={other} onChange={e=>void run(e.target.value)}><option value="">Select a version</option>{options.map(v=><option key={v.id} value={v.id}>{v.name} ({v.id.slice(0,8)})</option>)}</select></label>
    {busy&&<p role="status">Comparing…</p>}{error&&<p role="alert">{error}</p>}
    {result&&<>
      <p><strong>Runtime sessions:</strong> {result.runtime_sessions.before} before, {result.runtime_sessions.after} now.</p>
      <h3>Coverage by domain</h3><ul className="evidence-list">{result.domains.map(d=><li key={d.id}>{d.name}: {d.before?`${d.before.observed} of ${d.before.total}`:'not recorded'} classes before, {d.after.observed} of {d.after.total} now{d.before?` (${signed(d.after.observed-d.before.observed)})`:''}</li>)}</ul>
      <p className="fine-print">{Object.entries(result.percentage_point_delta).filter(([,v])=>v!==null).map(([k,v])=>`${humanize(k)} ${signed(v as number)} points`).join(' | ')||'No percentage change can be computed for these two versions.'}{!result.same_domain_review&&' The domain delta is withheld because the two versions use different domain boundaries.'}</p>
      {(result.renamed_domains.length>0||result.moved_total>0)&&<><h3>Domain boundaries</h3><ul className="evidence-list">{result.renamed_domains.map(r=><li key={r.id}>Renamed: {r.from_name} to {r.to_name}</li>)}{result.moved_classes.map(m=><li key={m.cls}>Moved {short(m.cls)} from {m.from_domain} to {m.to_domain}</li>)}{result.moved_total>result.moved_classes.length&&<li>{result.moved_total-result.moved_classes.length} more classes moved.</li>}</ul></>}
      <h3>Dependencies</h3><p>{Object.entries(CLASSIFICATION_LABEL).map(([k,label])=>`${label}: ${result.facts.before[k]??0} before, ${result.facts.after[k]??0} now`).join(' | ')}.</p>
      {result.facts.changed_total>0&&<ul className="evidence-list">{result.facts.changed.slice(0,8).map(f=><li key={f.source+f.target}>{short(f.source)} → {short(f.target)}: {f.before?CLASSIFICATION_LABEL[f.before]:'not present'} before, {CLASSIFICATION_LABEL[f.after]} now</li>)}{result.facts.changed_total>8&&<li>{result.facts.changed_total-8} more dependencies changed.</li>}</ul>}
      <h3>Suggestions</h3><p>{result.suggestions.closed_total} closed and {result.suggestions.opened_total} new ({result.suggestions.before} before, {result.suggestions.after} now).</p>
      {result.suggestions.closed.length>0&&<ul className="evidence-list">{result.suggestions.closed.slice(0,5).map(t=><li key={t}>Closed: {t}</li>)}</ul>}
    </>}
  </section>;
}
