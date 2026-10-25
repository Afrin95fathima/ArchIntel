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

const recipe = { id: 'concord-server', title: 'Walmart Concord server', description: 'Starts the server on a fresh PostgreSQL.', distribution_hint: 'server/dist/target/*.tar.gz',
  mode: 'STANDARD', passes: 1, dependencies: ['postgres:14.21-alpine'], scenarios: [{ name: 'Organization lifecycle', description: '', steps: 25, cleanup: 12 }] };
const apiSteps = ['CHECK_RUNNER', 'CREATE_SESSION', 'UPLOAD_DISTRIBUTION', 'START_APPLICATION', 'EXPLORE_API', 'STOP_APPLICATION', 'COMPLETE_SESSION'];
const apiDone = { id: 'j3', state: 'COMPLETED', created_at: '2026-10-23T10:00:00Z', method: 'API', recipe: { id: 'concord-server', title: 'Concord', name: 'concord-server' },
  options: { mode: null, artifact_name: 'concord-server-2.46.0-dist.tar.gz', max_requests: null, scenario_source: 'RECIPE' }, limitations: ['Fresh database per run.'],
  steps: apiSteps.map(name => ({ name, state: 'DONE', detail: null, at: 't' })), instrumentation: { mode: 'STANDARD', classes: 400, methods: 2415 },
  exploration: { method: 'API', duration_ms: 3000, stopped_by_budget: false, skipped: ['/api/v1/process/{id}/waitForCompletion'],
    summary: { requests: 240, get_routes: 108, get_routes_called: 93, statuses: { '2xx': 186, '4xx': 51 }, scenario_steps: 25, scenario_steps_passed: 25 },
    scenarios: [{ name: 'Organization lifecycle', steps: [{ id: 'create-org', kind: 'step', method: 'POST', path: '/api/v1/org', status: 200, state: 'PASSED', error: null }],
      cleanup: [{ id: 'delete-org', kind: 'cleanup', method: 'DELETE', path: '/api/v1/org/a?confirmation=yes', status: 200, state: 'PASSED', error: null }] }],
    unresolved: [{ template: '/api/v1/processcard/{cardId}/form', missing: ['cardId'] }],
    requests: [{ phase: 'crawl', method: 'GET', template: '/api/v1/org', path: '/api/v1/org', status: 200, duration_ms: 12, error: null }] },
  coverage: { spans: 12800, classes: { observed: 231, total: 2281, percentage: 10.13 }, entry_points: { observed: 96, total: 235, percentage: 40.85 } } };

function mountApi(items: unknown[] = []) {
  const posts: FormData[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const json = (b: unknown, s = 200) => ({ ok: true, status: s, json: async () => b });
    if (url.endsWith('/runtime-sessions/automation')) return json({ configured: true, reachable: true, tools: { java: true, otel_agent: true, docker: '29.7.2' } });
    if (url.endsWith('/runtime-sessions/explorations')) return json({ items });
    if (url.endsWith('/runtime-sessions/recipes')) return json({ items: [recipe] });
    if (url.endsWith('/runtime-sessions/explore-api') && init?.method === 'POST') { posts.push(init.body as FormData); return json({ ...apiDone, id: 'j4', state: 'QUEUED' }, 202); }
    return json({});
  }));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><AutoExplore applicationId="a1" analysisId="r1" /></QueryClientProvider>);
  return posts;
}

it('starts an API exploration with a launch recipe, a distribution and an optional scenario file', async () => {
  const posts = mountApi();
  fireEvent.click(await screen.findByRole('tab', { name: /REST API/ }));
  expect(await screen.findByText(/Starts the server on a fresh PostgreSQL\. Dependencies: postgres:14\.21-alpine/)).toBeTruthy();
  expect(screen.getByText(/Organization lifecycle \(25 steps, 12 cleanup\)/)).toBeTruthy();
  const start = screen.getByRole('button', { name: 'Start API exploration' }) as HTMLButtonElement;
  expect(start.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Application distribution'), { target: { files: [new File(['x'], 'concord-server-2.46.0-dist.tar.gz')] } });
  fireEvent.change(screen.getByLabelText('Scenario file'), { target: { files: [new File(['{}'], 'mine.json')] } });
  fireEvent.change(screen.getByLabelText('API instrumentation depth'), { target: { value: 'DEEP' } });
  fireEvent.change(screen.getByLabelText('Coverage passes'), { target: { value: '3' } });
  expect(start.disabled).toBe(false);
  fireEvent.click(start);
  await waitFor(() => expect(posts).toHaveLength(1));
  expect([posts[0].get('analysis_id'), posts[0].get('recipe_id'), posts[0].get('mode'), posts[0].get('max_requests'), posts[0].get('passes')]).toEqual(['r1', 'concord-server', 'DEEP', '0', '3']);
  expect((posts[0].get('scenario_file') as File).name).toBe('mine.json');
});

it('shows the API result: routes, scenario steps, coverage and what was not called', async () => {
  mountApi([apiDone]);
  const article = (await screen.findByText('Call the API routes and run the scenarios')).closest('article') as HTMLElement;
  expect(article.textContent).toContain('240 requests, 93 of 108 GET routes called, 25 of 25 scenario steps passed');
  expect(article.textContent).toContain('classes reached 231 of 2281 (10.13%), entry points 96 of 235 (40.85%), 12,800 spans');
  expect(article.textContent).toContain('Instrumentation plan: standard, 400 classes, 2415 method names.');
  expect(within(article).getByText('delete-org (cleanup)')).toBeTruthy();
  expect(article.textContent).toContain('no value seen for {cardId}');
  expect(article.textContent).toContain('Skipped by the recipe: /api/v1/process/{id}/waitForCompletion');
});

it('lists each coverage pass and its session when a job ran several', async () => {
  mountApi([{ ...apiDone, passes: [1, 2].map(index => ({ index, session_id: `${index}${index}${index}${index}abcd-0000`, plan_classes: 400, spans: 6000 + index, requests: 240, scenario_steps_passed: 25,
    classes: { observed: 200 + index, total: 2281, percentage: 9 } }))}]);
  const article = (await screen.findByText('Coverage passes (2)')).closest('article') as HTMLElement;
  expect(article.textContent).toContain('400 classes over all passes');
  expect(within(article).getByText('202 of 2281')).toBeTruthy();
  expect(within(article).getByText('2222abcd')).toBeTruthy();
});
