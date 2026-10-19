import { useRef, useState, type ReactNode } from 'react';
import { Download, Minus, Plus, Maximize2 } from 'lucide-react';
import { exportDiagram, download } from './exportUtils';

/** Zoomable, pannable SVG canvas with exports. Children are drawn in diagram coordinates. */
export function DiagramViewer({ width, height, name, label, children, mermaid }: { width: number; height: number; name: string; label: string; children: ReactNode; mermaid?: () => string }) {
  const svg = useRef<SVGSVGElement>(null);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const drag = useRef<{ x: number; y: number } | null>(null);
  const [error, setError] = useState('');
  const zoom = (factor: number) => setView(v => ({ ...v, k: Math.min(4, Math.max(.2, v.k * factor)) }));
  async function save(format: 'svg' | 'png' | 'pdf') {
    setError('');
    try { await exportDiagram(svg.current!, width, height, name, format); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }
  return <div className="diagram-viewer">
    <div className="diagram-tools" role="toolbar" aria-label="Diagram tools">
      <button onClick={() => zoom(1.25)} aria-label="Zoom in"><Plus size={15} /></button><button onClick={() => zoom(.8)} aria-label="Zoom out"><Minus size={15} /></button>
      <button onClick={() => setView({ x: 0, y: 0, k: 1 })} aria-label="Reset view"><Maximize2 size={15} /></button>
      <span className="diagram-tools-spacer" />
      <Download size={15} aria-hidden="true" />
      <button onClick={() => void save('svg')}>SVG</button><button onClick={() => void save('png')}>PNG</button><button onClick={() => void save('pdf')}>PDF</button>
      {mermaid && <button className="secondary" onClick={() => download(name + '.mmd', mermaid(), 'text/plain')} title="Secondary export for documentation tools">Mermaid text</button>}
    </div>
    {error && <p role="alert" className="diagram-error">{error}</p>}
    <svg ref={svg} className="diagram-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}
      onWheel={e => { if (e.ctrlKey || e.metaKey) { e.preventDefault(); zoom(e.deltaY < 0 ? 1.1 : .9); } }}
      onPointerDown={e => { drag.current = { x: e.clientX, y: e.clientY }; (e.currentTarget as Element).setPointerCapture?.(e.pointerId); }}
      onPointerMove={e => { if (drag.current) { const d = drag.current; drag.current = { x: e.clientX, y: e.clientY }; setView(v => ({ ...v, x: v.x + (e.clientX - d.x) / v.k, y: v.y + (e.clientY - d.y) / v.k })); } }}
      onPointerUp={() => { drag.current = null; }}>
      <rect width={width} height={height} fill="#ffffff" />
      <g data-viewport transform={`scale(${view.k}) translate(${view.x},${view.y})`}>{children}</g>
    </svg>
    <p className="fine-print" data-ui>Drag to pan · use the buttons or Ctrl/⌘ + scroll to zoom · click a box or arrow for details.</p>
  </div>;
}
