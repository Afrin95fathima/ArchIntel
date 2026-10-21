import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { AutoExplore } from './AutoExplore';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const steps = ['CHECK_RUNNER', 'CREATE_SESSION', 'UPLOAD_ARTIFACT', 'START_APPLICATION', 'EXPLORE', 'STOP_APPLICATION', 'COMPLETE_SESSION'];
const done = { id: 'j1', state: 'COMPLETED', created_at: '2026-10-21T10:00:00Z', options: { max_pages: 40, max_forms: 12, mode: 'STANDARD', artifact_name: 'petclinic.jar' },
  steps: steps.map(name => ({ name, state: 'DONE', detail: name === 'EXPLORE' ? '11 pages, 6 of 6 forms submitted, 18 routes observed.' : null, at: 't' })), session_id: 's1', limitations: ['Exploration creates data.'],
  exploration: { summary: { pages: 11, forms: 6, forms_completed: 6, routes: 18, failures: 0, skipped: 1, duration_ms: 17000 }, routes: [{ method: 'POST', shape: '/owners/new', statuses: [302] }],
    forms: [{ method: 'POST', shape: '/owners/new', completed: true, statuses: [302], error: null }], skipped: [{ url: 'http://x/owners/1/delete', reason: 'DESTRUCTIVE_LOOKING_LINK' }], failures: [], unvisited: [], stopped_by_time: false },
  coverage: { spans: 1234, classes: { observed: 21, total: 25, percentage: 84 } } };

function mount(status: unknown, items: unknown[] = [done], onPost?: (body: FormData) => unknown) {
  const posts: FormData[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const json = (b: unknown, ok = true, s = 200) => ({ ok, status: s, json: async () => b });
    if (url.endsWith('/runtime-sessions/automation')) return json(status);
    if (url.endsWith('/runtime-sessions/explorations')) return json({ items });
    if (url.endsWith('/runtime-sessions/explore') && init?.method === 'POST') { posts.push(init.body as FormData); return json(onPost ? onPost(init.body as FormData) : { ...done, id: 'j2', state: 'QUEUED' }, true, 202); }
    return json({});
  }));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><AutoExplore applicationId="a1" analysisId="r1" /></QueryClientProvider>);
  return posts;
}

it('tells the user how to start the runner when it is not configured or not reachable', async () => {
  mount({ configured: false, reachable: false });
  expect(await screen.findByText(/Start it with scripts\/runner-start.sh, then restart ArchIntel/)).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Start exploration' })).toBeNull();
  cleanup();
  mount({ configured: true, reachable: false, reason: 'RUNNER_UNREACHABLE' });
  expect(await screen.findByText(/not reachable \(RUNNER_UNREACHABLE\)/)).toBeTruthy();
});

it('starts only with a runnable archive and the disposable-data consent, and sends the limits', async () => {
  const posts = mount({ configured: true, reachable: true, tools: { java: true, chrome: true, otel_agent: true, rea: '6.7.0', docker: '29.7.2' } }, []);
  expect(await screen.findByText(/Runner ready: Java available, Chrome available, OpenTelemetry agent available, REA 6.7.0, Docker 29.7.2/)).toBeTruthy();
  const start = screen.getByRole('button', { name: 'Start exploration' }) as HTMLButtonElement;
  expect(start.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Runnable application JAR or WAR'), { target: { files: [new File(['PK'], 'petclinic.jar')] } });
  expect(start.disabled).toBe(true);                                   // consent still missing
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.change(screen.getByLabelText('Most pages'), { target: { value: '25' } });
  expect(start.disabled).toBe(false);
  fireEvent.click(start);
  await waitFor(() => expect(posts).toHaveLength(1));
  expect([posts[0].get('analysis_id'), posts[0].get('max_pages'), posts[0].get('max_forms'), posts[0].get('mode'), posts[0].get('confirm_disposable_data')]).toEqual(['r1', '25', '12', 'DEEP', 'true']);
});

it('shows each step, the result in numbers and what was not covered', async () => {
  mount({ configured: true, reachable: true, tools: {} });
  const article = (await screen.findByText('Explore with REA')).closest('article') as HTMLElement;
  expect(within(article).getByText('Explore with REA')).toBeTruthy();
  expect(within(article).getByText('11 pages, 6 of 6 forms submitted, 18 routes observed.')).toBeTruthy();
  expect(article.textContent).toContain('classes reached 21 of 25 (84%), 1,234 spans');
  expect(within(article).getByText(/destructive looking link/)).toBeTruthy();
});

it('reports where a failed exploration stopped and why', async () => {
  mount({ configured: true, reachable: true, tools: {} }, [{ ...done, state: 'FAILED', exploration: undefined, coverage: undefined, error: { step: 'START_APPLICATION', code: 'APP_START_TIMEOUT', detail: '' },
    steps: done.steps.map(s => s.name === 'START_APPLICATION' ? { ...s, state: 'FAILED' } : s) }]);
  expect((await screen.findByRole('alert')).textContent).toBe('Stopped at “Start it with the OpenTelemetry agent”: APP_START_TIMEOUT.');
});
