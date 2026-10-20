import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { TechnicalDebt } from './TechnicalDebt';
import edge from './fixtures/edgecases.debt.json';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function mount() {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => ({ ok: true, json: async () => edge })));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><TechnicalDebt analysisId="a1" /></QueryClientProvider>);
}

it('lists specific findings with measured value, threshold and both explanation layers', async () => {
  mount();
  fireEvent.change(await screen.findByLabelText('Rule'), { target: { value: 'DEBT-LAYER-VIOLATION' } });
  const table = screen.getAllByRole('table').at(-1)!;
  expect(within(table).getByText(/from layer: DOMAIN; to layer: PRESENTATION/)).toBeTruthy();
  expect(within(table).getByText(/BillingRecord belongs to the domain model layer but depends on BillingAction/)).toBeTruthy();
  fireEvent.click(within(table).getByRole('button', { name: 'Layer violation' }));
  expect(screen.getByText('BillingRecord.touch() calls BillingAction.oldApi()')).toBeTruthy();
  expect(screen.getByText('Technical')).toBeTruthy();
});

it('groups by package and shows the debt index formula', async () => {
  mount();
  fireEvent.change(await screen.findByLabelText('Group findings'), { target: { value: 'package' } });
  expect(screen.getAllByText(/com.fixture.edge.legacy/).length).toBeGreaterThan(0);
  expect(screen.getByText(/debt index = 3 × HIGH/)).toBeTruthy();
  expect(screen.getByText(/not a time, cost or currency estimate/)).toBeTruthy();
});

it('publishes the opened finding as the page selection for the docked assistant, and clears it on close', async () => {
  mount();
  const seen: (unknown)[] = [];
  const listener = (event: Event) => seen.push((event as CustomEvent).detail);
  window.addEventListener('archintel-assistant-context', listener);
  fireEvent.change(await screen.findByLabelText('Rule'), { target: { value: 'DEBT-LAYER-VIOLATION' } });
  const table = screen.getAllByRole('table').at(-1)!;
  fireEvent.click(within(table).getByRole('button', { name: 'Layer violation' }));
  expect(seen.at(-1)).toEqual({ kind: 'class', id: 'com.fixture.edge.legacy.BillingRecord', label: 'BillingRecord' });
  fireEvent.click(within(table).getByRole('button', { name: 'Layer violation' }));
  expect(seen.at(-1)).toBeNull();
  window.removeEventListener('archintel-assistant-context', listener);
});
