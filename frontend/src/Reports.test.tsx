import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { Reports } from './Reports';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const applications = [{ id: 'a1', project_id: 'p', name: 'PetClinic', version: '1', source_type: 'JAR' }];
function mount(htmlStatus = 200) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/report.html')) return { ok: htmlStatus === 200, status: htmlStatus, text: async () => '<html><body><h1>PetClinic: modernization report</h1><p>petclinic.jar has 24 classes</p></body></html>' };
    if (url.endsWith('/applications/a1/architecture-versions')) return { ok: true, json: async () => [{ id: 'v1', name: 'Capture one' }] };
    if (url.endsWith('/architecture-versions/v1/modernization')) return { ok: true, json: async () => [{ id: 'p1', strategy: 'MODULAR_MONOLITH', objective: 'Report' }] };
    return { ok: true, json: async () => ({}) };
  }));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><Reports applications={applications} /></QueryClientProvider>);
}

it('links the PDF, HTML and JSON exports of the selected proposal', async () => {
  mount();
  const pdf = await screen.findByRole('link', { name: /Download PDF/ });
  expect(pdf.getAttribute('href')).toBe('/api/v1/architecture-versions/v1/modernization/p1/report.pdf');
  expect(screen.getByRole('link', { name: /Download HTML/ }).getAttribute('href')).toBe('/api/v1/architecture-versions/v1/modernization/p1/report.html?download=true');
  expect(screen.getByRole('link', { name: /Export digital twin JSON/ }).getAttribute('href')).toBe('/api/v1/architecture-versions/v1/export');
});

it('previews the server-generated report in a sandboxed frame', async () => {
  mount();
  await screen.findByRole('link', { name: /Download PDF/ });          // the version and proposal have loaded
  fireEvent.click(screen.getByRole('button', { name: /Preview report/ }));
  const frame = await screen.findByTitle('Report preview') as HTMLIFrameElement;
  expect(frame.getAttribute('sandbox')).toBe('');
  expect(frame.getAttribute('srcdoc')).toContain('petclinic.jar has 24 classes');
});

it('shows a visible error when the report cannot be generated', async () => {
  mount(500);
  await screen.findByRole('link', { name: /Download PDF/ });
  fireEvent.click(screen.getByRole('button', { name: /Preview report/ }));
  await waitFor(() => expect(screen.getByText('The report could not be generated (HTTP 500).')).toBeTruthy());
});
