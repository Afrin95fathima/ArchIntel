/** Pure layout for the high-level diagram: entry strip, layer rows, external systems. */
export type HldData = { layers: { id: string; layer: string; label: string; plain: string; class_count: number; roles: Record<string, number>; packages: { id: string; count: number }[]; package_count: number }[];
  externals: { id: string; key: string; label: string; class_count: number; evidence: string[]; runtime_calls: number }[];
  entry_points: { id: string; kind: string; count: number; label: string; examples: string[] }[];
  edges: { id: string; source: string; target: string; class_pairs: number; runtime_calls: number; observed: boolean; against_layering: boolean; label: string; explanation: string }[];
  how_to_read: string[]; limitations: string[]; runtime_included: boolean };
export type Box = { id: string; x: number; y: number; w: number; h: number; kind: 'entry' | 'layer' | 'external'; title: string; subtitle: string; chips: { id: string; label: string }[]; hiddenChips: number };
export type Route = { id: string; d: string; lx: number; ly: number; label: string; observed: boolean; reverse: boolean; weight: number };

export const WIDTH = 980;
const LAYER_X = 150, LAYER_W = 680, ROW_GAP = 46, PAD = 30;

export function layoutHld(data: HldData, expanded: Set<string>) {
  const boxes: Box[] = [];
  let y = PAD;
  const entryW = data.entry_points.length ? Math.min(210, (LAYER_W - (data.entry_points.length - 1) * 14) / data.entry_points.length) : 0;
  data.entry_points.forEach((e, i) => boxes.push({ id: e.id, kind: 'entry', x: LAYER_X + i * (entryW + 14), y, w: entryW, h: 54, title: `${e.count} ${e.label}${e.count === 1 ? '' : 's'}`, subtitle: e.examples[0] || '', chips: [], hiddenChips: 0 }));
  if (data.entry_points.length) y += 54 + ROW_GAP;
  for (const layer of data.layers) {
    const open = expanded.has(layer.id);
    const chips = open ? layer.packages.slice(0, 12).map(p => ({ id: p.id, label: `${p.id.split('.').slice(-2).join('.')} (${p.count})` })) : [];
    const rows = Math.ceil(chips.length / 3);
    const h = 66 + (open ? rows * 24 + 10 : 0);
    boxes.push({ id: layer.id, kind: 'layer', x: LAYER_X, y, w: LAYER_W, h, title: layer.label, subtitle: `${layer.class_count} classes · ${Object.entries(layer.roles).map(([k, v]) => `${v} ${k.toLowerCase().replace('_', ' ')}`).join(', ')}`, chips, hiddenChips: open ? Math.max(0, layer.package_count - 12) : 0 });
    y += h + ROW_GAP;
  }
  const extW = data.externals.length ? Math.min(220, (LAYER_W - (data.externals.length - 1) * 14) / data.externals.length) : 0;
  data.externals.forEach((e, i) => boxes.push({ id: e.id, kind: 'external', x: LAYER_X + i * (extW + 14), y, w: extW, h: 54, title: e.label, subtitle: `${e.class_count} classes use it`, chips: [], hiddenChips: 0 }));
  const height = y + (data.externals.length ? 54 : -ROW_GAP) + PAD;
  const byId = new Map(boxes.map(b => [b.id, b]));
  const routes: Route[] = [];
  const maxPairs = Math.max(1, ...data.edges.map(e => e.class_pairs));
  const lanes = new Map<string, number>();
  data.edges.forEach(edge => {
    const a = byId.get(edge.source), b = byId.get(edge.target);
    if (!a || !b) return;
    const down = b.y > a.y, gap = Math.abs(b.y - a.y);
    const adjacent = gap <= Math.max(a.h, b.h) + ROW_GAP + 1;
    const weight = 1.5 + (3.5 * edge.class_pairs) / maxPairs;
    const key = edge.against_layering ? 'L' : 'R';
    const lane = (lanes.get(key) || 0) + (adjacent ? 0 : 1); if (!adjacent) lanes.set(key, lane);
    if (adjacent) {
      const slot = edge.target.startsWith('external:') ? Math.min(b.x + b.w / 2, LAYER_X + LAYER_W - 40) : edge.against_layering ? a.x + 120 : a.x + a.w / 2 + (down ? 0 : 60);
      const x = Math.min(Math.max(slot, a.x + 40), a.x + a.w - 40);
      const y1 = down ? a.y + a.h : a.y, y2 = down ? b.y : b.y + b.h;
      const tx = edge.target.startsWith('external:') ? Math.min(Math.max(b.x + b.w / 2, x), b.x + b.w - 20) : x;
      routes.push({ id: edge.id, d: `M${x},${y1} L${tx},${y2}`, lx: (x + tx) / 2 + 8, ly: (y1 + y2) / 2 + 4, label: edge.label, observed: edge.observed, reverse: edge.against_layering, weight });
    } else {
      const side = edge.against_layering ? -1 : 1;
      const bx = side > 0 ? a.x + a.w + 18 + lane * 22 : a.x - 18 - lane * 22;
      const y1 = a.y + a.h / 2 + (down ? 10 : -10), y2 = b.y + b.h / 2 + (down ? -10 : 10);
      const edgeA = side > 0 ? a.x + a.w : a.x, edgeB = side > 0 ? b.x + b.w : b.x;
      routes.push({ id: edge.id, d: `M${edgeA},${y1} C${bx},${y1} ${bx},${y2} ${edgeB},${y2}`, lx: bx + (side > 0 ? 4 : -4), ly: (y1 + y2) / 2, label: edge.label, observed: edge.observed, reverse: edge.against_layering, weight });
    }
  });
  return { boxes, routes, width: WIDTH, height };
}

export function hldMermaid(data: HldData): string {
  const id = (s: string) => s.replace(/[^A-Za-z0-9]/g, '_');
  const lines = ['flowchart TD'];
  data.entry_points.forEach(e => lines.push(`  ${id(e.id)}(["${e.count} ${e.label}"])`));
  data.layers.forEach(l => lines.push(`  ${id(l.id)}["${l.label}<br/>${l.class_count} classes"]`));
  data.externals.forEach(e => lines.push(`  ${id(e.id)}[("${e.label}")]`));
  data.edges.forEach(e => lines.push(`  ${id(e.source)} ${e.observed ? '==>' : '-.->'}|"${e.label}"| ${id(e.target)}`));
  return lines.join('\n') + '\n';
}
