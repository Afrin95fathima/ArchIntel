import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { TechnologyLifecycle } from './TechnologyLifecycle';
import edge from './fixtures/edgecases.lifecycle.json';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function mount(data: unknown) {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => ({ ok: true, json: async () => data })));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><TechnologyLifecycle analysisId="a1" /></QueryClientProvider>);
}

it('lists aging technologies with affected classes, call sites and alternatives from real fixture output', async () => {
  mount(edge);
  const log4j = await screen.findByRole('button', { name: 'Apache Log4j 1.x' });
  expect(screen.getAllByText('End-of-life').length).toBeGreaterThan(0);
  expect(screen.queryByText(/vulnerab/i, { selector: '.status-pill' })).toBeNull();
  fireEvent.click(log4j);
  expect(screen.getByText(/Log4j 2 \(org.apache.logging.log4j\)/)).toBeTruthy();
  fireEvent.click(screen.getAllByRole('button', { name: 'Show details' })[0]);
  expect(screen.getByText(/BillingAction.execute\(\) calls Logger.info\(\)/)).toBeTruthy();
  expect(screen.getByText('Plain language')).toBeTruthy();
  expect(screen.getByText('Technical')).toBeTruthy();
});

it('warns when the rules file is stale', async () => {
  mount({ ...edge, rules: { ...edge.rules, stale: true, warning: 'Lifecycle rules were last reviewed 400 days ago (limit 180).' } });
  expect(await screen.findByRole('alert')).toBeTruthy();
});

it('says why nothing is shown when no rule matches', async () => {
  mount({ ...edge, findings: [], summary: {} });
  expect(await screen.findByText(/No rule in the lifecycle rules file matched/)).toBeTruthy();
});
