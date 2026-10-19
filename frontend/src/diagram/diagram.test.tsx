import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { HighLevel, SequenceView } from './ApplicationArchitecture';
import { layoutHld, hldMermaid, type HldData } from './hld';
import { layoutLld, layoutSequence, type LldData, type Seq } from './lld';
import { jpegToPdf } from './exportUtils';
import hld from '../insight/fixtures/petclinic.hld.json';
import lld from '../insight/fixtures/petclinic.lld.json';
import seq from '../insight/fixtures/petclinic.sequence.json';
import node from '../insight/fixtures/petclinic.node.json';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const wrap = (el: React.ReactNode) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{el}</QueryClientProvider>);

it('lays layers out top to bottom with externals last, and routes every edge', () => {
  const l = layoutHld(hld as unknown as HldData, new Set());
  const ys = l.boxes.filter(b => b.kind === 'layer').map(b => b.y);
  expect(ys).toEqual([...ys].sort((a, b) => a - b));
  expect(l.boxes.at(-1)!.kind).toBe('external');
  expect(l.boxes.find(b => b.kind === 'entry')!.title).toBe('17 http endpoints');
  expect(l.routes.length).toBe(hld.edges.length);
  expect(l.routes.every(r => r.d.startsWith('M'))).toBe(true);
});

it('expanding a layer adds package chips and height', () => {
  const closed = layoutHld(hld as unknown as HldData, new Set());
  const open = layoutHld(hld as unknown as HldData, new Set(['layer:DOMAIN']));
  expect(open.height).toBeGreaterThan(closed.height);
  expect(open.boxes.find(b => b.id === 'layer:DOMAIN')!.chips.length).toBeGreaterThan(0);
});

it('exports Mermaid text as a secondary format', () => {
  const text = hldMermaid(hld as unknown as HldData);
  expect(text.startsWith('flowchart TD')).toBe(true);
  expect(text).toContain('layer_PRESENTATION -.->|"5 dependencies"| layer_DATA_ACCESS');
});

it('writes a structurally valid single-page PDF around a JPEG', () => {
  const pdf = new TextDecoder('latin1').decode(jpegToPdf(new Uint8Array([0xff, 0xd8, 0xff, 0xd9]), 10, 10, 300, 200));
  expect(pdf.startsWith('%PDF-1.4')).toBe(true);
  expect(pdf).toContain('/MediaBox [0 0 300 200]');
  expect(pdf).toContain('/Filter /DCTDecode');
  const xref = Number(/startxref\n(\d+)/.exec(pdf)![1]);
  expect(pdf.slice(xref, xref + 4)).toBe('xref');
});

it('lays classes out by layer and sequence messages in order', () => {
  const l = layoutLld(lld as unknown as LldData);
  expect(l.boxes.length).toBe(11);
  expect(l.tables.map(t => t.table).sort()).toEqual(['owners', 'pets', 'types', 'visits']);
  const s = layoutSequence(seq as unknown as Seq);
  expect(s.messages.map(m => m.y)).toEqual([...s.messages.map(m => m.y)].sort((a, b) => a - b));
});

it('HLD boxes and arrows open the shared detail panel', async () => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: string) => ({ ok: true, json: async () => url.includes('/diagram/hld') ? hld : url.includes('/connection') ? { explanation: '5 class-to-class dependencies', pairs: [], references: [] } : { ...node, name: url.includes('layer%3APRESENTATION') ? 'Layer detail' : node.name } })));
  wrap(<HighLevel analysisId="a1" sessions="" onOpen={() => {}} />);
  await waitFor(() => expect(screen.getByRole('img', { name: 'High-level architecture diagram' })).toBeTruthy());
  expect(screen.getByText('How to read this diagram')).toBeTruthy();
  expect(screen.getByText('Legend')).toBeTruthy();
  fireEvent.click(screen.getByText('Presentation (controllers, servlets, filters)'));
  await waitFor(() => expect(screen.getByRole('complementary', { name: /Details for/ })).toBeTruthy());
  const fetched = (fetch as unknown as { mock: { calls: string[][] } }).mock.calls.map(c => c[0]);
  expect(fetched.some(u => u.includes('node?id=layer%3APRESENTATION'))).toBe(true);
});

it('labels a static sequence as not observed', () => {
  wrap(<SequenceView seq={seq as unknown as Seq} />);
  expect(screen.getByText('Static (not observed)')).toBeTruthy();
  expect(screen.getByText(/not what was observed/)).toBeTruthy();
});
