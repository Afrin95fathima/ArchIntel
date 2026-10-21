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
    if (url.endsWith('/architecture-versions/v1/modernization/context')) return json({ version: { id: { value: 'v1' }, name: { value: 'Version one' }, fingerprint: { value: 'fp' }, captured_at: { value: null, not_measured: 'x' } }, scan: { analysis_id: { value: 'a' }, scan_date: { value: null, not_measured: 'x' }, algorithm_version: { value: null, not_measured: 'x' } },
      artifact: { name: { value: 'a.jar' }, sha256: { value: null, not_measured: 'x' } }, counts: { classes: { value: 1 }, packages: { value: 1 }, domains: { value: 1 }, class_cycle_groups: { value: 0 }, aging_technology_findings: { value: 0 }, entry_points: { value: 0 } },
      runtime: { sessions: [], session_count: 0, traces: { value: null, not_measured: 'x' }, class_coverage: { value: null, not_measured: 'x' }, entry_point_coverage: { value: null, not_measured: 'x' }, method_coverage: { value: null, not_measured: 'x' } },
      review: { domain_review: { value: null, not_measured: 'x' } }, changes: { text: 'none' }, takes_into_account: [], does_not_take_into_account: [] });
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


it('shows the non-functional recommendation next to the domain recommendation and tolerates older recommendations that lack optional lists', async () => {
  const modern = { kind: 'ADDRESS_NONFUNCTIONAL_CONSTRAINT', text: 'Before separating Owners: 3 persistent classes are shared.', affected_classes: ['petclinic.owner.Owner'], dependency_pairs: [], proposed_interface: null, target_domains: [],
    finding_ids: ['f9'], missing_evidence: ['runtime validation (Performance tab or a load test)'] };
  const legacy = { kind: 'COLLECT_DOMAIN_EVIDENCE', text: 'Exercise the entry points of Owners.' };           // saved before these lists existed
  const owners = document.assessments[0] as unknown as { recommendations: unknown[] };
  const before = owners.recommendations;
  owners.recommendations = [legacy, modern];
  try {
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><PlanningWorkspace applications={[{ id: 'a1', project_id: 'p', name: 'PetClinic', version: '1' } as never]} /></QueryClientProvider>);
    fireEvent.click(await screen.findByRole('button', { name: 'Readiness & confidence' }));
    expect(await screen.findByText('ADDRESS NONFUNCTIONAL CONSTRAINT')).toBeTruthy();
    expect(screen.getByText(/Supporting finding IDs: f9/)).toBeTruthy();
    expect(screen.getByText(/Affected classes: petclinic.owner.Owner/)).toBeTruthy();
    expect(screen.getByText(/Missing evidence: runtime validation/)).toBeTruthy();
    expect(screen.getByText('COLLECT DOMAIN EVIDENCE')).toBeTruthy();
    expect(screen.getAllByText(/Supporting finding IDs: none/).length).toBeGreaterThan(0);         // the older recommendation renders instead of crashing the page
    expect(screen.getAllByText(/Affected classes: none identified/).length).toBeGreaterThan(0);
  } finally { owners.recommendations = before; }
});


it('starts on the application of the selected analysis and tells the app when another application is chosen', async () => {
  const apps = [{ id: 'a1', project_id: 'p', name: 'PetClinic', version: '1', source_type: 'JAR' }, { id: 'a2', project_id: 'p', name: 'Northstar', version: '1', source_type: 'JAR' }];
  const seen: string[] = [];
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><PlanningWorkspace applications={apps as never} currentApplicationId="a2" onApplication={id => seen.push(id)} /></QueryClientProvider>);
  const select = await screen.findByLabelText('Planning application') as HTMLSelectElement;
  expect(select.value).toBe('a2');                                         // the application of the selected analysis, not the first in the list
  expect(seen).toEqual(['a2']);
  fireEvent.change(select, { target: { value: 'a1' } });
  await waitFor(() => expect(seen).toEqual(['a2', 'a1']));                 // the workflow strip can now follow the page
});
