import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AssistantDock } from './AssistantDock';
import { publishAssistantContext } from '../assistantContext';

beforeEach(() => localStorage.clear());
afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.clear(); });
const lines = (events: unknown[]) => events.map(e => JSON.stringify(e)).join('\n') + '\n';
const answer = lines([{ type: 'start', turn_id: 't1' }, { type: 'tool_call', tool: 'get_entry_points', args: { name: '', text: 'POST /owners/new' } },
  { type: 'sentence', text: 'POST /owners/new is handled by OwnerController.processCreationForm().', cites: ['entry:abc', 'class:p.OwnerController'] },
  { type: 'done', answer: { turn_id: 't1', status: 'ANSWERED', mode: 'LOCAL_EVIDENCE', ai_generated: false, sentences: [], removed: [], tool_calls: [], label: 'Deterministic answer composed from the analysis. Model not used: model disabled.', gateway: { reason: 'MODEL_DISABLED' } } }]);
function stub(post: () => unknown = () => ({ ok: true, body: undefined, text: async () => answer, json: async () => ({}) })) {
  const fetchMock = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') return post();
    if (url.includes('/runtime-sessions')) return { ok: true, json: async () => [{ id: 's1', name: 'Smoke run', analysis_id: 'a1' }, { id: 's2', name: 'Other analysis', analysis_id: 'zzz' }] };
    return { ok: true, json: async () => ({ messages: [] }) };
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
type Props = Partial<Parameters<typeof AssistantDock>[0]>;
function mount(props: Props = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const element = (p: Props) => <QueryClientProvider client={client}><AssistantDock analysisId="a1" applicationId="app1" pageLabel="Technical debt" {...p} /></QueryClientProvider>;
  const view = render(element(props));
  return { rerender: (p: Props) => view.rerender(element({ ...props, ...p })) };
}
const ask = (text: string) => { fireEvent.change(screen.getByLabelText('Ask an architecture question'), { target: { value: text } }); fireEvent.click(screen.getByLabelText('Send question')); };
const posts = (fetchMock: ReturnType<typeof stub>) => fetchMock.mock.calls.filter(c => c[1]?.method === 'POST');

it('is a closed button fixed at the corner until opened, then a labelled panel with the input focused', async () => {
  stub(); mount();
  const opener = screen.getByRole('button', { name: 'Open architecture assistant' });
  expect(screen.queryByRole('complementary', { name: 'Architecture assistant' })).toBeNull();
  fireEvent.click(opener);
  const panel = await screen.findByRole('complementary', { name: 'Architecture assistant' });
  expect(within(panel).getByRole('log', { name: 'Assistant conversation' })).toBeTruthy();
  await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText('Ask an architecture question')));
});

it('closes with the close button, with Escape, and toggles with Ctrl+/, returning focus to the opening button', async () => {
  stub(); mount();
  fireEvent.click(screen.getByRole('button', { name: 'Open architecture assistant' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Close assistant' }));
  expect(screen.queryByRole('complementary')).toBeNull();
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Open architecture assistant' }));
  fireEvent.keyDown(window, { key: '/', ctrlKey: true });
  expect(await screen.findByRole('complementary', { name: 'Architecture assistant' })).toBeTruthy();
  fireEvent.keyDown(window, { key: 'Escape' });
  expect(screen.queryByRole('complementary')).toBeNull();
  fireEvent.keyDown(window, { key: '/', metaKey: true });
  expect(await screen.findByRole('complementary')).toBeTruthy();
  fireEvent.keyDown(window, { key: '/', ctrlKey: true });
  expect(screen.queryByRole('complementary')).toBeNull();
});

it('streams tool use and cited sentences and labels the answer as not model-generated', async () => {
  const fetchMock = stub(); mount();
  fireEvent.click(screen.getByRole('button', { name: 'Open architecture assistant' }));
  await screen.findByRole('complementary');
  ask('Which controller handles POST /owners/new?');
  expect(await screen.findByText(/handled by OwnerController.processCreationForm/)).toBeTruthy();
  await waitFor(() => expect(screen.getByText('FROM THE ANALYSIS · NO MODEL')).toBeTruthy());
  expect(screen.getByLabelText('Tools used').textContent).toContain('get_entry_points(POST /owners/new)');
  expect(screen.getByRole('button', { name: 'OwnerController' })).toBeTruthy();
  expect(screen.getByText(/Model not used: model disabled/)).toBeTruthy();
  expect(posts(fetchMock)[0][0]).toBe('/api/v1/analyses/a1/insight/assistant/chat');
});

it('shows server errors such as the request budget as visible text', async () => {
  stub(() => ({ ok: false, status: 429, json: async () => ({ detail: 'Assistant request budget reached (120 per hour). Try again later.' }) })); mount();
  fireEvent.click(screen.getByRole('button', { name: 'Open architecture assistant' }));
  await screen.findByRole('complementary');
  ask('How many classes?');
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(screen.getByText(/budget reached/)).toBeTruthy();
});

it('shows the page and the selected class as a context chip and sends the selection with the question', async () => {
  const fetchMock = stub(); mount({ pageLabel: 'Architecture explorer', selectedNode: 'p.owner.OwnerController' });
  fireEvent.click(screen.getByRole('button', { name: 'Open architecture assistant' }));
  const chip = await screen.findByRole('button', { name: /Assistant context: Architecture explorer, OwnerController/ });
  expect(chip.textContent).toBe('Architecture explorerOwnerControllerstatic only');
  ask('What depends on it?');
  expect(await screen.findByText(/context: OwnerController/)).toBeTruthy();
  expect(JSON.parse(String(posts(fetchMock)[0][1]!.body))).toEqual({ question: 'What depends on it? (about OwnerController)' });
});

it('lets the user change the context to the whole application and pick a runtime session', async () => {
  const fetchMock = stub(); mount({ pageLabel: 'Candidate domains' });
  fireEvent.click(screen.getByRole('button', { name: 'Open architecture assistant' }));
  act(() => publishAssistantContext({ kind: 'domain', id: 'd1', label: 'Owners' }));
  fireEvent.click(await screen.findByRole('button', { name: /Assistant context: Candidate domains, Owners/ }));
  const editor = screen.getByRole('dialog', { name: 'Assistant context' });
  expect(within(editor).getByLabelText(/domain Owners/)).toBeTruthy();
  fireEvent.click(within(editor).getByLabelText(/the whole application/));
  await waitFor(() => expect(screen.getByRole('button', { name: /Assistant context: Candidate domains, whole application/ })).toBeTruthy());
  const select = await within(editor).findByLabelText('Runtime session');
  await waitFor(() => expect(within(select).getAllByRole('option').map(o => o.textContent)).toEqual(['None: static analysis only', 'Smoke run']));
  fireEvent.change(select, { target: { value: 's1' } });
  expect(screen.getByRole('button', { name: /runtime Smoke run/ })).toBeTruthy();
  ask('Is anything unobserved?');
  await screen.findByText(/handled by OwnerController/);
  const call = posts(fetchMock)[0];
  expect(call[0]).toBe('/api/v1/analyses/a1/insight/assistant/chat?runtime_session_ids=s1');
  expect(JSON.parse(String(call[1]!.body))).toEqual({ question: 'Is anything unobserved?' });
  fireEvent.click(within(editor).getByRole('button', { name: 'Reset to this page' }));
  expect(screen.getByRole('button', { name: /Assistant context: Candidate domains, Owners\. Change/ })).toBeTruthy();
});

it('keeps the conversation and the open panel while the page changes underneath it', async () => {
  stub(); const { rerender } = mount({ pageLabel: 'Technical debt' });
  fireEvent.click(screen.getByRole('button', { name: 'Open architecture assistant' }));
  await screen.findByRole('complementary');
  ask('Which controller handles POST /owners/new?');
  await screen.findByText(/handled by OwnerController/);
  rerender({ pageLabel: 'Dependencies', selectedNode: 'p.owner.OwnerRepository' });
  expect(screen.getByText(/handled by OwnerController/)).toBeTruthy();
  expect(screen.getByRole('complementary', { name: 'Architecture assistant' })).toBeTruthy();
  expect(screen.getByRole('button', { name: /Assistant context: Dependencies, OwnerRepository/ })).toBeTruthy();
});

it('remembers that it was open and its width after a reload', async () => {
  stub(); const first = mount();
  fireEvent.click(screen.getByRole('button', { name: 'Open architecture assistant' }));
  const handle = await screen.findByRole('separator', { name: 'Resize assistant' });
  expect(handle.getAttribute('aria-valuenow')).toBe('400');
  fireEvent.keyDown(handle, { key: 'ArrowLeft' });
  fireEvent.keyDown(handle, { key: 'ArrowLeft' });
  expect(handle.getAttribute('aria-valuenow')).toBe('448');
  first.rerender({}); cleanup();
  mount();
  expect(await screen.findByRole('separator', { name: 'Resize assistant' })).toBeTruthy();
  expect(screen.getByRole('separator', { name: 'Resize assistant' }).getAttribute('aria-valuenow')).toBe('448');
});

it('keeps the width inside its limits', async () => {
  stub(); mount();
  fireEvent.click(screen.getByRole('button', { name: 'Open architecture assistant' }));
  const handle = await screen.findByRole('separator', { name: 'Resize assistant' });
  for (let i = 0; i < 40; i++) fireEvent.keyDown(handle, { key: 'ArrowLeft' });
  expect(handle.getAttribute('aria-valuenow')).toBe('760');
  for (let i = 0; i < 60; i++) fireEvent.keyDown(handle, { key: 'ArrowRight' });
  expect(handle.getAttribute('aria-valuenow')).toBe('320');
});

it('explains that an analysis is needed when none is open, and disables the input', async () => {
  stub(); mount({ analysisId: '', pageLabel: 'Applications' });
  fireEvent.click(screen.getByRole('button', { name: 'Open architecture assistant' }));
  expect((await screen.findByRole('note')).textContent).toMatch(/Open an application analysis to ask about it/);
  expect((screen.getByLabelText('Ask an architecture question') as HTMLInputElement).disabled).toBe(true);
});
