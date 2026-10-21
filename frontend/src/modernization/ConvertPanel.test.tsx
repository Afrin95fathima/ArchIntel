import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { ConvertPanel } from './ConvertPanel';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const steps = ['PRECHECK', 'SELECT_SOURCE', 'GENERATE', 'BUILD_SERVICE', 'START_ORIGINAL', 'COMPARE', 'STOP_ORIGINAL'];
const gates = (missing: string[] = []) => ({ ready: !missing.length, model: 'claude-opus-5-5', limitations: [],
  items: ['PLAN_APPROVED', 'CLAUDE_POLICY', 'CLAUDE_KEY', 'RUNNER'].map(id => ({ id, met: !missing.includes(id), text: `${id} text` })) });
const done = { id: 'j1', state: 'COMPLETED', created_at: '2026-10-22T08:00:00Z', candidate_id: 'd-vet', candidate_name: 'Vet', service_name: 'vet', model: 'claude-opus-5-5', lane: 'LOCAL_TRIAL',
  steps: steps.map(name => ({ name, state: 'DONE', detail: null })), limitations: ['Trial lane only.'], verdict: 'REVIEW_DIFFERENCES',
  source: { commit: '30aab0ae764ad845b5eedd76028756835fec771f', files: [{ path: 'src/main/java/vet/Vet.java', bytes: 900 }], excluded: [{ path: 'src/main/resources/x.sql', reason: 'OUTSIDE_GRANT_OR_PROTECTED' }] },
  generation: { files: [{ path: 'src/main/java/vet/VetApp.java', bytes: 400, rationale: 'entry point' }], unresolved_questions: ['Who owns the vets table?'],
    usage: { model: 'claude-opus-5-5', prompt_tokens: 15000, output_tokens: 32000, duration_ms: 95000, estimated_cost_usd: 0.7 } },
  service: { state: 'RUNNING', base_url: 'http://127.0.0.1:18100' },
  comparison: { total: 2, counts: { EQUIVALENT: 1, DIFFERENT: 1 }, method: 'm', results: [
    { name: 'GET /vets.html', status: 'EQUIVALENT', differences: [], text_similarity: 1 },
    { name: 'GET /vets', status: 'DIFFERENT', differences: ['Requests differ: original [GET /vets 200], candidate [GET /vets 404].'], text_similarity: 0.2 }] } };

function mount(opts: { gates?: unknown; jobs?: unknown[]; candidate?: { id: string; name: string; proposal_state: string } } = {}) {
  const calls: { url: string; method: string; body?: unknown }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method || 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const json = (b: unknown, status = 200) => ({ ok: status < 400, status, json: async () => b });
    if (url.includes('/conversions/repositories')) return json({ items: [{ id: 'r1', name: 'spring-petclinic', commit: '30aab0ae764ad845b5eedd76028756835fec771f', granted: true }, { id: 'r2', name: 'other', commit: 'abc1234', granted: false }] });
    if (url.includes('/conversions/preconditions')) return json(opts.gates ?? gates());
    if (url.includes('/files/')) return json({ path: 'src/main/java/vet/VetApp.java', content: 'class VetApp {}', rationale: 'entry point' });
    if (url.endsWith('/conversions') && init?.method === 'POST') return json({ ...done, id: 'j2', state: 'QUEUED' }, 202);
    if (url.endsWith('/service') && init?.method === 'DELETE') return json({ ...done, service: { state: 'STOPPED', base_url: null } });
    if (url.endsWith('/conversions')) return json({ items: opts.jobs ?? [] });
    return json({});
  }));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ConvertPanel versionId="v1" planId="p1" candidate={opts.candidate ?? { id: 'd-vet', name: 'Vet', proposal_state: 'CANDIDATE_REQUIRES_REVIEW' }} /></QueryClientProvider>);
  return calls;
}

it('shows each gate and keeps the button disabled until all are met and the transfer is acknowledged', async () => {
  mount({ gates: gates(['CLAUDE_KEY']) });
  expect(await screen.findByText('Missing: CLAUDE_KEY text')).toBeTruthy();
  const list = screen.getByRole('list', { name: 'Conversion checklist' });
  expect(within(list).getByText('Met: PLAN_APPROVED text')).toBeTruthy();
  fireEvent.click(screen.getByRole('checkbox'));
  expect((screen.getByRole('button', { name: 'Convert with Claude' }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/Complete the missing items above/)).toBeTruthy();
});

it('starts a conversion with the granted repository and the explicit acknowledgement', async () => {
  const calls = mount();
  const button = await screen.findByRole('button', { name: 'Convert with Claude' }) as HTMLButtonElement;
  await waitFor(() => expect((screen.getByLabelText('Source repository') as HTMLSelectElement).value).toBe('r1'));   // the first repository with a grant
  expect(button.disabled).toBe(true);
  fireEvent.click(screen.getByRole('checkbox'));
  await waitFor(() => expect(button.disabled).toBe(false));
  fireEvent.click(button);
  await waitFor(() => expect(calls.some(c => c.method === 'POST')).toBe(true));
  expect(calls.find(c => c.method === 'POST')!.body).toEqual({ candidate_id: 'd-vet', repository_id: 'r1', acknowledgement: 'I_APPROVE_SENDING_SELECTED_SOURCE_TO_ANTHROPIC_CLAUDE' });
  expect((screen.getByRole('option', { name: /other .*no grant/ }) as HTMLOptionElement).disabled).toBe(true);
});

it('shows the verdict, the differences, the running service, cost, open questions and the generated code', async () => {
  const calls = mount({ jobs: [done] });
  expect(await screen.findByText('Some replayed scenarios behaved differently')).toBeTruthy();
  expect(screen.getByText(/1 of 2 equivalent/)).toBeTruthy();
  expect(screen.getByText(/candidate \[GET \/vets 404\]/)).toBeTruthy();
  expect(screen.getByRole('link', { name: 'http://127.0.0.1:18100' })).toBeTruthy();
  expect(screen.getByText(/15,000 input and 32,000 output tokens in 95 s, estimated \$0.7/)).toBeTruthy();
  expect(screen.getByText('Who owns the vets table?')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'src/main/java/vet/VetApp.java' }));
  expect(await screen.findByText('class VetApp {}')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Stop service' }));
  await waitFor(() => expect(calls.some(c => c.method === 'DELETE' && c.url.endsWith('/conversions/j1/service'))).toBe(true));
});

it('reports where a failed conversion stopped, with the build log', async () => {
  mount({ jobs: [{ ...done, state: 'FAILED', verdict: undefined, comparison: undefined, error: { step: 'BUILD_SERVICE', code: 'BUILD_FAILED', detail: '[ERROR] cannot find symbol' },
    service: { state: 'BUILD_FAILED', base_url: null, build_log_tail: '[ERROR] cannot find symbol' } }] });
  expect((await screen.findByRole('alert')).textContent).toBe('Stopped at “Build and start it in Docker”: BUILD_FAILED: [ERROR] cannot find symbol');
});

it('offers no conversion for a technical domain', () => {
  mount({ candidate: { id: 'd-cfg', name: 'System Configuration', proposal_state: 'TECHNICAL_DOMAIN_NOT_A_SERVICE' } });
  expect(screen.queryByRole('button', { name: 'Convert with Claude' })).toBeNull();
});
