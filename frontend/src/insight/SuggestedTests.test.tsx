import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { SuggestedTests } from './SuggestedTests';
import tests from './fixtures/petclinic.tests.json';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function mount(data: unknown) {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => ({ ok: true, json: async () => data })));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><SuggestedTests analysisId="a1" sessions="" /></QueryClientProvider>);
}

it('shows the route, form fields with constraints, preconditions and expected gain', async () => {
  mount(tests);
  fireEvent.click(await screen.findByRole('button', { name: /POST \/owners\/\{ownerId\}\/pets\/\{petId\}\/visits\/new/ }));
  expect(screen.getByText(/POST \/owners\/1\/pets\/1\/visits\/new/)).toBeTruthy();
  expect(screen.getByText(/description=example\s+\(required\)\s+\[must not be blank\]/)).toBeTruthy();
  expect(screen.getAllByText(/an Owner with ownerId=1 exists in the database/).length).toBeGreaterThan(0);
  expect(screen.queryByText(/required fields: firstName/)).toBeNull();
  expect(screen.getByText(/Would newly exercise/)).toBeTruthy();
});

it('states clearly when suggestions cannot be derived', async () => {
  mount({ status: 'NOT_AVAILABLE', reason: 'Bytecode facts are not available for this analysis (run a new analysis); routes and call paths cannot be derived.', suggestions: [] });
  expect(await screen.findByText(/Bytecode facts are not available/)).toBeTruthy();
});
