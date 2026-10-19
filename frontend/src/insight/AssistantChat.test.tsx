import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { AssistantChat } from './AssistantChat';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const lines = (events: unknown[]) => events.map(e => JSON.stringify(e)).join('\n') + '\n';

it('streams tool use and cited sentences, labelling the answer as not model-generated', async () => {
  const body = lines([{ type: 'start', turn_id: 't1' }, { type: 'tool_call', tool: 'get_entry_points', args: { name: '', text: 'POST /owners/new' } }, { type: 'tool_result', tool: 'get_entry_points', ok: true, evidence: [] },
    { type: 'sentence', text: 'POST /owners/new is handled by OwnerController.processCreationForm().', cites: ['entry:abc', 'class:p.OwnerController'] },
    { type: 'done', answer: { turn_id: 't1', status: 'ANSWERED', mode: 'LOCAL_EVIDENCE', ai_generated: false, sentences: [], removed: [], tool_calls: [], label: 'Deterministic answer composed from the analysis; no model was used.', gateway: { reason: 'MODEL_DISABLED' } } }]);
  const fetchMock = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => init?.method === 'POST'
    ? { ok: true, body: undefined, text: async () => body, json: async () => ({}) }
    : { ok: true, json: async () => ({ messages: [] }) });
  vi.stubGlobal('fetch', fetchMock);
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><AssistantChat analysisId="a1" /></QueryClientProvider>);
  fireEvent.change(screen.getByLabelText('Ask an architecture question'), { target: { value: 'Which controller handles POST /owners/new?' } });
  fireEvent.click(screen.getByLabelText('Send question'));
  expect(await screen.findByText(/handled by OwnerController.processCreationForm/)).toBeTruthy();
  await waitFor(() => expect(screen.getByText('FROM THE ANALYSIS · NO MODEL')).toBeTruthy());
  expect(screen.getByLabelText('Tools used').textContent).toContain('get_entry_points(POST /owners/new)');
  expect(screen.getByRole('button', { name: 'OwnerController' })).toBeTruthy();
  expect(screen.getByText(/Model not used: model disabled/)).toBeTruthy();
  const post = fetchMock.mock.calls.find(c => c[1]?.method === 'POST')!;
  expect(post[0]).toBe('/api/v1/analyses/a1/insight/assistant/chat');
});

it('shows server errors such as the request budget', async () => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: string, init?: RequestInit) => init?.method === 'POST'
    ? { ok: false, status: 429, json: async () => ({ detail: 'Assistant request budget reached (120 per hour). Try again later.' }) }
    : { ok: true, json: async () => ({ messages: [] }) }));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><AssistantChat analysisId="a1" /></QueryClientProvider>);
  fireEvent.change(screen.getByLabelText('Ask an architecture question'), { target: { value: 'How many classes?' } });
  fireEvent.click(screen.getByLabelText('Send question'));
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(screen.getByText(/budget reached/)).toBeTruthy();
});
