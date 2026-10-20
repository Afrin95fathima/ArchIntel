"""Self-contained HTML (inline CSS and SVG, no scripts) for the report model."""
from __future__ import annotations

from html import escape
import math

PALETTE = dict(ink='#1d2b36', muted='#5a6b78', line='#c9d3da', pale='#eef4f7', teal='#0b7a6b', blue='#2a5d9f', red='#b3261e', green='#1b7a3d', gold='#8a5a00')
MARKERS = {'arrow-muted': PALETTE['muted'], 'arrow-green': PALETTE['green'], 'arrow-red': PALETTE['red'], 'arrow-blue': PALETTE['blue']}


def marker_defs(prefix):
    return '<defs>' + ''.join(f'<marker id="{prefix}-{mid}" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="9" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="{colour}"/></marker>' for mid, colour in MARKERS.items()) + '</defs>'


LAYER_FILL = {'PRESENTATION': '#e3eef9', 'SERVICE': '#e1f3ee', 'DOMAIN': '#fdf1d6', 'DATA_ACCESS': '#efe6f7', 'INTEGRATION': '#e8edf1', 'SUPPORT': '#f1f1f1'}


def _e(value):
    return escape(str(value), quote=True)


def hld_svg(data: dict) -> str:
    layers, edges, externals, entries = data.get('layers', []), data.get('edges', []), data.get('externals', []), data.get('entry_points', [])
    width, left, box_w, box_h, gap = 900, 170, 440, 54, 40
    top = 84 if entries else 20
    height = top + max(len(layers) * (box_h + gap), len(externals) * 74) + 40
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="hld-title hld-desc" viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px">',
             '<title id="hld-title">High-level architecture</title>',
             f'<desc id="hld-desc">{len(layers)} layers, {len(edges)} dependency groups between layers or to external systems, {len(externals)} external systems, {sum(e["count"] for e in entries)} entry points.</desc>',
             marker_defs('hld')]
    boxes = {}
    for n, e in enumerate(entries):
        w = (width - 80) / max(1, len(entries)) - 10
        x = 40 + n * (w + 10)
        parts.append(f'<rect x="{x:.0f}" y="12" width="{w:.0f}" height="46" rx="6" fill="{PALETTE["pale"]}" stroke="{PALETTE["line"]}"/>'
                     f'<text x="{x + w / 2:.0f}" y="32" text-anchor="middle" font-size="12" font-weight="600" fill="{PALETTE["ink"]}">{_e(e["label"])}</text>'
                     f'<text x="{x + w / 2:.0f}" y="48" text-anchor="middle" font-size="11" fill="{PALETTE["muted"]}">{e["count"]} entry point(s)</text>')
    for i, l in enumerate(layers):
        y = top + i * (box_h + gap)
        boxes[l['id']] = (left, y, box_w, box_h)
        roles = ', '.join(f'{k} {v}' for k, v in sorted(l['roles'].items())[:4])
        parts.append(f'<rect x="{left}" y="{y}" width="{box_w}" height="{box_h}" rx="8" fill="{LAYER_FILL.get(l["layer"], "#f1f1f1")}" stroke="{PALETTE["line"]}"/>'
                     f'<text x="{left + 12}" y="{y + 22}" font-size="13" font-weight="700" fill="{PALETTE["ink"]}">{_e(l["label"])}</text>'
                     f'<text x="{left + 12}" y="{y + 40}" font-size="11" fill="{PALETTE["muted"]}">{l["class_count"]} classes in {l["package_count"]} package(s). {_e(roles)}</text>')
    ext_x, ext_w = left + box_w + 90, width - (left + box_w + 90) - 20
    for n, ext in enumerate(externals):
        y = top + n * 74
        boxes[ext['id']] = (ext_x, y, ext_w, 50)
        parts.append(f'<rect x="{ext_x}" y="{y}" width="{ext_w}" height="50" rx="6" fill="#ffffff" stroke="{PALETTE["muted"]}" stroke-dasharray="4 3"/>'
                     f'<text x="{ext_x + ext_w / 2:.0f}" y="{y + 22}" text-anchor="middle" font-size="12" font-weight="600" fill="{PALETTE["ink"]}">{_e(ext["label"])}</text>'
                     f'<text x="{ext_x + ext_w / 2:.0f}" y="{y + 38}" text-anchor="middle" font-size="11" fill="{PALETTE["muted"]}">{ext["class_count"]} classes</text>')
    lane = 0
    for e in edges:
        if e['source'] not in boxes or e['target'] not in boxes:
            continue
        sx, sy, sw, sh = boxes[e['source']]
        tx, ty, tw, th = boxes[e['target']]
        colour = PALETTE['red'] if e.get('against_layering') else PALETTE['green'] if e.get('observed') else PALETTE['muted']
        dash = '' if e.get('observed') or e.get('against_layering') else ' stroke-dasharray="5 4"'
        marker = 'arrow-red' if e.get('against_layering') else 'arrow-green' if e.get('observed') else 'arrow-muted'
        if e['target'].startswith('external'):
            x1, y1, x2, y2 = sx + sw, sy + sh / 2, tx, ty + th / 2
            parts.append(f'<path d="M{x1} {y1:.0f} L{x2} {y2:.0f}" stroke="{colour}" fill="none" stroke-width="1.4"{dash} marker-end="url(#hld-{marker})"/>')
            parts.append(f'<text x="{x1 + (x2 - x1) * .35:.0f}" y="{y1 + (y2 - y1) * .35 - 3:.0f}" font-size="10" fill="{colour}">{e["class_pairs"]}</text>')
            continue
        lane += 1
        gx = left - 12 - (lane % 7) * 16
        y1, y2 = sy + sh / 2, ty + th / 2
        parts.append(f'<path d="M{sx} {y1:.0f} H{gx} V{y2:.0f} H{tx - 2}" stroke="{colour}" fill="none" stroke-width="1.4"{dash} marker-end="url(#hld-{marker})"/>')
        parts.append(f'<text x="{gx - 12}" y="{(y1 + y2) / 2:.0f}" font-size="10" fill="{colour}">{e["class_pairs"]}</text>')
    parts.append(f'<text x="12" y="{height - 8}" font-size="10" fill="{PALETTE["muted"]}">Arrows point from the depending layer to what it uses; the number is distinct class pairs. Green: also seen at runtime. Dashed grey: code only. Red: against the layering.</text></svg>')
    return ''.join(parts)


def domain_map_svg(matrix: dict) -> str:
    domains, rows = matrix.get('domain_ids', []), matrix.get('rows', [])
    size, radius = 520, 190
    cx = cy = size / 2
    pos = {d['id']: (cx + radius * math.cos(2 * math.pi * i / max(1, len(domains)) - math.pi / 2), cy + radius * math.sin(2 * math.pi * i / max(1, len(domains)) - math.pi / 2)) for i, d in enumerate(domains)}
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="map-title map-desc" viewBox="0 0 {size} {size}" width="100%" style="max-width:{size}px">',
             '<title id="map-title">Domain map</title>', f'<desc id="map-desc">{len(domains)} candidate domains and {len(rows)} directed dependencies between them.</desc>',
             marker_defs('map')]
    maximum = max((r['edge_count'] for r in rows), default=1)
    for r in rows:
        if r['source_domain_id'] not in pos or r['target_domain_id'] not in pos:
            continue
        x1, y1 = pos[r['source_domain_id']]
        x2, y2 = pos[r['target_domain_id']]
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy) or 1
        sx, sy, ex, ey = x1 + dx / length * 46, y1 + dy / length * 22, x2 - dx / length * 46, y2 - dy / length * 22
        parts.append(f'<path d="M{sx:.0f} {sy:.0f} L{ex:.0f} {ey:.0f}" stroke="{PALETTE["blue"]}" stroke-width="{1 + 3 * r["edge_count"] / maximum:.1f}" fill="none" marker-end="url(#map-arrow-blue)" opacity="0.8"/>')
        parts.append(f'<text x="{(sx + ex) / 2 + 3:.0f}" y="{(sy + ey) / 2 - 3:.0f}" font-size="11" font-weight="600" fill="{PALETTE["red"]}">{r["edge_count"]}</text>')
    for d in domains:
        x, y = pos[d['id']]
        words = d['name'].split(' ')
        half = max(1, len(words) // 2) if len(d['name']) > 14 else len(words)
        lines = [' '.join(words[:half]), ' '.join(words[half:])] if half < len(words) else [d['name']]
        parts.append(f'<rect x="{x - 52:.0f}" y="{y - 22:.0f}" width="104" height="44" rx="8" fill="#e1f3ee" stroke="{PALETTE["teal"]}"/>')
        for n, text in enumerate(lines):
            parts.append(f'<text x="{x:.0f}" y="{y + (4 if len(lines) == 1 else -2 + 13 * n):.0f}" text-anchor="middle" font-size="11" font-weight="600" fill="{PALETTE["ink"]}">{_e(text[:20])}</text>')
    if not rows:
        parts.append(f'<text x="{cx}" y="{cy}" text-anchor="middle" font-size="12" fill="{PALETTE["muted"]}">No cross-domain dependency was found.</text>')
    parts.append('</svg>')
    return ''.join(parts)


CSS = f"""
body{{font:14px/1.5 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:{PALETTE['ink']};margin:0;background:#fff}}
main{{max-width:960px;margin:0 auto;padding:24px 20px 60px}}
header.cover{{border-bottom:4px solid {PALETTE['teal']};padding:8px 0 16px;margin-bottom:24px}}
header.cover h1{{margin:4px 0;font-size:28px}} .eyebrow{{font-size:12px;letter-spacing:.08em;color:{PALETTE['teal']};font-weight:700}}
.meta{{color:{PALETTE['muted']};font-size:12px}} .notice{{background:#fff7e0;border-left:4px solid #d99a1b;padding:8px 12px;margin:12px 0;font-size:13px}}
nav.toc ol{{columns:2;margin:8px 0 24px}} section.report-section{{margin:32px 0;break-inside:auto}}
section.report-section>h2{{background:{PALETTE['pale']};border-left:5px solid {PALETTE['teal']};padding:8px 12px;font-size:20px;margin:0 0 12px}}
.plain{{background:#f3faf8;border:1px solid #cfe7e1;border-radius:6px;padding:10px 14px;margin-bottom:12px}} .plain h3,.technical>h3{{font-size:13px;text-transform:uppercase;letter-spacing:.05em;margin:0 0 6px;color:{PALETTE['teal']}}}
.plain p{{margin:6px 0}} table{{border-collapse:collapse;width:100%;margin:8px 0 14px;font-size:12px}} caption{{text-align:left;font-weight:700;padding:6px 0;font-size:13px}}
th,td{{border:1px solid {PALETTE['line']};padding:4px 6px;vertical-align:top;text-align:left;overflow-wrap:anywhere}} th{{background:{PALETTE['pale']}}}
.note{{font-size:12px;color:{PALETTE['muted']}}} ul.items{{margin:4px 0 12px 18px;padding:0;font-size:13px}} figure{{margin:12px 0}} figcaption{{font-size:12px;color:{PALETTE['muted']}}}
footer{{border-top:1px solid {PALETTE['line']};margin-top:40px;padding-top:12px;color:{PALETTE['muted']};font-size:12px}}
@media print{{main{{max-width:none;padding:0}} section.report-section{{page-break-before:always}} header.cover+nav+section.report-section{{page-break-before:auto}} th{{background:#eee!important}}}}
"""


def _block(block: dict) -> str:
    kind = block['type']
    if kind == 'table':
        head = ''.join(f'<th scope="col">{_e(c)}</th>' for c in block['columns'])
        body = ''.join('<tr>' + ''.join(f'<td>{_e(c)}</td>' for c in row) + '</tr>' for row in block['rows']) or f'<tr><td colspan="{len(block["columns"])}">none</td></tr>'
        return f'<table><caption>{_e(block["caption"])}</caption><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>' + (f'<p class="note">{_e(block["note"])}</p>' if block.get('note') else '')
    if kind == 'list':
        return f'<h4>{_e(block["title"])}</h4><ul class="items">' + ''.join(f'<li>{_e(i)}</li>' for i in block['items']) + '</ul>'
    if kind == 'hld':
        return f'<figure>{hld_svg(block["data"])}<figcaption>High-level architecture: layers, entry points and external systems detected in the code.</figcaption></figure>'
    if kind == 'domain_map':
        return f'<figure>{domain_map_svg(block["data"])}<figcaption>Domain map: each arrow counts class-level dependency edges from one candidate domain to another.</figcaption></figure>'
    return f'<p>{_e(block.get("text", ""))}</p>'


def to_html(report: dict) -> str:
    meta = report['meta']
    toc = ''.join(f'<li><a href="#{_e(s["id"])}">{_e(s["title"])}</a></li>' for s in report['sections'])
    sections = []
    for s in report['sections']:
        plain = ''.join(f'<p>{_e(sentence)}</p>' for sentence in s['plain'])
        sections.append(f'<section class="report-section" id="{_e(s["id"])}" aria-labelledby="h-{_e(s["id"])}"><h2 id="h-{_e(s["id"])}">{s["number"]}. {_e(s["title"])}</h2>'
                        f'<div class="plain"><h3>In plain terms</h3>{plain}</div><div class="technical"><h3>Technical detail</h3>{"".join(_block(b) for b in s["technical"])}</div></section>')
    facts = ''.join(f'<tr><td>{_e(f["label"])}</td><td>{_e(f.get("text", f["value"]))}{_e(f["unit"])}</td><td>{_e(f["source"])}</td></tr>' for f in report['facts'])
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_e(meta["application"])} modernization report</title><style>{CSS}</style></head>'
            f'<body><main><header class="cover"><div class="eyebrow">ARCHINTEL | ARCHITECTURE INTELLIGENCE</div><h1>{_e(meta["application"])}: modernization report</h1>'
            f'<div class="meta">Artifact {_e(meta["artifact"])} | generated {_e(meta["generated_at"])} | analysis {_e(meta["analysis_id"])} | architecture version {_e(meta["version_id"])} | proposal {_e(meta["proposal_id"])}</div>'
            f'<div class="notice">{_e(meta["notice"])}</div></header><nav class="toc" aria-label="Contents"><ol>{toc}</ol></nav>{"".join(sections)}'
            f'<section class="report-section" id="facts"><h2>Numbers used in the plain-terms text</h2><table><thead><tr><th>Number</th><th>Value</th><th>Source</th></tr></thead><tbody>{facts}</tbody></table></section>'
            f'<footer>Generated by ArchIntel from the analysis, runtime evidence and proposal named above. Every figure comes from the same data the application shows.</footer></main></body></html>')
