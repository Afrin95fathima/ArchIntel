import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { TaskWorkspace } from './TaskWorkspace';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const applications = [{ id: 'a1', project_id: 'p', name: 'PetClinic', version: '1', source_type: 'JAR' }];

function mount(reviews: { state: string }[]) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const json = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
    if (url.endsWith('/applications/a1/architecture-versions')) return json([{ id: 'v1', name: 'Version one' }]);
    if (url.endsWith('/architecture-versions/v1/modernization')) return json([{ id: 'p1', strategy: 'MICROSERVICES', objective: 'o' }]);
    if (url.endsWith('/architecture-versions/v1/modernization/p1')) return json({ document: { decisions: [{ id: 'd1', kind: 'COLLECT_MORE_EVIDENCE', domain_id: 'domain-6a0f3c1e9b' }], assessments: [{ domain_id: 'domain-6a0f3c1e9b', domain_name: 'Vet' }] }, reviews });
    if (url.endsWith('/transformation/capabilities')) return json({ sandbox: { available: false, reason: 'No sandbox in this test.' } });
    if (url.endsWith('/security/ai/gemini/status')) return json({ credential_configured: false, model: 'm', generation_route_enabled: false });
    if (url.endsWith('/security/policy')) return json({});
    return json([]);
  }));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><TaskWorkspace applications={applications as never} /></QueryClientProvider>);
}

it('names the domain of a decision instead of showing its id', async () => {
  mount([{ state: 'APPROVED_PLANNING' }]);
  expect(await screen.findByRole('option', { name: 'COLLECT_MORE_EVIDENCE (Vet)' })).toBeTruthy();
});

it('says so when the latest review of the selected proposal is not an approval', async () => {
  mount([{ state: 'APPROVED_PLANNING' }, { state: 'REJECTED' }]);
  expect(await screen.findByText(/The latest review of this proposal is rejected, so a source task cannot be created from it/)).toBeTruthy();
  cleanup();
  mount([{ state: 'APPROVED_PLANNING' }]);
  await screen.findByRole('option', { name: 'COLLECT_MORE_EVIDENCE (Vet)' });
  expect(screen.queryByText(/latest review of this proposal/)).toBeNull();
});
