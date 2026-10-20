import type {DatabaseObservation,DatabaseSummary,MappingReport,SpanRef} from './types';

const NOT_RECORDED='Not available: this session was completed before mapping details were captured. Create a new session to see them.';

function Samples({refs}:{refs:SpanRef[]}){
  return <>{refs.map(r=><code key={r.session_id+r.trace_id+r.span_id} title={`session ${r.session_id} trace ${r.trace_id}`}>{r.span_id}</code>).reduce<React.ReactNode[]>((all,el,i)=>i?[...all,' ',el]:[el],[])}</>;
}

export function MappingDetails({report}:{report?:MappingReport}){
  if(!report)return <section className="runtime-card"><h2>Static ↔ runtime identities</h2><p>{NOT_RECORDED}</p></section>;
  return <section className="runtime-card" aria-label="Runtime mapping details">
    <h2>Static ↔ runtime identities</h2>
    <p><strong>Why this table exists.</strong> {report.why}</p>
    <h3>Resolved ({report.resolved.length})</h3>
    {report.resolved.length?<table><thead><tr><th>Runtime identifier</th><th>Resolved to</th><th>Rule</th><th>Events</th><th>Sample span ids</th></tr></thead><tbody>
      {report.resolved.map(r=><tr key={r.rule+r.runtime_identifier+r.static_class+(r.static_method||'')}>
        <td><code>{r.runtime_identifier}</code></td><td><code>{r.static_class}{r.static_method?'.'+r.static_method+'()':''}</code>{r.declared_route&&<small> via route {r.declared_route}</small>}</td>
        <td><strong>{r.rule}</strong><small>{r.rule_label}</small></td><td>{r.event_count}</td><td><Samples refs={r.sample_span_ids}/></td></tr>)}
    </tbody></table>:<p>No span resolved to a scanned class (see Not mapped below).</p>}
    <h3>Not mapped ({report.counts.unmapped} events in {report.unmapped.length} groups)</h3>
    {report.unmapped.length?<table><thead><tr><th>Reason</th><th>Span</th><th>Missing</th><th>Events</th><th>What the span still tells us</th><th>Sample span ids</th></tr></thead><tbody>
      {report.unmapped.map((u,i)=><tr key={i}>
        <td><strong>{u.reason_code}</strong><small>{u.reason}</small>{u.closest_candidate&&<small>Closest scanned class: <code>{u.closest_candidate}</code> (similarity {u.similarity})</small>}</td>
        <td>{u.span_names.length?u.span_names.join(', '):'no span name'}<small>kind {u.span_kind||'not recorded'} · type {u.event_type} · scope {u.instrumentation_scope||'not recorded'}{u.scope_version?' '+u.scope_version:''}</small>{u.runtime_identifier&&<small>class <code>{u.runtime_identifier}</code></small>}</td>
        <td>{u.missing_attributes.length?u.missing_attributes.join(', '):'none'}</td><td>{u.event_count}</td><td>{u.still_tells_us}</td><td><Samples refs={u.sample_span_ids}/></td></tr>)}
    </tbody></table>:<p>Every span mapped to a class or route; the Not mapped table is empty.</p>}
    {report.truncated&&<p className="fine-print">Only the 200 largest groups of each table are shown; the counts above include every span.</p>}
  </section>;
}

export function DatabaseCallers({rows,summary}:{rows:DatabaseObservation[];summary?:DatabaseSummary}){
  return <section className="runtime-card" aria-label="Database observations">
    <h2>Observed persistence signals</h2>
    <p>SQL text and parameter values are discarded after the operation and table names are read from them.</p>
    {summary?<p><strong>{summary.text}</strong></p>:<p>{NOT_RECORDED}</p>}
    <table><thead><tr><th>Caller</th><th>Depth</th><th>Operation</th><th>Tables</th><th>System</th><th>Calls</th><th>Sample span ids</th></tr></thead><tbody>
      {rows.map((d,i)=><tr key={i}>
        <td>{d.caller_class?<><code>{d.caller_class}{d.caller_method?'.'+d.caller_method+'()':''}</code>{d.thread_boundary?.crosses_thread&&<small>Runs on thread {d.thread_boundary.caller_thread}; database call on {d.thread_boundary.database_thread}</small>}</>
          :d.reason_code?<><strong>Not resolved: {d.reason_code}</strong><small>{d.reason}</small></>:<><strong>Not resolved</strong><small>{NOT_RECORDED}</small></>}</td>
        <td>{d.depth==null?'not applicable':d.depth===0?'0 (own attributes)':d.depth}</td>
        <td>{d.operation||'not recorded'}</td><td>{(d.tables?.length?d.tables:d.resource?[d.resource]:[]).join(', ')||'not recorded'}</td><td>{d.system}</td><td>{d.call_count}</td><td><Samples refs={d.sample_span_ids||[]}/></td></tr>)}
    </tbody></table>
  </section>;
}
