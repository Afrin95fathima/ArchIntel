import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { Responsibilities } from './Responsibilities';
import summary from './fixtures/petclinic.responsibilities.json';
import components from './fixtures/petclinic.responsibility-components.json';
import detail from './fixtures/petclinic.responsibility-component.json';
import edgeSummary from './fixtures/edgecases.responsibilities.json';
import edgeComponents from './fixtures/edgecases.responsibility-components.json';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

type Handlers = { summary?: unknown; components?: (url: URL) => unknown; component?: unknown; status?: Record<string, number> };
function mount(handlers: Handlers = {}) {
  const calls: URL[] = [];
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (input: string) => {
    const url = new URL(String(input), 'http://localhost');
    calls.push(url);
    const key = url.pathname.endsWith('/responsibilities') ? 'summary' : url.pathname.endsWith('/components') ? 'components' : url.pathname.endsWith('/component') ? 'component' : 'other';
    if (handlers.status?.[key]) return { ok: false, status: handlers.status[key], json: async () => ({ detail: 'The analysis service could not be reached.' }) };
    const body = key === 'summary' ? handlers.summary ?? summary : key === 'components' ? (handlers.components ? handlers.components(url) : components) : key === 'component' ? handlers.component ?? detail : {};
    return { ok: true, status: 200, json: async () => body };
  }));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><Responsibilities analysisId="a1" /></QueryClientProvider>);
  return calls;
}
const page = (total: number, items = components.items) => ({ ...components, items, total, offset: 0, limit: 25 });

it('shows how many classes fall in each primary classification and the shared and risky parts', async () => {
  mount();
  await screen.findByText(/classes analyzed with rules/);
  const by = summary.summary.by_primary as Record<string, number>;
  for (const [name, count] of [['functional', by.FUNCTIONAL], ['functional support', by.FUNCTIONAL_SUPPORT], ['mixed', by.MIXED], ['non functional', by.NON_FUNCTIONAL]] as const) {
    const label = screen.getAllByText(name, { selector: 'span' }).find(el => el.closest('article'))!;
    expect(within(label.closest('article') as HTMLElement).getByText(String(count))).toBeTruthy();
  }
  expect(screen.getByText(/risk indicators \(\d+ high, \d+ medium\)/)).toBeTruthy();
  expect(screen.getByText(/Confidence levels are an ordinal heuristic, not a calibrated probability/)).toBeTruthy();
});

it('lists every class with its classification, candidate domain, labelled responsibilities and counts', async () => {
  mount();
  const row = (await screen.findByRole('button', { name: 'OwnerController' })).closest('tr') as HTMLElement;
  expect(within(row).getByText('mixed')).toBeTruthy();                        // a mixed-responsibility class is represented as such
  expect(within(row).getByText('Security')).toBeTruthy();                     // detected: no suffix
  expect(within(row).getByText(/Testability \(inferred\)/)).toBeTruthy();     // inferred: marked in the text, not only by colour
  expect(within(row).getByText('Owner Visit')).toBeTruthy();
  expect(screen.getAllByRole('row').length).toBe(components.items.length + 1);
});

it('sends each filter to the API and returns to the first page', async () => {
  const calls = mount({ components: () => page(60) });
  await screen.findByRole('button', { name: 'OwnerController' });
  fireEvent.click(screen.getByRole('button', { name: 'Next' }));
  await waitFor(() => expect(calls.some(u => u.searchParams.get('offset') === '25')).toBe(true));
  fireEvent.change(screen.getByLabelText('Non-functional concern'), { target: { value: 'SECURITY' } });
  await waitFor(() => expect(calls.some(u => u.searchParams.get('concern') === 'SECURITY' && u.searchParams.get('offset') === '0')).toBe(true));
  fireEvent.change(screen.getByLabelText('Primary classification'), { target: { value: 'MIXED' } });
  fireEvent.change(screen.getByLabelText('Detection status'), { target: { value: 'DETECTED' } });
  fireEvent.change(screen.getByLabelText('Confidence'), { target: { value: 'HIGH' } });
  fireEvent.change(screen.getByLabelText('Functional responsibility'), { target: { value: 'API_AND_APPLICATION_ENTRY' } });
  fireEvent.change(screen.getByLabelText('Business capability'), { target: { value: summary.capabilities[0].id } });
  fireEvent.change(screen.getByLabelText('Search class'), { target: { value: 'owner' } });
  await waitFor(() => {
    const last = calls[calls.length - 1].searchParams;
    expect([last.get('primary'), last.get('status'), last.get('confidence'), last.get('functional'), last.get('concern'), last.get('capability'), last.get('q'), last.get('offset')])
      .toEqual(['MIXED', 'DETECTED', 'HIGH', 'API_AND_APPLICATION_ENTRY', 'SECURITY', summary.capabilities[0].id, 'owner', '0']);
  });
});

it('explains an empty filter result using the number of analyzed classes', async () => {
  mount({ components: () => page(0, []) });
  expect(await screen.findByText(/No class matches these filters among the 24 analyzed classes/)).toBeTruthy();
});

it('opens a class and shows its evidence with line numbers, the derived path note, confidence wording and what the label does not prove', async () => {
  mount();
  fireEvent.click(await screen.findByRole('button', { name: 'OwnerController' }));
  const panel = await screen.findByLabelText('Details of OwnerController');
  expect(await within(panel).findByText(/WebDataBinder\.setDisallowedFields\(\)/)).toBeTruthy();
  expect(within(panel).getAllByText('DETECTED').length).toBeGreaterThan(0);
  expect(within(panel).getAllByText(/· line \d+/).length).toBeGreaterThan(0);                                   // call sites carry an exact line
  expect(within(panel).getAllByText(/method body at lines \d+–\d+ \(bytecode does not record where the annotation was written\)/).length).toBeGreaterThan(0);
  expect(within(panel).getAllByText(/confidence \(heuristic\)/).length).toBeGreaterThan(0);
  expect(within(panel).getByText(/path derived from the package and the SourceFile attribute/)).toBeTruthy();
  expect(within(panel).getAllByText(/What this does not prove:/).length).toBeGreaterThan(0);
  expect(within(panel).getByText(/the class's own code runs this concern/)).toBeTruthy();
  expect(within(panel).getByText('AI: explain this class in words (optional)')).toBeTruthy();
  expect(within(panel).getByRole('button', { name: 'Generate' })).toBeTruthy();
});

it('shows an uncertain class as uncertain with the reason instead of forcing a label', async () => {
  const uncertain = edgeComponents.items.find(i => i.primary_classification === 'UNCERTAIN')!;
  const uncertainDetail = { ...detail, simple_name: uncertain.simple_name, fqn: uncertain.fqn, primary_classification: 'UNCERTAIN', classification_reasons: [], functional_responsibilities: [], non_functional_responsibilities: [],
    uncertainties: ['No responsibility evidence was found in the bytecode of this class.'], risks: [], methods: [], dependency_details: [], dependent_details: [], cross_cutting: [], capability_implications: [] };
  mount({ summary: edgeSummary, components: () => ({ ...edgeComponents, items: [uncertain], total: 1 }), component: uncertainDetail });
  fireEvent.click(await screen.findByRole('button', { name: uncertain.simple_name }));
  const panel = await screen.findByLabelText(`Details of ${uncertain.simple_name}`);
  expect(await within(panel).findByText(/No responsibility evidence was found in the bytecode of this class/)).toBeTruthy();
  expect(within(panel).getAllByText(/None detected in the bytecode of this Java class/).length).toBe(2);
});

it('describes each candidate domain as business, technical or mixed with what that means for modernization', async () => {
  mount();
  fireEvent.click(await screen.findByRole('tab', { name: 'Capabilities' }));
  const technical = summary.capabilities.find(c => c.kind === 'TECHNICAL')!;
  const heading = await screen.findByRole('heading', { name: technical.name });
  expect(within(heading.closest('section') as HTMLElement).getByText('technical')).toBeTruthy();
  expect(within(heading.closest('section') as HTMLElement).getByText(/Keep it as shared configuration or a library, not a service/)).toBeTruthy();
  expect(screen.getAllByText(/Boundary confidence/).length).toBe(summary.capabilities.length);
});

it('lists shared components with library guidance and filters them by kind', async () => {
  mount();
  fireEvent.click(await screen.findByRole('tab', { name: 'Cross-cutting' }));
  expect(await screen.findByText(/it is not turned into a service by default/)).toBeTruthy();
  expect(screen.getAllByText(/library/).length).toBeGreaterThan(0);
  const kinds = [...new Set(summary.cross_cutting.map(c => c.kind))];
  fireEvent.change(screen.getByLabelText('Kind of shared component'), { target: { value: kinds[0] } });
  const expected = summary.cross_cutting.filter(c => c.kind === kinds[0]).length;
  expect(screen.getByText(`${expected} shared`)).toBeTruthy();
});

it('filters risks by category, detection status, severity and runtime need and keeps the consequence marked as inferred', async () => {
  mount();
  fireEvent.click(await screen.findByRole('tab', { name: 'Risks' }));
  expect(await screen.findByText(`${summary.risks.length} risk indicators`)).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Runtime validation'), { target: { value: 'true' } });
  expect(screen.getByText(`${summary.risks.filter(r => r.runtime_validation_required).length} risk indicators`)).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Risk detection status'), { target: { value: 'INFERRED' } });
  fireEvent.change(screen.getByLabelText('Runtime validation'), { target: { value: '' } });
  expect(screen.getByText(`${summary.risks.filter(r => r.detection_status === 'INFERRED').length} risk indicators`)).toBeTruthy();
  fireEvent.click(screen.getAllByRole('button', { expanded: false }).find(b => b.closest('.resp-risks'))!);
  expect(screen.getByText(/Consequence \(inferred, (high|medium|low) confidence\):/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Risk severity'), { target: { value: 'LOW' } });
  expect(screen.getByText(/No risk indicator matches these filters/)).toBeTruthy();
});

it('states the limits: label meanings, detection statuses, what each label does not prove and the evidence check', async () => {
  mount();
  fireEvent.click(await screen.findByRole('tab', { name: 'Method and limits' }));
  expect(await screen.findByText(/Absence of a detected mechanism is not proof/)).toBeTruthy();
  expect(screen.getByText(/A reasoned reading of one or more facts; not established as a fact/)).toBeTruthy();
  expect(screen.getByText(/Security classes or annotations do not show that the application is secure/)).toBeTruthy();
  expect(screen.getByText(/evidence items were checked against the snapshot and 0 were rejected/)).toBeTruthy();
});

it('reports analyses without bytecode facts as unavailable instead of showing empty numbers', async () => {
  mount({ summary: { status: 'NOT_AVAILABLE', reason: 'Bytecode facts are not available for this analysis, so responsibilities cannot be derived from code. Run a new analysis of the same artifact to enable this view.' } });
  expect(await screen.findByText(/Bytecode facts are not available for this analysis/)).toBeTruthy();
  expect(screen.queryByRole('tab', { name: 'Components' })).toBeNull();
});

it('shows a visible error when the summary or the list cannot be loaded', async () => {
  mount({ status: { summary: 503 } });
  expect(await screen.findByText(/The analysis service could not be reached/)).toBeTruthy();
  cleanup();
  mount({ status: { components: 500 } });
  expect(await screen.findByText(/The analysis service could not be reached/)).toBeTruthy();
});
