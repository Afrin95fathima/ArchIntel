"""Bounded archive handling; customer bytecode is never executed."""
import hashlib
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile
from app.config import Settings


class ArtifactError(ValueError):
    pass


class LimitExceeded(ArtifactError):
    def __init__(self, limit: str, configured: int, observed: int, advice: str):
        self.limit, self.configured, self.observed, self.advice = limit, configured, observed, advice
        super().__init__(f"Limit {limit} exceeded: configured {configured}, observed {observed}. {advice}")


class _ByteArrayWriter:
    def __init__(self, target: bytearray): self.target = target
    def write(self, value): self.target.extend(value)


class _NullWriter:
    def write(self, value): return len(value)


def _copy_bounded(source, output, budget: list[int], maximum: int, limit: str) -> int:
    copied = 0
    while chunk := source.read(min(1024 * 1024, maximum - budget[0] + 1)):
        budget[0] += len(chunk)
        copied += len(chunk)
        output.write(chunk)
        if budget[0] > maximum:
            raise LimitExceeded(limit, maximum, budget[0], 'Split the artifact or ask your administrator to raise this limit.')
    return copied


def _check_archive_metadata(entry, config: Settings, count: int, expanded: int, description: str, check_size: bool = True) -> int:
    if count > config.max_archive_entries:
        raise LimitExceeded('max_archive_entries', config.max_archive_entries, count, 'Split the artifact by module.')
    maximum = config.max_expanded_mb * 1024**2
    if check_size and expanded > maximum:
        raise LimitExceeded('max_uncompressed_size', maximum, expanded, 'Split the artifact by module.')
    ratio = entry.file_size / max(1, entry.compress_size)
    if ratio > config.max_compression_ratio:
        raise LimitExceeded('max_compression_ratio', config.max_compression_ratio, int(ratio), 'Repackage the artifact without highly compressible padding.')
    return expanded


def validate_archive(path: Path, config: Settings, destination: Path | None = None) -> dict:
    if not zipfile.is_zipfile(path):
        raise ArtifactError('This file is not a valid Java ZIP archive (JAR/WAR).')
    compressed = path.stat().st_size
    if compressed > config.max_upload_mb * 1024**2:
        raise LimitExceeded('max_upload_size_compressed', config.max_upload_mb * 1024**2, compressed, 'Split the artifact by module or ask your administrator to raise max_upload_mb.')
    expanded, actual_expanded, count, classes, libraries, multi_release = 0, [0], 0, [], 0, 0
    packaging = 'JAR'
    try:
        with zipfile.ZipFile(path) as archive:
            seen = set()
            for entry in archive.infolist():
                count += 1
                normalized = entry.filename.replace('\\', '/')
                parts = PurePosixPath(normalized)
                if parts.is_absolute() or '..' in parts.parts or ':' in normalized or '\x00' in normalized:
                    raise ArtifactError('Archive contains an unsafe path.')
                if stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                    raise ArtifactError('Encrypted ZIP entries and symbolic links are not supported.')
                expanded += entry.file_size
                _check_archive_metadata(entry, config, count, expanded, 'Archive')
                if normalized.endswith('.jar'):
                    libraries += 1
                if not normalized.endswith('.class'):
                    continue
                if normalized.startswith('META-INF/versions/'):
                    multi_release += 1
                    continue
                if normalized.rsplit('/', 1)[-1] in ('module-info.class', 'package-info.class'):
                    continue
                class_path = normalized
                if normalized.startswith('BOOT-INF/classes/'):
                    packaging = 'SPRING_BOOT'
                elif normalized.startswith('WEB-INF/classes/'):
                    packaging = 'WAR'
                for prefix in ('BOOT-INF/classes/', 'WEB-INF/classes/'):
                    if class_path.startswith(prefix):
                        class_path = class_path[len(prefix):]
                if class_path.casefold() in seen:
                    raise ArtifactError('Duplicate class paths in one JAR are ambiguous and are not supported.')
                seen.add(class_path.casefold())
                classes.append(class_path)
                if len(classes) > config.max_classes:
                    raise ArtifactError('Artifact exceeds the configured class limit.')
                with archive.open(entry) as source:
                    header = source.read(4)
                    if destination is not None: actual_expanded[0] += len(header)
                    if header != b'\xca\xfe\xba\xbe':
                        raise ArtifactError('An entry has a .class extension but is not Java bytecode.')
                if destination is not None:
                    target = (destination / class_path).resolve()
                    if not target.is_relative_to(destination.resolve()):
                        raise ArtifactError('Class path escapes the analysis directory.')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as source, target.open('wb') as output:
                        header = source.read(4)
                        actual_expanded[0] += len(header)
                        if header != b'\xca\xfe\xba\xbe':
                            raise ArtifactError('An entry has a .class extension but is not Java bytecode.')
                        output.write(header)
                        _copy_bounded(source, output, actual_expanded, config.max_expanded_mb * 1024**2, 'max_uncompressed_size')
            if not classes:
                raise ArtifactError('No application .class files found. Upload a compiled application JAR/WAR.')
    except (zipfile.BadZipFile, RuntimeError, OSError) as error:
        if isinstance(error, ArtifactError):
            raise
        raise ArtifactError('Archive is corrupt or unreadable.') from error
    return dict(class_files=len(classes), archive_entries=count, expanded_bytes=max(expanded, actual_expanded[0]),
        nested_libraries_skipped=libraries, multi_release_overrides_skipped=multi_release,
        packaging=packaging,
        limitations=['Bundled third-party JARs are not recursively scanned; application references to them are preserved.', 'Multi-release JAR override classes (META-INF/versions) are skipped; base classes are analyzed.'])


def validate_project_zip(path: Path, config: Settings, destination: Path | None = None) -> dict:
    """Collect compiled project classes from a ZIP without extracting arbitrary files.

    Accepted class sources are explicit target/classes or build/classes trees and
    ordinary module JAR/WAR files. Java source is retained only as an input
    manifest; this bytecode scanner does not compile or execute uploaded code.
    """
    if not zipfile.is_zipfile(path):
        raise ArtifactError('This file is not a valid ZIP project bundle.')
    compressed = path.stat().st_size
    if compressed > config.max_upload_mb * 1024**2:
        raise LimitExceeded('max_upload_size_compressed', config.max_upload_mb * 1024**2, compressed, 'Split the artifact by module or ask your administrator to raise max_upload_mb.')
    total_entries = 0
    expanded = 0
    actual_expanded = [0]
    candidate_entries: list[tuple[str, zipfile.ZipInfo, str, str]] = []
    seen_paths: set[str] = set()
    try:
        with zipfile.ZipFile(path) as archive:
            for entry in archive.infolist():
                total_entries += 1
                normalized = entry.filename.replace('\\', '/')
                parts = PurePosixPath(normalized)
                if parts.is_absolute() or '..' in parts.parts or ':' in normalized or '\x00' in normalized:
                    raise ArtifactError('Project ZIP contains an unsafe path.')
                if stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                    raise ArtifactError('Encrypted ZIP entries and symbolic links are not supported.')
                expanded += entry.file_size
                _check_archive_metadata(entry, config, total_entries, expanded, 'Project ZIP', check_size=False)
                lowered = normalized.casefold()
                # Exclude dependency caches, generated web bundles and VCS trees.
                if any(part in {'.git', 'node_modules', '.m2', 'deps', 'dependency', 'dependencies'}
                       for part in (p.casefold() for p in parts.parts)):
                    continue
                if lowered.endswith('.class'):
                    segments = [part.casefold() for part in parts.parts]
                    output_index = next((i for i in range(len(segments)-1)
                        if segments[i:i+2] in (['target', 'classes'], ['build', 'classes'])), None)
                    if output_index is not None:
                        class_path = '/'.join(parts.parts[output_index+2:])
                    elif len(parts.parts) == 1:
                        class_path = normalized
                    else:
                        with archive.open(entry) as source:
                            _copy_bounded(source, _NullWriter(), actual_expanded, config.max_expanded_mb * 1024**2, 'max_uncompressed_size')
                        continue
                    candidate_entries.append((class_path, entry, 'class', normalized))
                elif lowered.endswith(('.jar', '.war')) and (
                    '/target/' in lowered or '/build/libs/' in lowered or lowered.startswith(('target/', 'build/libs/'))
                ):
                    candidate_entries.append((normalized, entry, 'archive', normalized))
                else:
                    with archive.open(entry) as source:
                        _copy_bounded(source, _NullWriter(), actual_expanded, config.max_expanded_mb * 1024**2, 'max_uncompressed_size')

            if not candidate_entries:
                raise ArtifactError('This ZIP contains no compiled Java output. Build the project first and include its module target/classes folders or target JAR/WAR files; source-only ZIPs are not yet supported.')

            root = destination.resolve() if destination is not None else None
            if root is not None:
                root.mkdir(parents=True, exist_ok=True)
            hashes: dict[str, str] = {}
            origins: dict[str, str] = {}
            conflicts: dict[str, dict[str, str]] = {}
            extracted = 0
            scanned_archives = 0
            multi_release = 0
            temp_root = Path(tempfile.mkdtemp(prefix='archintel-project-'))
            try:
                for item_path, entry, kind, origin in sorted(candidate_entries, key=lambda item: item[3].casefold()):
                    if kind == 'class':
                        if entry.file_size > 16 * 1024 * 1024:
                            raise ArtifactError('A compiled class entry exceeds the 16 MiB safety limit.')
                        with archive.open(entry) as source:
                            header = source.read(4)
                            actual_expanded[0] += len(header)
                            if actual_expanded[0] > config.max_expanded_mb * 1024**2:
                                raise LimitExceeded('max_uncompressed_size',config.max_expanded_mb*1024**2,actual_expanded[0],'Split the artifact by module.')
                            if header != b'\xca\xfe\xba\xbe':
                                raise ArtifactError('A .class entry is not valid Java bytecode.')
                            tail = bytearray()
                            class_budget = [actual_expanded[0]]
                            _copy_bounded(source, _ByteArrayWriter(tail), class_budget, config.max_expanded_mb * 1024**2, 'max_uncompressed_size')
                            actual_expanded[0] = class_budget[0]
                            content = header + bytes(tail)
                        digest = hashlib.sha256(content).hexdigest()
                        extracted += _store_project_class(item_path, digest, header, content, config, root, hashes,
                            origins, conflicts, origin)
                    else:
                        # Stream each nested artifact to disk; never load an entire nested archive into memory.
                        nested = temp_root / f'{scanned_archives}.zip'
                        with archive.open(entry) as source, nested.open('wb') as output:
                            extracted_nested = _copy_bounded(source, output, [0], config.max_expanded_mb * 1024**2, 'max_uncompressed_size')
                        if extracted_nested != entry.file_size:
                            raise ArtifactError('Nested archive size does not match its ZIP directory entry.')
                        if not zipfile.is_zipfile(nested):
                            raise ArtifactError('A compiled module archive in the project ZIP is corrupt.')
                        with zipfile.ZipFile(nested) as module_archive:
                            scanned_archives += 1
                            for module_entry in module_archive.infolist():
                                total_entries += 1
                                normalized = module_entry.filename.replace('\\', '/')
                                parts = PurePosixPath(normalized)
                                if parts.is_absolute() or '..' in parts.parts or ':' in normalized or '\x00' in normalized:
                                    raise ArtifactError('A compiled module archive contains an unsafe path (absolute or ../).')
                                if stat.S_ISLNK(module_entry.external_attr >> 16) or module_entry.flag_bits & 1:
                                    raise ArtifactError('Encrypted ZIP entries and symbolic links are not supported.')
                                expanded += module_entry.file_size
                                _check_archive_metadata(module_entry, config, total_entries, expanded, 'Project ZIP', check_size=False)
                                name = normalized.casefold()
                                module_parts = [p.casefold() for p in parts.parts]
                                if not name.endswith('.class') or any(
                                    module_parts[i:i+2] in (['web-inf', 'lib'], ['boot-inf', 'lib'])
                                    for i in range(len(module_parts)-1)
                                ) or (module_parts and module_parts[0] in {'lib', 'libs', 'deps', 'dependencies'}):
                                    with module_archive.open(module_entry) as source:
                                        _copy_bounded(source,_NullWriter(),actual_expanded,config.max_expanded_mb*1024**2,'max_uncompressed_size')
                                    continue
                                if module_entry.file_size > 16 * 1024 * 1024:
                                    raise ArtifactError('A compiled class entry exceeds the 16 MiB safety limit.')
                                if name.startswith('meta-inf/versions/'):
                                    multi_release += 1
                                    continue
                                class_path = normalized
                                if class_path.rsplit('/', 1)[-1] in ('module-info.class', 'package-info.class'):
                                    continue
                                with module_archive.open(module_entry) as source:
                                    header = source.read(4)
                                    actual_expanded[0] += len(header)
                                    if actual_expanded[0] > config.max_expanded_mb*1024**2:
                                        raise LimitExceeded('max_uncompressed_size',config.max_expanded_mb*1024**2,actual_expanded[0],'Split the artifact by module.')
                                    if header != b'\xca\xfe\xba\xbe':
                                        raise ArtifactError('A module .class entry is not valid Java bytecode.')
                                    tail = bytearray()
                                    class_budget = [actual_expanded[0]]
                                    _copy_bounded(source, _ByteArrayWriter(tail), class_budget, config.max_expanded_mb * 1024**2, 'max_uncompressed_size')
                                    actual_expanded[0] = class_budget[0]
                                    content = header + bytes(tail)
                                digest = hashlib.sha256(content).hexdigest()
                                extracted += _store_project_class(class_path, digest, header,
                                    content, config, root, hashes, origins, conflicts,
                                    item_path + '!/' + normalized)
            finally:
                shutil.rmtree(temp_root, ignore_errors=True)
    except (zipfile.BadZipFile, RuntimeError, OSError) as error:
        if isinstance(error, ArtifactError):
            raise
        raise ArtifactError('Project ZIP is corrupt or unreadable.') from error
    if not hashes:
        raise ArtifactError('No compiled Java classes were found in the project ZIP.')
    return dict(class_files=len(hashes), archive_entries=total_entries, expanded_bytes=max(expanded, actual_expanded[0]),
        nested_archives=scanned_archives, duplicate_identical_classes=extracted-len(hashes),
        conflicting_duplicate_classes=len(conflicts), conflicting_duplicate_examples=list(conflicts.values())[:100],
        multi_release_overrides_skipped=multi_release, packaging='JAVA_PROJECT_ZIP',
        limitations=['Only compiled bytecode under target/classes or build/classes and project module JAR/WAR files is analyzed; Java source is not compiled.',
            'Third-party classes bundled under dependency/lib folders are skipped.',
            'Module and multi-release metadata (module-info.class, META-INF/versions) can be incomplete when only classes directories are included.',
            'For conflicting definitions with the same fully qualified class name, the first normalized project path is analyzed; alternatives are listed in the ZIP manifest.'])


def _store_project_class(class_path: str, digest: str, header: bytes, content: bytes, config: Settings,
                         destination: Path | None, hashes: dict[str, str], origins: dict[str, str],
                         conflicts: dict[str, dict[str, str]], origin: str) -> int:
    normalized = class_path.replace('\\', '/')
    parts = PurePosixPath(normalized)
    if parts.is_absolute() or '..' in parts.parts or ':' in normalized or '\x00' in normalized:
        raise ArtifactError('Project ZIP contains an unsafe compiled class path.')
    if normalized.startswith('META-INF/versions/') or normalized.rsplit('/', 1)[-1] in ('module-info.class', 'package-info.class'):
        return 0
    key = normalized.casefold()
    existing = hashes.get(key)
    if existing:
        if existing != digest:
            conflicts.setdefault(key, dict(class_path=normalized, selected=origins[key], ignored=origin))
            return 0
        return 1
    if len(hashes) >= config.max_classes:
        raise ArtifactError('Project ZIP exceeds the configured class limit.')
    hashes[key] = digest
    origins[key] = origin
    if destination is not None:
        target = (destination / normalized).resolve()
        if not target.is_relative_to(destination):
            raise ArtifactError('Compiled class path escapes the analysis directory.')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return 1


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def remove_job(path: Path, root: Path) -> None:
    resolved, parent = path.resolve(), root.resolve()
    if resolved == parent or not resolved.is_relative_to(parent):
        raise ValueError('Refusing cleanup outside the job root.')
    if resolved.exists():
        shutil.rmtree(resolved)
