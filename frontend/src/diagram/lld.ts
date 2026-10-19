/** Pure layout for the low-level diagram of one package and for sequence diagrams. */
export type LldClass = { id: string; name: string; role: string; layer: string; reason: string; methods: number; table: string | null; entry_points: { id: string; text: string; method: string }[]; observed: boolean | null };
export type LldData = { package: string; classes: LldClass[]; edges: { id: string; source: string; target: string; references: number; runtime_calls: number; observed: boolean; label: string }[];
  tables: { id: string; table: string; entity: string; source: string }[]; runtime_tables: { id: string; table: string; operation: string; caller: string; calls: number }[]; entry_points: { id: string; text: string; handler: string }[]; how_to_read: string[]; limitations: string[] };
export type Seq = { status: string; reason?: string; origin: 'STATIC' | 'RUNTIME'; entry: string; participants: { id: string; label: string; role?: string }[]; messages: { order: number; source: string; target: string; label: string; line?: number | null; origin: string; duration_ms?: number; error?: boolean; inherited_from_library?: boolean }[]; note: string };
const ORDER = ['PRESENTATION', 'SERVICE', 'DATA_ACCESS', 'DOMAIN', 'CONFIGURATION', 'SUPPORT'];
const W = 190, GAP_X = 40, GAP_Y = 70;

export function layoutLld(data: LldData) {
  const rows = ORDER.map(layer => data.classes.filter(c => c.layer === layer)).filter(r => r.length);
  const perRow = Math.max(1, ...rows.map(r => Math.min(r.length, 4)));
  const width = Math.max(760, perRow * (W + GAP_X) + GAP_X);
  const boxes: { id: string; x: number; y: number; w: number; h: number; cls: LldClass }[] = [];
  let y = 30;
  const rowLayers: { layer: string; y: number; h: number }[] = [];
  for (const row of rows) {
    let rowHeight = 0, x = 0, line = 0, lineY = y;
    row.forEach((cls, i) => {
      const h = 52 + cls.entry_points.length * 15 + (cls.table ? 15 : 0);
      if (i % 4 === 0 && i > 0) { line += 1; lineY += rowHeight + 24; rowHeight = 0; }
      const inLine = row.slice(line * 4, line * 4 + 4).length;
      x = (width - (inLine * (W + GAP_X) - GAP_X)) / 2 + (i % 4) * (W + GAP_X);
      boxes.push({ id: cls.id, x, y: lineY, w: W, h, cls });
      rowHeight = Math.max(rowHeight, h);
    });
    rowLayers.push({ layer: row[0].layer, y, h: lineY + rowHeight - y });
    y = lineY + rowHeight + GAP_Y;
  }
  const byId = new Map(boxes.map(b => [b.id, b]));
  const max = Math.max(1, ...data.edges.map(e => e.references));
  const routes = data.edges.flatMap(e => {
    const a = byId.get(e.source), b = byId.get(e.target);
    if (!a || !b) return [];
    const sameRow = Math.abs(a.y - b.y) < 5;
    const x1 = a.x + a.w / 2, y1 = sameRow ? a.y + a.h : a.y + (b.y > a.y ? a.h : 0);
    const x2 = b.x + b.w / 2, y2 = sameRow ? b.y + b.h : b.y + (b.y > a.y ? 0 : b.h);
    const bend = sameRow ? 36 : 0;
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2 + bend;
    return [{ id: e.id, d: sameRow ? `M${x1},${y1} Q${mx},${my + 20} ${x2},${y2}` : `M${x1},${y1} L${x2},${y2}`, lx: mx, ly: my, label: e.label, observed: e.observed, weight: 1.2 + (2.8 * e.references) / max }];
  });
  const tableY = y;
  const tables = data.tables.map((t, i) => ({ ...t, x: 30 + (i % 5) * 170, y: tableY + Math.floor(i / 5) * 46, w: 150, h: 34 }));
  const height = tableY + (tables.length ? Math.ceil(tables.length / 5) * 46 + 20 : 0) + 10;
  const tableRoutes = tables.flatMap(t => { const a = byId.get(t.entity); return a ? [{ id: 'tbl-' + t.id, d: `M${a.x + a.w / 2},${a.y + a.h} L${t.x + t.w / 2},${t.y}`, observed: false }] : []; });
  return { width, height: Math.max(height, 160), boxes, routes, tables, tableRoutes, rowLayers };
}

export function layoutSequence(seq: Seq) {
  const colW = Math.max(130, Math.min(190, 900 / Math.max(1, seq.participants.length)));
  const width = Math.max(520, seq.participants.length * colW + 40);
  const xs = new Map(seq.participants.map((p, i) => [p.id, 20 + colW / 2 + i * colW]));
  const top = 70, step = 34;
  const height = top + seq.messages.length * step + 50;
  const messages = seq.messages.map((m, i) => ({ ...m, x1: xs.get(m.source) ?? 0, x2: xs.get(m.target) ?? 0, y: top + 20 + i * step }));
  return { width, height, colW, xs, messages, top };
}
