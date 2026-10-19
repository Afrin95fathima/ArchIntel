"""Bounded per-analysis source store for the assistant and AI explanation steps.

What is stored: `.java` entries that were inside the uploaded artifact (for example source jars or
project ZIPs that include src/). Nothing is decompiled. When no source exists, callers receive a
deterministic *bytecode outline* (signatures, annotations, call sites with line numbers) labelled as such.

Access is only through analysis-scoped API routes, which enforce tenant ownership of the analysis.
`source_store_mode=DENY` disables capture and reading.
"""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import zipfile

from .roles import short


def _root(config, analysis_id: str) -> Path:
    return Path(config.data_dir) / 'source-store' / analysis_id


def _fqn_for(name: str, internal: set[str]) -> str | None:
    parts = PurePosixPath(name).with_suffix('').parts
    for start in range(len(parts)):
        candidate = '.'.join(parts[start:])
        if candidate in internal:
            return candidate
    return None


def capture(config, analysis_id: str, artifact_path: Path, result: dict) -> dict:
    if getattr(config, 'source_store_mode', 'ALLOW') != 'ALLOW':
        return dict(status='DISABLED', reason='source_store_mode=DENY for this deployment.', index={})
    internal = {c['id'] for c in result.get('classes', [])}
    per_class, total_limit = config.source_store_max_bytes_per_class, config.source_store_max_total_bytes
    index, total, skipped = {}, 0, 0
    try:
        with zipfile.ZipFile(artifact_path) as archive:
            for info in archive.infolist():
                name = info.filename.replace('\\', '/')
                if not name.endswith('.java') or info.is_dir() or '..' in PurePosixPath(name).parts:
                    continue
                fqn = _fqn_for(name, internal)
                if not fqn or fqn in index:
                    continue
                if info.file_size > per_class or total + info.file_size > total_limit:
                    skipped += 1
                    continue
                data = archive.read(info)[:per_class]
                digest = hashlib.sha256(data).hexdigest()
                folder = _root(config, analysis_id)
                folder.mkdir(parents=True, exist_ok=True)
                (folder / (digest + '.java')).write_bytes(data)
                index[fqn] = dict(sha256=digest, bytes=len(data), archive_path=name)
                total += len(data)
    except (OSError, zipfile.BadZipFile):
        return dict(status='UNAVAILABLE', reason='The artifact could not be reopened to read source entries.', index={})
    status = 'SOURCE_CAPTURED' if index else 'NO_SOURCE_IN_ARTIFACT'
    return dict(status=status, index=index, total_bytes=total, skipped_over_limit=skipped,
        reason=None if index else 'The uploaded artifact contains no .java source entries; a bytecode outline is used instead.')


def outline(fqn: str, facts: dict) -> str:
    """Deterministic, human-readable bytecode outline. Not source code."""
    info = facts.get(fqn)
    if not info:
        return ''
    lines = [f'// Bytecode outline of {fqn} (generated from the class file; not original source)']
    for annotation in info['annotations']:
        lines.append(f'@{short(annotation["type"])}{annotation["values"] or ""}')
    kind = 'interface' if info['interface'] else 'enum' if info['enum'] else 'abstract class' if info['abstract'] else 'class'
    extends = f' extends {short(info["super_name"])}' if info.get('super_name') and info['super_name'] != 'java.lang.Object' else ''
    implements = (' implements ' + ', '.join(short(i) for i in info['interfaces'])) if info['interfaces'] else ''
    lines.append(f'{info["visibility"]} {kind} {short(fqn)}{extends}{implements} {{')
    for field in info['fields']:
        if field['synthetic']:
            continue
        notes = ''.join(f'@{short(a["type"])}{a["values"] or ""} ' for a in field['annotations'])
        lines.append(f'  {notes}{field["visibility"]}{" static" if field["static"] else ""}{" final" if field["final"] else ""} {short(field["type"])} {field["name"]};')
    for method in info['methods']:
        if method['synthetic'] or method['bridge']:
            continue
        notes = ''.join(f'@{short(a["type"])}{a["values"] or ""} ' for a in method['annotations'])
        name = short(fqn) if method['name'] == '<init>' else 'static {}' if method['name'] == '<clinit>' else method['name']
        where = f'  // lines {method["line_range"][0]}-{method["line_range"][1]}' if method.get('line_range') else ''
        lines.append(f'  {notes}{method["visibility"]}{" static" if method["static"] else ""} {short(method["returns"])} {name}({", ".join(short(p) for p in method["parameters"])}){where}')
        for site in method['invokes'][:40]:
            callee = 'new ' + short(site['owner']) if site['name'] == '<init>' else f'{short(site["owner"])}.{site["name"]}()'
            lines.append(f'    -> calls {callee}' + (f' at line {site["line"]}' if site.get('line') else ''))
    lines.append('}')
    return '\n'.join(lines)


def read(config, analysis_id: str, result: dict, fqn: str, max_bytes: int = 16384) -> dict:
    if getattr(config, 'source_store_mode', 'ALLOW') != 'ALLOW':
        return dict(fqn=fqn, kind='DISABLED', text='', reason='Source reading is disabled for this deployment (source_store_mode=DENY).')
    store = result.get('source_store') or {}
    entry = (store.get('index') or {}).get(fqn)
    if entry:
        path = _root(config, analysis_id) / (entry['sha256'] + '.java')
        try:
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() == entry['sha256']:
                return dict(fqn=fqn, kind='SOURCE', text=data[:max_bytes].decode('utf-8', 'replace'), truncated=len(data) > max_bytes,
                    archive_path=entry['archive_path'])
        except OSError:
            pass
    facts = (result.get('bytecode') or {}).get('classes') or {}
    text = outline(fqn, facts)
    if not text:
        return dict(fqn=fqn, kind='NOT_AVAILABLE', text='', reason='No source and no bytecode facts are recorded for this class.')
    return dict(fqn=fqn, kind='BYTECODE_OUTLINE', text=text[:max_bytes], truncated=len(text) > max_bytes,
        reason='No .java source was in the artifact; this outline is generated from bytecode.')
