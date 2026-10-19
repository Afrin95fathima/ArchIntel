import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { CircularDependencies } from './Cycles';
import edge from './fixtures/edgecases.cycles.json';
import clinic from './fixtures/petclinic.cycles.json';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function mount(data: unknown) {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => ({ ok: true, json: async () => data })));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><CircularDependencies analysisId="a1" /></QueryClientProvider>);
}

it('shows each cycle in order with the references that form it', async () => {
  mount(edge);
  expect(await screen.findByText(/Cycle 1: Customer → Order → Customer/)).toBeTruthy();
  expect(screen.getAllByText(/Customer cannot be changed without also checking Order, because each uses the other/).length).toBeGreaterThan(0);
  expect(screen.getByText('field Order.customer has type Customer')).toBeTruthy();
  expect(screen.getAllByRole('img', { name: /Cycle Customer to Order back to Customer/ }).length).toBe(1);
  expect(screen.getAllByText(/Suggestion only/).length).toBeGreaterThan(0);
});

it('explains the absence of cycles with the method', async () => {
  mount(clinic);
  expect(await screen.findByText(/No circular dependencies were found/)).toBeTruthy();
});
