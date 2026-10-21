import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { ArchitectureExplorer, DetailPanel, layeredPositions } from './Explorer';
import graph from './fixtures/petclinic.graph.json';
import node from './fixtures/petclinic.node.json';

vi.mock('cytoscape', () => {
  const chain: Record<string, unknown> = {};
  const api = { on: () => {}, destroy: () => {}, fit: () => {}, elements: () => ({ removeClass: () => {}, not: () => ({ addClass: () => {} }) }), getElementById: () => ({ nonempty: () => false }) };
  Object.assign(chain, api);
  return { default: () => chain };
});

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const wrap = (el: React.ReactNode) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{el}</QueryClientProvider>);

it('places nodes in one row per architecture layer', () => {
  const pos = layeredPositions(graph.nodes as never, graph.layers.map(l => l.id));
  const rows = new Set(Object.values(pos).map(p => p.y));
  expect(rows.size).toBe(new Set(graph.nodes.map(n => n.layer)).size);
});

it('detail panel shows role evidence, entry points, summary and debt for a class', async () => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => ({ ok: true, json: async () => node })));
  wrap(<DetailPanel analysisId="a1" id="x" onNavigate={() => {}} sessions="" />);
  expect(await screen.findByText(/OwnerController is a class whose role is controller/)).toBeTruthy();
  expect(screen.getAllByText(/annotated @org.springframework.stereotype.Controller/).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/GET \/owners\/\{ownerId\}/).length).toBeGreaterThan(0);
  expect(screen.getByText(/No runtime session selected/)).toBeTruthy();
});

it('explorer explains what is shown and what was hidden or aggregated', async () => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: string) => ({ ok: true, json: async () => url.includes('/graph') ? graph : url.includes('/node') ? node : url.includes('/unresolved') ? { categories: [], total: 0 } : { classes: [], packages: [], roles: [], runtime_included: false } })));
  wrap(<ArchitectureExplorer analysisId="a1" />);
  await waitFor(() => expect(screen.getByRole('region', { name: 'What am I looking at?' })).toBeTruthy());
  expect(screen.getByText(/Showing 5 of 5 nodes/)).toBeTruthy();
  expect(screen.getByText(/aggregated into packages/)).toBeTruthy();
  expect(screen.getByText('Legend')).toBeTruthy();
});

it('shows the number of entry points on the application node instead of "none"', async () => {
  const system = { kind: 'SYSTEM', id: 'system', name: 'Application', breadcrumb: [{ id: 'system', label: 'Application' }], summary: 'The application has 5 packages and 25 top-level classes. It declares 18 entry points.', size: { packages: 5, classes: 25 }, entry_points: 18, roles: { ENTITY: 9 } };
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => ({ ok: true, json: async () => system })));
  wrap(<DetailPanel analysisId="a1" id="system" onNavigate={() => {}} sessions="" />);
  expect(await screen.findByText('18 declared across this application')).toBeTruthy();
  expect(screen.queryByText('none')).toBeNull();
});
