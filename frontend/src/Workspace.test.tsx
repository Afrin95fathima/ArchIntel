import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { Workspace } from './Workspace';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('reuses the project and application created by a failed upload when the corrected file is sent again', async () => {
  const calls: { method: string; path: string }[] = [];
  let artifactAttempts = 0;
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url).replace('/api/v1', ''); const method = init?.method || 'GET'; calls.push({ method, path });
    const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) });
    if (path === '/projects' && method === 'POST') return ok({ id: 'p1', name: 'New' });
    if (path === '/applications' && method === 'POST') return ok({ id: 'a1', project_id: 'p1', name: 'Shop', version: '1.0', source_type: 'ZIP' });
    if (path === '/applications/a1/artifact') { artifactAttempts += 1; return artifactAttempts === 1 ? { ok: false, status: 422, json: async () => ({ detail: 'This ZIP contains no compiled Java output.' }), text: async () => '' } : ok({ id: 'art' }); }
    if (path === '/applications/a1/analysis') return ok({ id: 'run1', application_id: 'a1', status: 'RUNNING', progress: 0 });
    return ok([]);
  }));
  const started = vi.fn();
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><Workspace projects={[]} applications={[]} analyses={[]} onSelect={() => {}} onStarted={started} refresh={() => {}} /></QueryClientProvider>);
  fireEvent.click(screen.getByRole('button', { name: 'Analyze application' }));
  const choose = (name: string) => fireEvent.change(screen.getByLabelText('Java artifact or compiled project ZIP'), { target: { files: [new File(['x'], name)] } });
  fireEvent.change(screen.getByLabelText('New project name'), { target: { value: 'New' } });
  fireEvent.change(screen.getByLabelText('Application name'), { target: { value: 'Shop' } });
  fireEvent.change(screen.getByLabelText('Version'), { target: { value: '1.0' } });
  choose('source-only.zip');
  fireEvent.submit(screen.getByRole('button', { name: 'Start architecture analysis' }).closest('form') as HTMLFormElement);
  expect(await screen.findByText(/This ZIP contains no compiled Java output/)).toBeTruthy();
  choose('compiled.zip');
  fireEvent.submit(screen.getByRole('button', { name: 'Start architecture analysis' }).closest('form') as HTMLFormElement);
  await waitFor(() => expect(started).toHaveBeenCalled());
  expect(calls.filter(c => c.method === 'POST' && c.path === '/projects')).toHaveLength(1);
  expect(calls.filter(c => c.method === 'POST' && c.path === '/applications')).toHaveLength(1);
  expect(calls.filter(c => c.path === '/applications/a1/artifact')).toHaveLength(2);
});
