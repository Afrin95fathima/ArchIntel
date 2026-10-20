"""Small dependency-free PDF renderer for a consolidated modernization report."""
from datetime import datetime, timezone
import textwrap
import unicodedata
import zlib


def _plain(value):
    value = str(value if value is not None else 'Unavailable')
    value = value.replace('\u2192', '->').replace('\u2013', '-').replace('\u2014', '-').replace('\u2022', '*')
    return unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')


def report_lines(report):
    """Line stream for the renderer, from the report model (the same model the HTML renders)."""
    meta = report['meta']
    yield ('cover', meta['application'] + ': modernization report')
    yield ('subtitle', meta['artifact'])
    yield ('meta', f"Generated {meta['generated_at']} | analysis {meta['analysis_id']}")
    yield ('meta', f"Architecture version {meta['version_id']} | proposal {meta['proposal_id']}")
    yield ('notice', meta['notice'])
    for section in report['sections']:
        yield ('page', '')
        yield ('h1', f"{section['number']}. {section['title']}")
        yield ('h2', 'In plain terms')
        for sentence in section['plain']:
            yield ('p', sentence)
        yield ('h2', 'Technical detail')
        for block in section['technical']:
            if block['type'] == 'table':
                yield ('table', block)
            elif block['type'] == 'list':
                yield ('sub', block['title'])
                for item in block['items']:
                    yield ('bullet', item)
            elif block['type'] == 'hld':
                yield ('hld', block['data'])
            elif block['type'] == 'domain_map':
                yield ('domain_graph', block['data'])
                yield ('matrix', block['data'])
    yield ('page', '')
    yield ('h1', 'Numbers used in the plain-terms text')
    yield ('table', dict(caption='Fact table', columns=['Number', 'Value', 'Source'], rows=[[f['label'], str(f.get('text', f['value'])) + f['unit'], f['source']] for f in report['facts']], note=None))


def _escape(text):
    raw = _plain(text).encode('ascii', 'replace')
    out = bytearray()
    for byte in raw:
        if byte in (40, 41, 92):
            out.append(92)
        if byte < 32 or byte > 126:
            out.extend(f'\\{byte:03o}'.encode('ascii'))
        else:
            out.append(byte)
    return bytes(out)


def render_report(report):
    """Render the report model as a PDF with a plain-terms layer and the technical detail beneath it."""
    page_width, page_height = 612, 792
    margin, bottom = 48, 52
    pages, commands = [], []
    y = page_height - 58
    palette = {
        'navy': '0.06 0.16 0.30', 'navy2': '0.10 0.24 0.39',
        'teal': '0.00 0.62 0.57', 'blue': '0.20 0.48 0.76',
        'gold': '0.94 0.62 0.18', 'coral': '0.86 0.31 0.27',
        'ink': '0.12 0.18 0.25', 'muted': '0.34 0.40 0.48',
        'pale': '0.94 0.97 0.99', 'pale_teal': '0.88 0.97 0.95',
        'pale_gold': '1 0.96 0.86', 'line': '0.82 0.87 0.91', 'white': '1 1 1',
    }
    cover_page = False

    def rect(x, y0, width, height, color):
        commands.append(f'{color} rg {x:.1f} {y0:.1f} {width:.1f} {height:.1f} re f'.encode('ascii'))

    def text_at(text, x, y0, size=9, font='F1', color=None):
        color = color or palette['ink']
        commands.append(f'{color} rg'.encode('ascii'))
        commands.append(b'BT /' + font.encode('ascii') + b' ' + str(size).encode('ascii') + b' Tf ' + f'{x:.1f} {y0:.1f} Td ('.encode('ascii') + _escape(text) + b') Tj ET')

    def new_page():
        nonlocal commands, y, cover_page
        if commands:
            pages.append(commands)
        commands = []
        cover_page = False
        y = page_height - 66
        commands.extend([
            f'{palette["navy"]} rg'.encode('ascii'), b'0 748 612 44 re f',
            f'{palette["white"]} rg'.encode('ascii'), b'BT /F2 9 Tf 48 764 Td (ARCHINTEL  |  ARCHITECTURE INTELLIGENCE) Tj ET',
            f'{palette["teal"]} rg'.encode('ascii'), b'0 744 612 4 re f',
        ])

    def line(text, size=10, font='F1', color='0.12 0.18 0.15', gap=14, indent=0):
        nonlocal y
        if y < bottom + gap:
            new_page()
        commands.append(f'{color} rg'.encode('ascii'))
        commands.append(b'BT /' + font.encode('ascii') + b' ' + str(size).encode('ascii') + b' Tf ' + str(margin + indent).encode('ascii') + b' ' + str(y).encode('ascii') + b' Td (' + _escape(text) + b') Tj ET')
        y -= gap

    def wrapped(text, width=94, **options):
        normalized = _plain(text)
        for paragraph in normalized.splitlines() or ['']:
            pieces = textwrap.wrap(paragraph, width=width, break_long_words=True, break_on_hyphens=True) or ['']
            for piece in pieces:
                line(piece, **options)

    def chart(spec):
        nonlocal y
        title, takeaway, source, raw_items = spec
        items = [(str(label), max(0, float(value))) for label, value in raw_items if isinstance(value, (int, float))]
        if not items:
            return
        if y < bottom + min(330, 68 + len(items) * 25):
            new_page()
        line(title, size=12, font='F2', color=palette['navy'], gap=19)
        wrapped(takeaway, width=100, size=8, color=palette['muted'], gap=12)
        max_value = max((value for _, value in items), default=1) or 1
        colors = (palette['teal'], palette['blue'], palette['gold'], palette['coral'])
        for index, (label, value) in enumerate(items):
            if y < bottom + 18:
                new_page()
            row_y = y
            short = label if len(label) <= 27 else label[:24] + '...'
            text_at(short, margin + 3, row_y - 4, 8, 'F1', palette['ink'])
            rect(222, row_y - 8, 277, 8, palette['pale'])
            rect(222, row_y - 8, 277 * value / max_value, 8, colors[index % len(colors)])
            text_at(f'{value:g}', 510, row_y - 4, 8, 'F2', palette['navy'])
            y -= 24
        wrapped('Source: ' + source, width=100, size=7, color=palette['muted'], gap=10)
        y -= 6

    def paired_chart(spec):
        nonlocal y
        title, takeaway, source, raw_items = spec
        items = [(str(name), float(readiness), float(confidence), str(label)) for name, readiness, confidence, label in raw_items
                 if isinstance(readiness, (int,float)) and isinstance(confidence, (int,float))]
        if not items: return
        if y < bottom + min(360, 90 + len(items)*35): new_page()
        line(title,size=12,font='F2',color=palette['navy'],gap=19)
        wrapped(takeaway,width=100,size=8,color=palette['muted'],gap=12)
        for name, readiness, confidence, label in items:
            if y < bottom+35: new_page()
            text_at(name[:27],margin+3,y-4,8,'F1',palette['ink'])
            rect(222,y-8,235,7,palette['pale']); rect(222,y-8,235*max(0,min(100,readiness))/100,7,palette['teal'])
            rect(222,y-19,235,7,palette['pale']); rect(222,y-19,235*max(0,min(100,confidence))/100,7,palette['blue'])
            text_at(f'R {readiness:g} | C {confidence:g}',462,y-4,7,'F2',palette['navy'])
            text_at(label.replace('_',' ')[:18],462,y-16,6,'F1',palette['muted'])
            y-=34
        wrapped('Green = confidence-adjusted readiness; blue = evidence confidence. Source: '+source,width=100,size=7,color=palette['muted'],gap=10)
        y-=5

    def dependency_matrix(matrix):
        nonlocal y
        ids=matrix.get('domain_ids',[]); rows=matrix.get('rows',[])
        if not ids:return
        if y < bottom+210:new_page()
        names={d['id']:d['name'] for d in ids}; order=[d['id'] for d in ids]; values={(r['source_domain_id'],r['target_domain_id']):r['edge_count'] for r in rows}
        maximum=max(values.values(),default=1) or 1; cell=min(40,420/max(1,len(order)))
        line('Domain dependency matrix (source row -> target column)',size=10,font='F2',color=palette['navy'],gap=18)
        start_x=margin+126; start_y=y
        for j,did in enumerate(order):
            text_at(names[did][:10],start_x+j*cell,start_y-7,6,'F1',palette['muted'])
        y-=13
        for i,s in enumerate(order):
            text_at(names[s][:20],margin+2,y-9,7,'F1',palette['ink'])
            for j,t in enumerate(order):
                value=values.get((s,t),0); intensity=value/maximum
                color=f'{0.94-0.58*intensity:.2f} {0.97-0.40*intensity:.2f} {0.99-0.12*intensity:.2f}'
                rect(start_x+j*cell,y-14,cell-2,15,color)
                text_at(str(value),start_x+j*cell+cell/2-3,y-9,7,'F2',palette['navy'])
            y-=18
        y-=5
        wrapped('Cell values are class-level dependency edge counts. Absent domain pairs equal zero in the captured static graph.',width=100,size=7,color=palette['muted'],gap=10)
        y-=8

    def dependency_graph(matrix):
        nonlocal y
        ids=matrix.get('domain_ids',[]); rows=matrix.get('rows',[])
        if not ids:return
        if y < bottom+275:new_page()
        names={d['id']:d['name'] for d in ids}; cx=306; cy=y-128; radius=98
        line('Directed domain graph (edge labels show class-pair counts)',size=10,font='F2',color=palette['navy'],gap=18)
        order=[d['id'] for d in ids]
        positions={did:(cx+radius*__import__('math').cos(2*__import__('math').pi*i/len(order)),cy+radius*__import__('math').sin(2*__import__('math').pi*i/len(order))) for i,did in enumerate(order)}
        maximum=max((r['edge_count'] for r in rows),default=1)
        for row in rows:
            x1,y1=positions[row['source_domain_id']]; x2,y2=positions[row['target_domain_id']]
            commands.append(f'{palette["blue"]} RG {0.6+1.4*row["edge_count"]/maximum:.1f} w {x1:.1f} {y1:.1f} m {x2:.1f} {y2:.1f} l S'.encode('ascii'))
            text_at(str(row['edge_count']),(x1+x2)/2,(y1+y2)/2,7,'F2',palette['coral'])
        for did,(x,y0) in positions.items():
            rect(x-40,y0-10,80,20,palette['pale_teal']); text_at(names[did][:18],x-37,y0-3,6,'F2',palette['navy'])
        if not rows:
            text_at('No cross-domain edges were found in the static graph.',margin,cy-radius-17,7,'F1',palette['muted'])
        y=cy-radius-20

    def table_block(block):
        nonlocal y
        columns, rows = block['columns'], block['rows'][:400]
        weights = [min(38, max(6, max([len(str(col))] + [len(str(r[i])) for r in rows[:60]]))) for i, col in enumerate(columns)]
        usable, total = 508, sum(weights)
        widths = [usable * w / total for w in weights]
        chars = [max(4, int(w / 3.7)) for w in widths]
        if y < bottom + 60:
            new_page()
        line(block['caption'], size=10, font='F2', color=palette['navy'], gap=15)

        def header():
            nonlocal y
            rect(46, y - 9, 510, 13, palette['pale_teal'])
            x = 48
            for column, width, limit in zip(columns, widths, chars):
                text_at(str(column)[:limit], x, y - 5, 7, 'F2', palette['navy'])
                x += width
            y -= 15
        header()
        if not rows:
            line('none', size=8, color=palette['muted'], gap=12)
        for number, row in enumerate(rows):
            cells = [textwrap.wrap(_plain(cell), width=limit, break_long_words=True) or [''] for cell, limit in zip(row, chars)]
            height = 9 * max(len(c) for c in cells) + 4
            if y - height < bottom:
                new_page()
                header()
            if number % 2 == 0:
                rect(46, y - height + 8, 510, height, palette['pale'])
            x = 48
            for lines_, width in zip(cells, widths):
                for offset, piece in enumerate(lines_):
                    text_at(piece, x, y - 2 - 9 * offset, 7, 'F1', palette['ink'])
                x += width
            y -= height
        if len(block['rows']) > 400:
            line(f"{len(block['rows']) - 400} more rows are in the HTML report and the JSON export.", size=7, color=palette['muted'], gap=10)
        if block.get('note'):
            wrapped(block['note'], width=100, size=7, color=palette['muted'], gap=10)
        y -= 8

    def hld_diagram(data):
        nonlocal y
        layers, edges, externals, entries = data.get('layers', []), data.get('edges', []), data.get('externals', []), data.get('entry_points', [])
        body = max(len(layers) * 44, len(externals) * 40)
        if y < bottom + 70 + body:
            new_page()
        line('High-level architecture', size=10, font='F2', color=palette['navy'], gap=16)
        top = y
        if entries:
            width = 500 / len(entries)
            for n, entry in enumerate(entries):
                x = 48 + n * width
                rect(x, top - 26, width - 6, 26, palette['pale'])
                text_at(entry['label'][:int(width / 4.2)], x + 3, top - 11, 7, 'F2', palette['navy'])
                text_at(f"{entry['count']} entry point(s)", x + 3, top - 22, 6, 'F1', palette['muted'])
            top -= 40
        boxes = {}
        left, box_w = 120, 250
        for i, layer in enumerate(layers):
            y0 = top - i * 44
            boxes[layer['id']] = (left, y0, box_w, 30)
            rect(left, y0 - 30, box_w, 30, palette['pale_teal'])
            text_at(layer['label'][:58], left + 6, y0 - 12, 8, 'F2', palette['navy'])
            text_at(f"{layer['class_count']} classes in {layer['package_count']} package(s)", left + 6, y0 - 24, 6, 'F1', palette['muted'])
        ext_x, ext_w = left + box_w + 70, 120
        for n, ext in enumerate(externals):
            y0 = top - n * 44
            boxes[ext['id']] = (ext_x, y0, ext_w, 30)
            rect(ext_x, y0 - 30, ext_w, 30, palette['pale_gold'])
            text_at(ext['label'][:28], ext_x + 4, y0 - 12, 7, 'F2', palette['navy'])
            text_at(f"{ext['class_count']} classes", ext_x + 4, y0 - 24, 6, 'F1', palette['muted'])
        lane = 0
        for edge in edges:
            if edge['source'] not in boxes or edge['target'] not in boxes:
                continue
            sx, sy, sw, sh = boxes[edge['source']]
            tx, ty, tw, th = boxes[edge['target']]
            colour = palette['coral'] if edge.get('against_layering') else palette['teal'] if edge.get('observed') else palette['muted']
            if edge['target'].startswith('external'):
                x1, y1, x2, y2 = sx + sw, sy - sh / 2, tx, ty - th / 2
                commands.append(f'{colour} RG 0.9 w {x1:.1f} {y1:.1f} m {x2:.1f} {y2:.1f} l S'.encode('ascii'))
                text_at(str(edge['class_pairs']), x1 + (x2 - x1) * .35, y1 + (y2 - y1) * .35 + 2, 6, 'F2', colour)
                continue
            lane += 1
            gx = left - 8 - (lane % 7) * 11
            y1, y2 = sy - sh / 2, ty - th / 2
            commands.append(f'{colour} RG 0.9 w {sx:.1f} {y1:.1f} m {gx:.1f} {y1:.1f} l {gx:.1f} {y2:.1f} l {tx - 1:.1f} {y2:.1f} l S'.encode('ascii'))
            text_at(str(edge['class_pairs']), gx - 8, (y1 + y2) / 2, 6, 'F2', colour)
        y = top - body - 6
        wrapped('Arrows point from the depending layer to what it uses; numbers are distinct class pairs. Teal: also seen at runtime. Grey: code only. Red: against the layering.', width=100, size=7, color=palette['muted'], gap=10)
        y -= 6

    new_page()
    # The report opens with a designed cover, then uses a consistent high-contrast
    # page header, color-coded section bars, and clear evidence source labels.
    pages.clear()
    commands = []
    y = 700
    for kind, text in report_lines(report):
        if kind == 'page':
            if len(commands) > 4:
                new_page()
        elif kind == 'table':
            table_block(text)
        elif kind == 'hld':
            hld_diagram(text)
        elif kind == 'chart':
            chart(text)
        elif kind == 'paired':
            paired_chart(text)
        elif kind == 'matrix':
            dependency_matrix(text)
        elif kind == 'domain_graph':
            dependency_graph(text)
        elif kind == 'cover':
            cover_page = True
            rect(0, 0, page_width, page_height, palette['navy'])
            rect(0, 0, 14, page_height, palette['teal'])
            rect(398, 492, 214, 300, palette['navy2'])
            rect(440, 542, 132, 132, palette['teal'])
            rect(468, 570, 76, 76, palette['navy'])
            rect(506, 608, 42, 42, palette['gold'])
            text_at('ARCHINTEL  |  ARCHITECTURE INTELLIGENCE', 48, 718, 10, 'F2', palette['teal'])
            y = 625
            wrapped(text, width=24, size=27, font='F2', color=palette['white'], gap=34)
        elif kind == 'subtitle':
            wrapped(text, width=55, size=18, font='F2', color=palette['teal'], gap=24)
        elif kind == 'meta':
            wrapped(text, width=90, size=8, color='0.83 0.88 0.94' if cover_page else palette['muted'], gap=13)
        elif kind == 'notice':
            if cover_page:
                rect(42, y - 44, 522, 43, palette['navy2'])
                wrapped(text, width=93, size=9, color=palette['white'], gap=13, indent=10)
                y -= 8
            else:
                rect(42, y - 30, 522, 30, palette['pale_gold'])
                rect(42, y - 30, 4, 30, palette['gold'])
                wrapped(text, width=92, size=8, color=palette['ink'], gap=12, indent=10)
                y -= 10
        elif kind == 'h1':
            if y < bottom + 50:
                new_page()
            rect(42, y - 22, 522, 30, palette['pale_teal'])
            rect(42, y - 22, 5, 30, palette['teal'])
            wrapped(text, width=74, size=14, font='F2', color=palette['navy'], gap=18, indent=10)
            y -= 12
        elif kind == 'h2':
            y -= 3
            wrapped(text, width=82, size=11, font='F2', color=palette['blue'], gap=15)
        elif kind == 'kv':
            key, value = text.split('\x00', 1)
            wrapped(key.upper(), width=92, size=7, font='F2', color=palette['blue'], gap=10, indent=4)
            wrapped(value, width=92, size=9, color=palette['ink'], gap=13, indent=4)
        elif kind == 'row':
            rect(46, y - 11, 510, 18, palette['pale'])
            rect(46, y - 11, 3, 18, palette['blue'])
            wrapped(text, width=92, size=8, color=palette['ink'], gap=12, indent=8)
        elif kind == 'bullet':
            wrapped('- ' + text, width=90, size=8, color=palette['ink'], gap=12, indent=8)
        elif kind == 'finding':
            issue = text
            severity = str(issue.get('severity', 'UNRANKED')).upper()
            severity_color = palette['coral'] if severity in ('CRITICAL', 'HIGH') else palette['gold'] if severity == 'MEDIUM' else palette['blue']
            wrapped(f'{severity}  |  {issue.get("title") or issue.get("issue_type") or issue.get("id")}', width=88, size=10, font='F2', color=severity_color, gap=14)
            wrapped('Plain meaning: ' + str(issue.get('why_it_matters') or issue.get('description') or 'No plain-language explanation was supplied.'), width=93, size=8, color=palette['ink'], gap=12, indent=8)
            wrapped('Technical target: ' + str(issue.get('entity_type', 'entity')) + ' / ' + str(issue.get('entity_id', 'not specified')) + '  |  Type: ' + str(issue.get('issue_type', 'not specified')), width=93, size=7, color=palette['muted'], gap=11, indent=8)
            evidence = issue.get('evidence')
            if evidence:
                wrapped('Evidence: ' + str(evidence), width=93, size=7, color=palette['muted'], gap=11, indent=8)
            wrapped('Suggested investigation: ' + str(issue.get('recommendation') or 'No recommendation was supplied.'), width=93, size=8, color=palette['ink'], gap=12, indent=8)
            y -= 7
        elif kind == 'sub':
            wrapped(text, width=88, size=8, color=palette['muted'], gap=12, indent=15)
        elif kind == 'footer_note':
            y -= 6
            wrapped(text, width=95, size=8, color=palette['muted'], gap=12)
        elif kind == 'p':
            wrapped(text, width=95, size=8, color=palette['ink'], gap=12)
            y -= 2
    if commands:
        pages.append(commands)

    total = len(pages)
    objects = [None, b'<< /Type /Catalog /Pages 2 0 R >>', None,
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>']
    page_ids = []
    for index, page_commands in enumerate(pages, start=1):
        footer_color = palette['white'] if index == 1 else palette['muted']
        footer = f'{footer_color} rg BT /F1 8 Tf 48 30 Td (Confidential working report  |  Page {index} of {total}) Tj ET'.encode('ascii')
        stream = b'\n'.join(page_commands + [footer])
        compressed = zlib.compress(stream)
        content_id = len(objects)
        objects.append(b'<< /Length ' + str(len(compressed)).encode('ascii') + b' /Filter /FlateDecode >>\nstream\n' + compressed + b'\nendstream')
        page_id = len(objects)
        page_ids.append(page_id)
        objects.append(b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents ' + str(content_id).encode('ascii') + b' 0 R >>')
    kids = b' '.join(str(page_id).encode('ascii') + b' 0 R' for page_id in page_ids)
    objects[2] = b'<< /Type /Pages /Kids [' + kids + b'] /Count ' + str(total).encode('ascii') + b' >>'
    output = bytearray(b'%PDF-1.4\n%ArchIntel\n')
    offsets = [0]
    for object_id, obj in enumerate(objects[1:], start=1):
        offsets.append(len(output))
        output.extend(str(object_id).encode('ascii') + b' 0 obj\n' + obj + b'\nendobj\n')
    xref = len(output)
    output.extend(b'xref\n0 ' + str(len(objects)).encode('ascii') + b'\n0000000000 65535 f \n')
    for offset in offsets[1:]:
        output.extend(f'{offset:010d} 00000 n \n'.encode('ascii'))
    output.extend(b'trailer\n<< /Size ' + str(len(objects)).encode('ascii') + b' /Root 1 0 R >>\nstartxref\n' + str(xref).encode('ascii') + b'\n%%EOF\n')
    return bytes(output)

