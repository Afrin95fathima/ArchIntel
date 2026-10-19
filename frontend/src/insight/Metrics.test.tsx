import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { ArchitectureMetrics } from './Metrics';
import edge from './fixtures/edgecases.metrics.json';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it('shows formulas, inputs and plain meanings for a selected package', async () => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => ({ ok: true, json: async () => edge })));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ArchitectureMetrics analysisId="a1" /></QueryClientProvider>);
  fireEvent.click(await screen.findByText('com.fixture.edge.cycle.a'));
  expect(screen.getByRole('region', { name: 'Metrics for com.fixture.edge.cycle.a' })).toBeTruthy();
  expect(screen.getAllByText('Ce / (Ca + Ce); 0 when Ca + Ce = 0').length).toBeGreaterThan(0);
  expect(screen.getByText(/How many outside classes rely on this package/)).toBeTruthy();
  expect(screen.getByRole('img', { name: /Abstractness versus instability/ })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Classes' }));
  expect(await screen.findByText('ItemController')).toBeTruthy();
});
