import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { PlanningWorkspace } from './PlanningWorkspace';

vi.mock('../runtime/RuntimeGraph', () => ({ RuntimeGraph: () => null }));

const decisions = [
  { id: 'd-owners', domain_id: 'dom-owners', kind: 'BREAK_CYCLE_FIRST', action: 'Break the cycle.', blockers: ['CROSS_DOMAIN_CYCLE'], finding_ids: ['f1'], fact_ids: [], evidence_ids: ['e1'] },
  { id: 'd-visits', domain_id: 'dom-visits', kind: 'COLLECT_MORE_EVIDENCE', action: 'Exercise entry points.', blockers: ['RUNTIME_OBSERVATION_GAP'], finding_ids: ['f2'], fact_ids: [], evidence_ids: ['e2'] },
];
const assessment = (id: string, name: string) => ({ domain_id: id, domain_name: name, structural_score: 70, runtime_score: null, combined_score: 70, confidence_score: 40, confidence_label: 'LIMITED', confidence_components: {}, structural_components: {}, runtime_components: {}, readiness_formula: '', confidence_note: '' });
const document = {
  id: 'p1', fingerprint: 'fp', version_id: 'v1', rule_version: 'r', calibration_version: 'c', assessments: [assessment('dom-owners', 'Owners'), assessment('dom-visits', 'Visits')],
  findings: [], decisions, waves: [], target: { strategy: 'MODULAR_MONOLITH', objective: 'o', note: '', components: [], interfaces: [], alternatives: [] },
  validation: { status: 'VALIDATED', scope: 's' }, limitations: [],
};
const reasons = (rule: string, domains: string[]) => ({
  answer: 'unused', decision: { ...decisions[0], fact_ids: [] }, findings: [], decision_rule: { rule_id: 'BREAK_CYCLE_FIRST', action: 'Break the cycle.', blockers: [] },
  reasons: [{ rule_id: rule, severity: 'HIGH', text: 'x', measured: { domains_in_cycle: domains.length }, threshold: { minimum_domains_in_cycle: 2 }, subjects: domains, evidence_ids: ['e1'], fact_count: 0, measured_fields_recorded: true }],
  ai: { status: 'NOT_REQUESTED' },
});

let pending: Record<string, (value: unknown) => void>;
let failing: Set<string>;
beforeEach(() => {
  pending = {}; failing = new Set();
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const json = (body: unknown, ok = true) => ({ ok, status: ok ? 200 : 500, json: async () => body });
    if (url.endsWith('/applications/a1/architecture-versions')) return json([{ id: 'v1', name: 'Version one' }]);
    if (url.endsWith('/architecture-versions/v1/modernization')) return json([{ id: 'p1', strategy: 'MODULAR_MONOLITH', objective: 'o' }]);
    if (url.endsWith('/architecture-versions/v1/modernization/p1')) return json({ id: 'p1', document, context: { state: 'CURRENT' }, reviews: [], projection: { state: 'APPLIED', attempts: 1, error_code: null } });
    if (url.endsWith('/explain') && init?.method === 'POST') {
      const id = JSON.parse(String(init.body)).decision_id as string;
      if (failing.has(id)) return json({ detail: 'Explanation service failed for ' + id }, false);
      return new Promise(resolve => { pending[id] = (body: unknown) => resolve(json(body)); });
    }
    return json({});
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

async function openDecisions() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><PlanningWorkspace applications={[{ id: 'a1', project_id: 'p', name: 'PetClinic', version: '1', source_type: 'JAR' }]} /></QueryClientProvider>);
  fireEvent.click(await screen.findByRole('button', { name: 'Decisions' }));
  return { owners: await screen.findByRole('button', { name: 'Explain why: Owners' }) as HTMLButtonElement, visits: screen.getByRole('button', { name: 'Explain why: Visits' }) as HTMLButtonElement };
}

it('only the clicked button enters the loading state', async () => {
  const { owners, visits } = await openDecisions();
  fireEvent.click(owners);
  await waitFor(() => expect(owners.disabled).toBe(true));
  expect(visits.disabled).toBe(false);
  expect(within(screen.getByRole('article', { name: 'Decision Visits' })).queryByText(/Explaining/)).toBeNull();
  expect(Object.keys(pending)).toEqual(['d-owners']);
});

it('shows the result under the clicked item only, with rule, measured value, threshold, subjects and evidence ids', async () => {
  const { owners } = await openDecisions();
  fireEvent.click(owners);
  await waitFor(() => expect(pending['d-owners']).toBeTruthy());
  pending['d-owners'](reasons('CROSS_DOMAIN_CYCLE', ['Owners', 'Visits']));
  const region = await screen.findByRole('region', { name: 'Explanation: Owners' });
  expect(within(region).getByText(/CROSS_DOMAIN_CYCLE/)).toBeTruthy();
  expect(within(region).getByText('Measured: domains_in_cycle = 2')).toBeTruthy();
  expect(within(region).getByText('Threshold: minimum_domains_in_cycle = 2')).toBeTruthy();
  expect(within(region).getByText(/Owners, Visits/)).toBeTruthy();
  expect(within(region).getByText(/e1/)).toBeTruthy();
  expect(screen.queryByRole('region', { name: 'Explanation: Visits' })).toBeNull();
  expect(within(screen.getByRole('article', { name: 'Decision Visits' })).queryByText(/CROSS_DOMAIN_CYCLE/)).toBeNull();
});

it('two items can hold results at the same time', async () => {
  const { owners, visits } = await openDecisions();
  fireEvent.click(owners); fireEvent.click(visits);
  await waitFor(() => expect(Object.keys(pending).sort()).toEqual(['d-owners', 'd-visits']));
  pending['d-visits'](reasons('LIMITED_OBSERVATION', ['Visits']));
  pending['d-owners'](reasons('CROSS_DOMAIN_CYCLE', ['Owners', 'Visits']));
  expect(within(await screen.findByRole('region', { name: 'Explanation: Visits' })).getByText(/LIMITED_OBSERVATION/)).toBeTruthy();
  expect(within(await screen.findByRole('region', { name: 'Explanation: Owners' })).getByText(/CROSS_DOMAIN_CYCLE/)).toBeTruthy();
});

it('shows a failed request as visible text under that item', async () => {
  failing.add('d-visits');
  const { visits } = await openDecisions();
  fireEvent.click(visits);
  const article = screen.getByRole('article', { name: 'Decision Visits' });
  expect(await within(article).findByText(/Explanation service failed for d-visits/)).toBeTruthy();
  expect(visits.disabled).toBe(false);
});

it('clicking again hides the result, and a third click shows it without another request', async () => {
  const { owners } = await openDecisions();
  fireEvent.click(owners);
  await waitFor(() => expect(pending['d-owners']).toBeTruthy());
  pending['d-owners'](reasons('CROSS_DOMAIN_CYCLE', ['Owners', 'Visits']));
  await screen.findByRole('region', { name: 'Explanation: Owners' });
  fireEvent.click(owners);
  await waitFor(() => expect(screen.queryByRole('region', { name: 'Explanation: Owners' })).toBeNull());
  fireEvent.click(owners);
  expect(await screen.findByRole('region', { name: 'Explanation: Owners' })).toBeTruthy();
  const posts = (fetch as unknown as { mock: { calls: [string, RequestInit?][] } }).mock.calls.filter(([, init]) => init?.method === 'POST');
  expect(posts).toHaveLength(1);
});
