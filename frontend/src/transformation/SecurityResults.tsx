export type SecurityEvidence={state:string;error_code?:string;result?:{
 tool:string;tool_version:string;plugin:string;plugin_version:string;image_id:string;
 findings:{rule:string;priority:number;class_name:string}[];
 dependency_scan:{state:string;reason:string;coverage?:string;findings?:{id:string;package:string;installed:string;fixed:string;severity:string}[]}
}};

export function SecurityResults({evidence,onScan,disabled}:{evidence?:SecurityEvidence;onScan:()=>void;disabled:boolean}){
 const result=evidence?.result;
 return <section className="runtime-card">
  <h2>Java security analysis</h2>
  <p>Scan the captured candidate artifact with the separately provisioned security tools. Missing classes, expired databases and scanner errors prevent a pass. Complete runtime dependency coverage remains a separate requirement.</p>
  <button disabled={disabled} onClick={onScan}>Run Java security scan</button>
  {evidence&&<p role="status">Security analysis: {evidence.state}. {evidence.error_code}</p>}
  {result&&<>
   <p>{result.tool} {result.tool_version}, {result.plugin} {result.plugin_version}</p>
   <ul>{result.findings.map((f,i)=><li key={i}>{f.rule} — {f.class_name} (priority {f.priority})</li>)}</ul>
   <h3>Packaged dependencies: {result.dependency_scan.state}</h3>
   <p>{result.dependency_scan.reason}. Coverage: {result.dependency_scan.coverage||'Not established'}.</p>
   {!!result.dependency_scan.findings?.length&&<table><thead><tr><th>Vulnerability</th><th>Package</th><th>Severity</th><th>Fixed version</th></tr></thead><tbody>
    {result.dependency_scan.findings.map((f,i)=><tr key={i}><td>{f.id}</td><td>{f.package} {f.installed}</td><td>{f.severity}</td><td>{f.fixed||'No fix reported'}</td></tr>)}
   </tbody></table>}
   <details><summary>Scanner image</summary><code>{result.image_id}</code></details>
  </>}
 </section>;
}
