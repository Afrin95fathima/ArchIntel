import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { Expandable, InsightState, NodeLink, NotAvailable } from './shared';

type Row = { id: string; method: string; route: string; count: number; min_ms: number; avg_ms: number; p50_ms: number; p95_ms: number; p99_ms: number; max_ms: number; first_ms: number;
  percentiles_reliable: boolean; errors: number; error_rate_pct: number; db_calls_per_request: number; db_share_pct: number };
type Finding = { rule_id: string; label: string; severity: string; entry_point: string; measured: number; unit: string; evidence: string; action: string; reliable: boolean };
type Hotspot = { class_id: string; method: string; in_scan: boolean; domain: string | null; count: number; avg_ms: number; p95_ms: number; max_ms: number; total_ms: number };
export type PerformanceResult = {
  entry_points: Row[]; findings: Finding[]; hotspots: Hotspot[]; domains: { domain: string; calls: number; total_ms: number; avg_ms: number }[];
  summary: { requests: number; entry_points: number; non_request_traces: number; findings: number; high: number; medium: number; reliable_entry_points: number };
  rules: { id: string; label: string; metric: string; thresholds: { severity: string; at_least: number }[]; action: string }[];
  method: { min_samples: number; percentile: string; time: string; caveat: string };
  sessions: { id: string; name: string; status: string; spans: number }[];
};

const ms = (value: number) => value >= 1000 ? (value / 1000).toFixed(2) + ' s' : value.toFixed(value < 10 ? 2 : 0) + ' ms';

/** `revision` changes whenever a selected session receives spans or changes status, so the figures never go stale while a session is live. */
export function Performance({ analysisId, sessions, revision = '' }: { analysisId: string; sessions: string; revision?: string }) {
  const query = useQuery({ queryKey: ['insight', analysisId, 'performance', sessions, revision], queryFn: () => api<PerformanceResult>(`/analyses/${analysisId}/insight/performance?runtime_session_ids=${sessions}`), enabled: !!sessions });
  return <section className="runtime-card"><h2>Performance</h2>
    <p>Latency, failures and database time measured from the spans of the selected sessions. Nothing is estimated; every number comes from span timestamps and error status.</p>
    {!sessions ? <NotAvailable reason="Select at least one runtime session to measure performance." /> : <InsightState query={query}>{() => {
      const data = query.data!;
      if (!data.entry_points.length) return <NotAvailable reason={`No request entry point (HTTP server span) was observed${data.summary.non_request_traces ? `; ${data.summary.non_request_traces} traces without a request (start-up or background work) were left out` : ''}. Send requests to the application while the session is running.`} />;
      return <>
        <div className="insight-cards">
          <article><strong>{data.summary.requests}</strong><span>requests measured</span></article>
          <article><strong>{data.summary.entry_points}</strong><span>entry points ({data.summary.reliable_entry_points} with enough requests for percentiles)</span></article>
          <article><strong>{data.summary.high}</strong><span>high findings</span></article>
          <article><strong>{data.summary.medium}</strong><span>medium findings</span></article>
        </div>
        <p className="fine-print">{data.method.caveat}</p>
        {data.summary.non_request_traces > 0 && <p className="fine-print">{data.summary.non_request_traces} traces without a request (start-up, scheduled or background work) are not part of the request figures.</p>}
        <h3>Findings</h3>
        {data.findings.length === 0 ? <NotAvailable reason={`No entry point crossed a threshold across ${data.summary.requests} requests, which is not evidence of capacity, so run a load test with JMeter or k6 before extracting.`} /> :
          <ul className="detail-list">{data.findings.map(f => <li key={f.rule_id + f.entry_point}>
            <span className={'status-pill ' + f.severity.toLowerCase()}>{f.severity}</span> <strong>{f.label}</strong>: {f.entry_point} <span className="muted">({f.evidence}{f.reliable ? '' : '; too few requests for a percentile'})</span>
            <p className="fine-print">{f.action}</p></li>)}</ul>}
        <h3>Entry points</h3>
        <div className="insight-table-wrap"><table className="insight-table"><thead><tr><th>Entry point</th><th>Requests</th><th>p50</th><th>p95</th><th>Slowest</th><th>First request</th><th>Failed</th><th>DB calls / request</th><th>DB time share</th></tr></thead>
          <tbody>{data.entry_points.map(r => <tr key={r.id}>
            <td>{r.id}</td><td>{r.count}</td><td>{ms(r.p50_ms)}</td>
            <td>{r.percentiles_reliable ? ms(r.p95_ms) : <span className="muted" title={`Needs ${data.method.min_samples} requests`}>n/a</span>}</td>
            <td>{ms(r.max_ms)}</td><td>{ms(r.first_ms)}</td><td>{r.errors} ({r.error_rate_pct}%)</td><td>{r.db_calls_per_request}</td><td>{r.db_share_pct}%</td></tr>)}</tbody></table></div>
        <h3>Slowest code by total time</h3>
        <div className="insight-table-wrap"><table className="insight-table"><thead><tr><th>Method</th><th>Domain</th><th>Calls</th><th>Average</th><th>Slowest</th><th>Total</th></tr></thead>
          <tbody>{data.hotspots.map(h => <tr key={h.class_id + '#' + h.method}>
            <td>{h.in_scan ? <NodeLink id={h.class_id} /> : <span title="Not a scanned application class">{h.class_id.split('.').at(-1)}</span>}.{h.method}</td>
            <td>{h.domain ?? <span className="muted">outside the scan</span>}</td><td>{h.count}</td><td>{ms(h.avg_ms)}</td><td>{ms(h.max_ms)}</td><td>{ms(h.total_ms)}</td></tr>)}</tbody></table></div>
        <p className="fine-print">Times are inclusive: the time of showOwner includes every method and DB call it makes.</p>
        {data.domains.length > 0 && <Expandable summary={<strong>Time by candidate domain</strong>}><table className="insight-table"><thead><tr><th>Domain</th><th>Method calls</th><th>Total time</th><th>Average</th></tr></thead>
          <tbody>{data.domains.map(d => <tr key={d.domain}><td>{d.domain}</td><td>{d.calls}</td><td>{ms(d.total_ms)}</td><td>{ms(d.avg_ms)}</td></tr>)}</tbody></table></Expandable>}
        <Expandable summary={<strong>How findings are decided</strong>}><ul>{data.rules.map(rule => <li key={rule.id}><strong>{rule.label}</strong> ({rule.id}): {rule.metric}; {rule.thresholds.map(t => `${t.severity} at ${t.at_least} or more`).join(', ')}. {rule.action}</li>)}</ul>
          <p className="fine-print">Percentiles use the {data.method.percentile} method and are shown only with at least {data.method.min_samples} requests. {data.method.time}.</p></Expandable>
      </>;
    }}</InsightState>}
  </section>;
}
