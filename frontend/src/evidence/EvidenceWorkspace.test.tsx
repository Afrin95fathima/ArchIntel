import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { EvidenceWorkspace } from './EvidenceWorkspace';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const applications = [{ id: 'a1', project_id: 'p', name: 'PetClinic', version: '1', source_type: 'JAR' }];
const analyses = [{ id: 'an1', application_id: 'a1', status: 'COMPLETED' }];
const version = { id: 'v1', name: 'Architecture observation', analysis_id: 'an1', parent_id: null, fingerprint: 'fp', counts: {}, manifest: { runtime_session_ids: ['s1', 's2'], rule_version: 'evidence-1', derived_assessments: 'x' } };
const twin = { ...version, domains: [{ id: 'd1', name: 'Vet', classes: new Array(10).fill('c') }, { id: 'd2', name: 'Owner Visit', classes: new Array(15).fill('c') }],
  coverage: { classes: { observed: 12, total: 25, percentage: 48, status: 'AVAILABLE' }, entry_points: { observed: 12, total: 17, percentage: 70.59, status: 'AVAILABLE' } }, quality: {}, unknowns: [], projection: { state: 'FAILED', attempts: 1, error_code: 'RuntimeError' } };
const facts = [{ id: 'f1', source: 'org.x.owner.Pet', target: 'org.x.owner.PetType', classification: 'STATIC_ONLY', evidence_ids: ['e1'], note: '' }];

function mount() {
  const calls: URL[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    const url = new URL(String(input), 'http://localhost'); calls.push(url);
    const json = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
    const p = url.pathname;
    if (p.endsWith('/applications/a1/architecture-versions')) return json([version]);
    if (p.endsWith('/applications/a1/runtime-sessions')) return json([]);
    if (p.endsWith('/architecture-versions/v1/twin')) return json(twin);
    if (p.endsWith('/architecture-versions/v1/facts')) {
      const c = url.searchParams.get('classification');
      return json({ items: c && c !== 'STATIC_ONLY' ? [] : facts, total: c === 'STATIC_AND_DYNAMIC' ? 6 : c === 'STATIC_ONLY' ? 20 : c === 'DYNAMIC_ONLY' ? 3 : 29 });
    }
    if (p.endsWith('/facts/f1/provenance')) return json({ fact: facts[0], evidence: [{ id: 'e1', kind: 'STATIC', source: 'org.x.owner.Pet', target: 'org.x.owner.PetType', observation: { field: 'type' }, confidence: 0.9, collector: 'scanner', timestamp: 't', resolved_references: [] }] });
    if (p.endsWith('/architecture-versions/v1/discovery')) return json({ items: [{ id: 'g1', kind: 'ENTRY_POINT', priority: 1, text: 'Exercise PetController.processUpdateForm', state: 'OPEN', gap_state: 'UNOBSERVED', revision: 0, note: '', history: [] }], total: 1 });
    return json({});
  }));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><EvidenceWorkspace applications={applications as never} analyses={analyses as never} /></QueryClientProvider>);
  return calls;
}

it('opens with what the version tells you: real numbers, the plan rule and the next step', async () => {
  mount();
  const panel = await screen.findByLabelText('What this version tells you');
  expect(await within(panel).findByText(/This version describes 25 classes in 2 domains, built from 2 runtime sessions/)).toBeTruthy();
  expect(within(panel).getByText(/reached 12 of 25 classes \(48%\) and 12 of 17 entry points/)).toBeTruthy();
  expect(await within(panel).findByText(/Of 29 dependencies, 6 are confirmed by code and runtime, 20 appear in code only and 3 only at runtime/)).toBeTruthy();
  expect(await within(panel).findByText(/1 open suggestion would add runtime evidence; the highest priority is: Exercise PetController/)).toBeTruthy();
});

it('names the views by the question they answer and keeps the same views reachable', async () => {
  mount();
  const tabs = await screen.findAllByRole('tab');
  expect(tabs.map(t => t.textContent)).toEqual(['What we know', 'What is missing', 'How it connects', 'What it means']);
  fireEvent.click(screen.getByRole('tab', { name: 'What is missing' }));
  expect(await screen.findByText('Priority 1: Entry point')).toBeTruthy();
  fireEvent.click(screen.getByRole('tab', { name: 'What it means' }));
  expect(await screen.findByText('Classes reached')).toBeTruthy();
});

it('filters facts by how they were established, with counts, plain labels and the meaning of the filter', async () => {
  const calls = mount();
  const chips = await screen.findByRole('group', { name: 'Filter facts' });
  await within(chips).findByRole('button', { name: 'In code only (20)' });
  expect(within(chips).getByRole('button', { name: 'All (29)' })).toBeTruthy();
  fireEvent.click(within(chips).getByRole('button', { name: 'In code only (20)' }));
  await waitFor(() => expect(calls.some(u => u.pathname.endsWith('/facts') && u.searchParams.get('classification') === 'STATIC_ONLY' && u.searchParams.get('limit') === '50')).toBe(true));
  expect(await screen.findByText(/does not prove the code is unused/)).toBeTruthy();
  expect(await screen.findByText('owner.Pet → owner.PetType')).toBeTruthy();
});

it('shows a plain summary of the supporting evidence next to the raw records', async () => {
  mount();
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect evidence' }));
  const drawer = await screen.findByLabelText('Evidence for the selected fact');
  expect(within(drawer).getByText(/1 record supports owner\.Pet → owner\.PetType: Static; confidence 0\.90 to 0\.90/)).toBeTruthy();
});

it('collapses the capture form once a version exists but keeps it one click away', async () => {
  mount();
  const form = (await screen.findByText('Capture a new version')).closest('details') as HTMLDetailsElement;
  await screen.findByLabelText('What this version tells you');
  await waitFor(() => expect(form.open).toBe(false));
  fireEvent.click(within(form).getByText('Capture a new version'));
  await waitFor(() => expect(form.open).toBe(true));
  expect(within(form).getByText('Step 1: choose the evidence')).toBeTruthy();
  expect(within(form).getByText('Step 3: preview, then save')).toBeTruthy();
});
