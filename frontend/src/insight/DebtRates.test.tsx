import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { TechnicalDebt } from './TechnicalDebt';
import edge from './fixtures/edgecases.debt.json';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function mount() {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: string) => ({ ok: true, json: async () => url.endsWith('/insight/glossary')
    ? { entries: [{ id: 'rate:cycle-member', group: 'Technical problem rates', term: 'Classes in dependency cycles', answers: 'What share of the classes have this problem?', formula: 'x', numerator: 'classes that belong to a strongly connected group of two or more classes', denominator: 'all analysed top-level classes', inputs: [] }] }
    : edge })));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><TechnicalDebt analysisId="a1" /></QueryClientProvider>);
}

it('shows each problem as numerator of denominator with its percentage, sorted by percentage', async () => {
  mount();
  const panel = await screen.findByRole('region', { name: 'Technical problem rates' });
  expect(within(panel).getByRole('button', { name: /Classes in dependency cycles: 7 of 19 classes \(36\.8%\)/ })).toBeTruthy();
  expect(within(panel).getByRole('button', { name: /Classes using aging frameworks: 8 of 19 classes \(42\.1%\)/ })).toBeTruthy();
  const order = within(panel).getAllByRole('button', { name: /\(\d+(\.\d)?%\)/ }).map(b => b.getAttribute('aria-label')!.split(':')[0]);
  expect(order.slice(0, 3)).toEqual(['Mutable static state', 'Classes with at least one finding', 'Classes using aging frameworks']);
});

it('clicking a percentage lists the exact classes counted and the denominator definition', async () => {
  mount();
  const panel = await screen.findByRole('region', { name: 'Technical problem rates' });
  fireEvent.click(within(panel).getByRole('button', { name: /Classes in dependency cycles/ }));
  const list = within(panel).getByRole('list', { name: 'Items counted for Classes in dependency cycles' });
  expect(within(list).getAllByRole('listitem')).toHaveLength(7);
  expect(within(list).getByText('Order')).toBeTruthy();
  expect(within(panel).getByText(/all analysed top-level classes/)).toBeTruthy();
});

it('says which rates could not be measured and why, without showing a percentage for them', async () => {
  mount();
  const panel = await screen.findByRole('region', { name: 'Technical problem rates' });
  expect(within(panel).getByText(/Not measured: Classes never observed at runtime \(no runtime session is selected\)/)).toBeTruthy();
  expect(within(panel).queryByRole('button', { name: /Classes never observed at runtime/ })).toBeNull();
});

it('switches to per-package rows with their own denominators', async () => {
  mount();
  const panel = await screen.findByRole('region', { name: 'Technical problem rates' });
  fireEvent.change(within(panel).getByLabelText('Rate view'), { target: { value: 'package' } });
  const row = within(panel).getByText('com.fixture.edge.cycle.a', { selector: 'button' }).closest('tr')!;
  expect(within(row).getAllByText(/ of \d+ \(\d+(\.\d)?%\)/).length).toBeGreaterThan(0);
});

it('defines every rate in the glossary with its numerator and denominator', async () => {
  mount();
  const glossary = (await screen.findByText(/Glossary: how these numbers are calculated/)).closest('details')!;
  expect(await within(glossary).findByText('classes that belong to a strongly connected group of two or more classes')).toBeTruthy();
  expect(within(glossary).getByText('all analysed top-level classes')).toBeTruthy();
});
