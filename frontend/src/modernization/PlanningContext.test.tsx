import { cleanup, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { PlanningContext } from './PlanningContext';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const missing = (reason: string) => ({ value: null, not_measured: reason });
const field = (value: unknown, extra = {}) => ({ value, source: 's', ...extra });
const data = (over: Record<string, unknown> = {}) => ({
  version: { id: field('v1'), name: field('PetClinic capture'), fingerprint: field('ab12cd'), captured_at: field('2026-10-20T09:00:00Z') },
  scan: { analysis_id: field('a1'), scan_date: field('2026-10-19T08:00:00Z'), algorithm_version: field('0.2.1') }, artifact: { name: field('petclinic.jar'), sha256: field('f'.repeat(64)) },
  counts: { classes: field(24), packages: field(5), domains: field(5), class_cycle_groups: field(0), aging_technology_findings: field(2), entry_points: field(18) },
  runtime: { sessions: [{ id: 's-1', name: 'Smoke run', environment: 'LOCAL', status: 'COMPLETED', started_at: '2026-10-20T08:00:00Z', ended_at: '2026-10-20T08:30:00Z', traces: 41, spans: 410 }], session_count: 1,
    traces: field(41, { unit: 'traces (one per request or job)' }), class_coverage: { value: 75, observed: 3, total: 4, text: '75.0% (3 of 4)' }, entry_point_coverage: missing('Raw method evidence expired'), method_coverage: missing('no method evidence') },
  review: { domain_review: missing('no domain review is recorded for this version') }, changes: { state: 'NO_EARLIER_VERSION', text: 'No earlier architecture version exists for this application, so nothing can be compared.' },
  takes_into_account: ['Runtime coverage: 75.0% of classes (3 of 4).'], does_not_take_into_account: ['Behavioral contract tests: none are recorded for this version.'], ...over });
function mount(body: unknown) {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => body })));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><PlanningContext versionId="v1" /></QueryClientProvider>);
}

it('shows each fact with its value, and every missing fact as "not measured" with the reason', async () => {
  mount(data());
  const panel = await screen.findByRole('region', { name: 'Planning context' });
  const dd = (label: string) => within(panel).getByText(label).closest('div')!.querySelector('dd')!.textContent;
  expect(dd('Classes')).toBe('24');
  expect(dd('Artifact')).toBe('petclinic.jar');
  expect(dd('Class coverage')).toBe('75.0% (3 of 4)');
  expect(dd('Runtime traces')).toBe('41 traces (one per request or job)');
  expect(dd('Entry-point coverage')).toBe('not measured: Raw method evidence expired');
  expect(dd('Domain review')).toBe('not measured: no domain review is recorded for this version');
});

it('lists the runtime sessions with ids and windows and states what the plan does and does not use', async () => {
  mount(data());
  const panel = await screen.findByRole('region', { name: 'Planning context' });
  const row = within(panel).getByText('s-1').closest('tr')!;
  expect(within(row).getByText('Smoke run (LOCAL)')).toBeTruthy();
  expect(within(row).getByText('2026-10-20T08:00:00Z to 2026-10-20T08:30:00Z')).toBeTruthy();
  expect(within(row).getByText('410')).toBeTruthy();
  expect(within(panel).getByText('Runtime coverage: 75.0% of classes (3 of 4).')).toBeTruthy();
  expect(within(panel).getByText('Behavioral contract tests: none are recorded for this version.')).toBeTruthy();
  expect(within(panel).getByText('No earlier architecture version exists for this application, so nothing can be compared.')).toBeTruthy();
});

it('shows a recorded domain review with its author and reason', async () => {
  mount(data({ review: { domain_review: { value: true, actor: 'alok', reason: 'Architect review' } } }));
  const panel = await screen.findByRole('region', { name: 'Planning context' });
  expect(within(panel).getByText('Domain review').closest('div')!.querySelector('dd')!.textContent).toBe('recorded by alok: Architect review');
});

it('with no runtime session says so instead of listing an empty table', async () => {
  mount(data({ runtime: { sessions: [], session_count: 0, traces: missing('no runtime session is attached to this version'), class_coverage: missing('no runtime session is attached to this version'), entry_point_coverage: missing('no runtime session is attached to this version'), method_coverage: missing('no runtime session is attached to this version') } }));
  const panel = await screen.findByRole('region', { name: 'Planning context' });
  expect(within(panel).getByText('No runtime session is attached to this version.')).toBeTruthy();
  expect(within(panel).getByText('Class coverage').closest('div')!.querySelector('dd')!.textContent).toBe('not measured: no runtime session is attached to this version');
});
