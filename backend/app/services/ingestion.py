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


def validate_archive(path: Path, config: Settings, destination: Path | None = None) -> dict:
    if not zipfile.is_zipfile(path):
        raise ArtifactError('This file is not a valid Java ZIP archive (JAR/WAR).')
    expanded, count, classes, libraries, multi_release = 0, 0, [], 0, 0
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
                    raise ArtifactError('Encrypted entries and symbolic links are not supported.')
                expanded += entry.file_size
                if count > config.max_archive_entries or expanded > config.max_expanded_mb * 1024**2:
                    raise ArtifactError('Archive expanded size or entry count exceeds the configured limit.')
                if entry.file_size > 1024 * max(1, entry.compress_size):
                    raise ArtifactError('Archive compression ratio exceeds the safety limit.')
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
                    raise ArtifactError('Duplicate class paths are ambiguous and are not supported.')
                seen.add(class_path.casefold())
                classes.append(class_path)
                if len(classes) > config.max_classes:
                    raise ArtifactError('Artifact exceeds the configured class limit.')
                with archive.open(entry) as source:
                    if source.read(4) != b'\xca\xfe\xba\xbe':
                        raise ArtifactError('An entry has a .class extension but is not Java bytecode.')
                if destination is not None:
                    target = (destination / class_path).resolve()
                    if not target.is_relative_to(destination.resolve()):
                        raise ArtifactError('Class path escapes the analysis directory.')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as source, target.open('wb') as output:
                        header = source.read(4)
                        if header != b'\xca\xfe\xba\xbe':
                            raise ArtifactError('An entry has a .class extension but is not Java bytecode.')
                        output.write(header)
                        shutil.copyfileobj(source, output, length=1024 * 1024)
            if not classes:
                raise ArtifactError('No application .class files found. Upload a compiled application JAR/WAR.')
    except (zipfile.BadZipFile, RuntimeError, OSError) as error:
        if isinstance(error, ArtifactError):
            raise
        raise ArtifactError('Archive is corrupt or unreadable.') from error
    return dict(class_files=len(classes), archive_entries=count, expanded_bytes=expanded,
        nested_libraries_skipped=libraries, multi_release_overrides_skipped=multi_release,
        packaging=packaging,
        limitations=['Bundled third-party JARs are not recursively scanned; application references to them are preserved.', 'Multi-release override classes are skipped; base classes are analyzed.'])


def validate_project_zip(path: Path, config: Settings, destination: Path | None = None) -> dict:
    """Collect compiled project classes from a ZIP without extracting arbitrary files.

    Accepted class sources are explicit target/classes or build/classes trees and
    ordinary module JAR/WAR files. Java source is retained only as an input
    manifest; this bytecode scanner does not compile or execute uploaded code.
    """
    if not zipfile.is_zipfile(path):
        raise ArtifactError('This file is not a valid ZIP project bundle.')
    total_entries = 0
    expanded = 0
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
                    raise ArtifactError('Encrypted entries and symbolic links are not supported.')
                expanded += entry.file_size
                if total_entries > config.max_archive_entries or expanded > config.max_expanded_mb * 1024**2:
                    raise ArtifactError('Project ZIP expanded size or entry count exceeds the configured limit.')
                if entry.file_size > 1024 * max(1, entry.compress_size):
                    raise ArtifactError('Project ZIP compression ratio exceeds the safety limit.')
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
                        continue
                    candidate_entries.append((class_path, entry, 'class', normalized))
                elif lowered.endswith(('.jar', '.war')) and (
                    '/target/' in lowered or '/build/libs/' in lowered or lowered.startswith(('target/', 'build/libs/'))
                ):
                    candidate_entries.append((normalized, entry, 'archive', normalized))

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
                            if header != b'\xca\xfe\xba\xbe':
                                raise ArtifactError('A .class entry is not valid Java bytecode.')
                            content = header + source.read()
                        digest = hashlib.sha256(content).hexdigest()
                        extracted += _store_project_class(item_path, digest, header, content, config, root, hashes,
                            origins, conflicts, origin)
                    else:
                        # Stream each nested artifact to disk; never load an entire nested archive into memory.
                        nested = temp_root / f'{scanned_archives}.zip'
                        with archive.open(entry) as source, nested.open('wb') as output:
                            shutil.copyfileobj(source, output, length=1024 * 1024)
                        if not zipfile.is_zipfile(nested):
                            raise ArtifactError('A compiled module archive in the project ZIP is corrupt.')
                        with zipfile.ZipFile(nested) as module_archive:
                            scanned_archives += 1
                            for module_entry in module_archive.infolist():
                                total_entries += 1
                                normalized = module_entry.filename.replace('\\', '/')
                                parts = PurePosixPath(normalized)
                                if parts.is_absolute() or '..' in parts.parts or ':' in normalized or '\x00' in normalized:
                                    raise ArtifactError('A compiled module archive contains an unsafe path.')
                                if stat.S_ISLNK(module_entry.external_attr >> 16) or module_entry.flag_bits & 1:
                                    raise ArtifactError('Encrypted entries and symbolic links are not supported.')
                                expanded += module_entry.file_size
                                if total_entries > config.max_archive_entries or expanded > config.max_expanded_mb * 1024**2:
                                    raise ArtifactError('Project ZIP expanded size or entry count exceeds the configured limit.')
                                if module_entry.file_size > 1024 * max(1, module_entry.compress_size):
                                    raise ArtifactError('Module archive compression ratio exceeds the safety limit.')
                                name = normalized.casefold()
                                module_parts = [p.casefold() for p in parts.parts]
                                if not name.endswith('.class') or any(
                                    module_parts[i:i+2] in (['web-inf', 'lib'], ['boot-inf', 'lib'])
                                    for i in range(len(module_parts)-1)
                                ) or (module_parts and module_parts[0] in {'lib', 'libs', 'deps', 'dependencies'}):
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
                                    if header != b'\xca\xfe\xba\xbe':
                                        raise ArtifactError('A module .class entry is not valid Java bytecode.')
                                    content = header + source.read()
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
    return dict(class_files=len(hashes), archive_entries=total_entries, expanded_bytes=expanded,
        nested_archives=scanned_archives, duplicate_identical_classes=extracted-len(hashes),
        conflicting_duplicate_classes=len(conflicts), conflicting_duplicate_examples=list(conflicts.values())[:100],
        multi_release_overrides_skipped=multi_release, packaging='JAVA_PROJECT_ZIP',
        limitations=['Only compiled bytecode under target/classes or build/classes and project module JAR/WAR files is analyzed; Java source is not compiled.',
            'Third-party classes bundled under dependency/lib folders are skipped.',
            'Module and multi-release metadata can be incomplete when only classes directories are included.',
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
