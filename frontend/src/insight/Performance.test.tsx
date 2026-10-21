import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { Performance, type PerformanceResult } from './Performance';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function mount(data: unknown, sessions = 's1') {
  const fetchMock = vi.fn().mockImplementation(async () => ({ ok: true, json: async () => data }));
  vi.stubGlobal('fetch', fetchMock);
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><Performance analysisId="a1" sessions={sessions} /></QueryClientProvider>);
  return fetchMock;
}
const row = { id: 'GET /owners/{id}', method: 'GET', route: '/owners/{id}', count: 3, min_ms: 100, avg_ms: 200, p50_ms: 200, p95_ms: 300, p99_ms: 300, max_ms: 3000, first_ms: 450, percentiles_reliable: false, errors: 1, error_rate_pct: 33.3, db_calls_per_request: 12.5, db_share_pct: 61.2 };
const result: PerformanceResult = {
  entry_points: [row, { ...row, id: 'GET /vets', route: '/vets', count: 40, percentiles_reliable: true, p95_ms: 640, max_ms: 700, errors: 0, error_rate_pct: 0 }],
  findings: [{ rule_id: 'PERF-SLOW', label: 'Slow entry point', severity: 'HIGH', entry_point: 'GET /owners/{id}', measured: 3000, unit: 'p95 latency (ms)', evidence: 'slowest of 3 requests 3000.0 ms', action: 'Profile this route first.', reliable: false }],
  hotspots: [{ class_id: 'app.owner.OwnerController', method: 'showOwner', in_scan: true, domain: 'Owner Visit', count: 3, avg_ms: 10, p95_ms: 12, max_ms: 12, total_ms: 30 },
             { class_id: 'org.lib.Helper', method: 'run', in_scan: false, domain: null, count: 1, avg_ms: 2000, p95_ms: 2000, max_ms: 2000, total_ms: 2000 }],
  domains: [{ domain: 'Owner Visit', calls: 3, total_ms: 30, avg_ms: 10 }],
  summary: { requests: 43, entry_points: 2, non_request_traces: 72, findings: 1, high: 1, medium: 0, reliable_entry_points: 1 },
  rules: [{ id: 'PERF-SLOW', label: 'Slow entry point', metric: 'p95 latency (ms)', thresholds: [{ severity: 'MEDIUM', at_least: 500 }, { severity: 'HIGH', at_least: 2000 }], action: 'Profile this route first.' }],
  method: { min_samples: 20, percentile: 'nearest rank', time: 'inclusive span duration', caveat: 'Measured under the observed traffic only (not production load).' },
  sessions: [{ id: 's1', name: 'PetClinic', status: 'COMPLETED', spans: 329 }],
};

it('asks the performance endpoint for the selected sessions', async () => {
  const fetchMock = mount(result, 's1,s2');
  await screen.findByText('requests measured');
  expect(String(fetchMock.mock.calls[0][0])).toContain('/analyses/a1/insight/performance?runtime_session_ids=s1,s2');
});

it('shows percentiles only where there were enough requests and states why otherwise', async () => {
  mount(result);
  await screen.findByText('requests measured');
  const rows = screen.getAllByRole('row');
  const few = rows.find(r => r.textContent?.includes('GET /owners/{id}') && r.textContent.includes('33.3%'))!;
  expect(few.textContent).toContain('n/a');                 // 3 requests: no p95
  expect(few.textContent).toContain('3.00 s');              // slowest is still shown
  const enough = rows.find(r => r.textContent?.startsWith('GET /vets'))!;
  expect(enough.textContent).toContain('640 ms');
});

it('lists findings with severity, measured evidence, the reason a percentile is not claimed and the action', async () => {
  mount(result);
  expect(await screen.findByText('Slow entry point')).toBeTruthy();
  expect(screen.getByText('HIGH')).toBeTruthy();
  expect(screen.getByText(/slowest of 3 requests 3000.0 ms; too few requests for a percentile/)).toBeTruthy();
  expect(screen.getAllByText('Profile this route first.').length).toBeGreaterThan(0);
});

it('marks code outside the scan and reports background traces separately', async () => {
  mount(result);
  expect(await screen.findByText('outside the scan')).toBeTruthy();
  expect(screen.getByText(/72 traces without a request/)).toBeTruthy();
  expect(screen.getByText(/not production load/)).toBeTruthy();
});

it('fetches again when a selected session receives more spans', async () => {
  const fetchMock = mount(result);
  await screen.findByText('requests measured');
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = (revision: string) => <QueryClientProvider client={client}><Performance analysisId="a1" sessions="s1" revision={revision} /></QueryClientProvider>;
  const { rerender } = render(view('s1:RUNNING:100'));
  await screen.findAllByText('requests measured');
  const before = fetchMock.mock.calls.length;
  rerender(view('s1:RUNNING:100'));
  expect(fetchMock.mock.calls.length).toBe(before);              // unchanged evidence: no new request
  rerender(view('s1:COMPLETED:329'));
  await vi.waitFor(() => expect(fetchMock.mock.calls.length).toBe(before + 1));
});

it('explains an empty result and a missing selection instead of showing zeros', async () => {
  mount({ ...result, entry_points: [], summary: { ...result.summary, non_request_traces: 72 } });
  expect(await screen.findByText(/No request entry point \(HTTP server span\) was observed; 72 traces/)).toBeTruthy();
  cleanup();
  const fetchMock = mount(result, '');
  expect(screen.getByText('Select at least one runtime session to measure performance.')).toBeTruthy();
  expect(fetchMock).not.toHaveBeenCalled();
});
