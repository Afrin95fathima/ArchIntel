/** Client-side export of a rendered SVG to SVG, PNG and PDF files. No network, no third-party code. */
export function serializeSvg(svg: SVGSVGElement, width: number, height: number): string {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('width', String(width));
  clone.setAttribute('height', String(height));
  clone.setAttribute('viewBox', `0 0 ${width} ${height}`);
  clone.querySelector('[data-viewport]')?.removeAttribute('transform');
  const style = document.createElementNS('http://www.w3.org/2000/svg', 'style');
  style.textContent = 'text{font-family:Inter,Arial,sans-serif;font-size:12px;fill:#26332c}.box{fill:#fff;stroke:#7d8a82;stroke-width:1.5}.edge{fill:none;stroke:#8a9a90;stroke-width:1.6}.edge.observed{stroke:#2d634b}.edge.static{stroke-dasharray:6 4}.edge.reverse{stroke:#af584e}.edge-label{font-size:11px}';
  clone.insertBefore(style, clone.firstChild);
  clone.querySelectorAll('[data-ui]').forEach(node => node.remove());
  return '<?xml version="1.0" encoding="UTF-8"?>\n' + new XMLSerializer().serializeToString(clone);
}

export function download(name: string, data: Blob | string, type: string) {
  const blob = typeof data === 'string' ? new Blob([data], { type }) : data;
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function svgToCanvas(svgText: string, width: number, height: number, scale = 2): Promise<HTMLCanvasElement> {
  const image = new Image();
  const url = URL.createObjectURL(new Blob([svgText], { type: 'image/svg+xml;charset=utf-8' }));
  await new Promise<void>((resolve, reject) => { image.onload = () => resolve(); image.onerror = () => reject(new Error('The diagram could not be rasterised.')); image.src = url; });
  const canvas = document.createElement('canvas');
  canvas.width = width * scale; canvas.height = height * scale;
  const context = canvas.getContext('2d')!;
  context.fillStyle = '#ffffff'; context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  URL.revokeObjectURL(url);
  return canvas;
}

/** Minimal single-page PDF embedding one JPEG (DCTDecode); page sized to the diagram. */
export function jpegToPdf(jpeg: Uint8Array, imageWidth: number, imageHeight: number, pageWidth: number, pageHeight: number): Uint8Array {
  const encoder = new TextEncoder();
  const parts: Uint8Array[] = [];
  const offsets: number[] = [];
  let length = 0;
  const push = (chunk: Uint8Array | string) => { const bytes = typeof chunk === 'string' ? encoder.encode(chunk) : chunk; parts.push(bytes); length += bytes.length; };
  const object = (id: number, body: string, stream?: Uint8Array) => {
    offsets[id] = length;
    push(`${id} 0 obj\n${body}\n`);
    if (stream) { push('stream\n'); push(stream); push('\nendstream\n'); }
    push('endobj\n');
  };
  push('%PDF-1.4\n');
  object(1, '<< /Type /Catalog /Pages 2 0 R >>');
  object(2, '<< /Type /Pages /Kids [3 0 R] /Count 1 >>');
  object(3, `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageWidth} ${pageHeight}] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>`);
  object(4, `<< /Type /XObject /Subtype /Image /Width ${imageWidth} /Height ${imageHeight} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpeg.length} >>`, jpeg);
  const content = `q ${pageWidth} 0 0 ${pageHeight} 0 0 cm /Im0 Do Q`;
  object(5, `<< /Length ${content.length} >>`, encoder.encode(content));
  const xref = length;
  push(`xref\n0 6\n0000000000 65535 f \n${[1, 2, 3, 4, 5].map(i => String(offsets[i]).padStart(10, '0') + ' 00000 n \n').join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`);
  const out = new Uint8Array(length);
  let position = 0;
  parts.forEach(part => { out.set(part, position); position += part.length; });
  return out;
}

export async function exportDiagram(svg: SVGSVGElement, width: number, height: number, name: string, format: 'svg' | 'png' | 'pdf') {
  const text = serializeSvg(svg, width, height);
  if (format === 'svg') return download(name + '.svg', text, 'image/svg+xml');
  const canvas = await svgToCanvas(text, width, height);
  if (format === 'png') return canvas.toBlob(blob => blob && download(name + '.png', blob, 'image/png'));
  const data = atob(canvas.toDataURL('image/jpeg', 0.92).split(',')[1]);
  const bytes = Uint8Array.from(data, c => c.charCodeAt(0));
  return download(name + '.pdf', new Blob([jpegToPdf(bytes, canvas.width, canvas.height, width, height) as BlobPart], { type: 'application/pdf' }), 'application/pdf');
}
