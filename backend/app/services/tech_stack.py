"""Bounded offline technology inventory from bytecode and archive metadata."""
from collections import Counter
from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET


def _maven_dependencies(content):
    try:
        root = ET.fromstring(content)
    except (ET.ParseError, ValueError):
        return []
    ns = {'m': 'http://maven.apache.org/POM/4.0.0'}
    rows = []
    for item in root.findall('.//m:dependencies/m:dependency', ns):
        group = (item.findtext('m:groupId', default='', namespaces=ns) or '').strip()
        artifact = (item.findtext('m:artifactId', default='', namespaces=ns) or '').strip()
        version = (item.findtext('m:version', default='', namespaces=ns) or '').strip()
        if group and artifact:
            exact = bool(version and not re.search(r'[${}]', version))
            rows.append(dict(group_id=group,artifact_id=artifact,version=version or None,
                version_status='EXACT' if exact else 'UNRESOLVED_OR_INHERITED'))
    return rows


def inspect_artifact(path: Path, classes_dir: Path, static: dict) -> dict:
    majors = Counter()
    for file in classes_dir.rglob('*.class'):
        try:
            with file.open('rb') as stream:
                header = stream.read(8)
            if len(header) == 8 and header[:4] == b'\xca\xfe\xba\xbe':
                majors[int.from_bytes(header[6:8], 'big')] += 1
        except OSError:
            continue
    java_versions = sorted({max(1, major - 44) for major in majors})
    metadata, dependency_names, manifests, pom_files = [], set(), [], []
    has_maven_descriptor = False
    has_gradle_descriptor = False
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                name = info.filename.replace('\\','/')
                lowered = name.casefold()
                if lowered == 'pom.xml' or (lowered.endswith('/pom.xml') and ('meta-inf/maven/' in lowered or lowered.count('/') <= 1)):
                    has_maven_descriptor = True
                if lowered in ('build.gradle','build.gradle.kts','settings.gradle','settings.gradle.kts') or (lowered.count('/') == 1 and lowered.split('/')[-1] in ('build.gradle','build.gradle.kts')):
                    has_gradle_descriptor = True
                if info.file_size > 2 * 1024 * 1024:
                    continue
                if lowered.endswith('/meta-inf/manifest.mf') or lowered == 'meta-inf/manifest.mf':
                    manifests.append(archive.read(info).decode('utf-8','replace'))
                if lowered.endswith('/pom.xml') or lowered == 'pom.xml':
                    pom_files.append(archive.read(info))
                if lowered.endswith('.jar') and ('/lib/' in lowered or lowered.startswith('lib/')):
                    dependency_names.add(Path(name).name)
                if lowered.endswith('/pom.properties') or lowered == 'meta-inf/maven/pom.properties':
                    metadata.append(archive.read(info).decode('utf-8','replace'))
    except (OSError, zipfile.BadZipFile):
        pass
    dependencies = {}
    for content in pom_files[:50]:
        for row in _maven_dependencies(content):
            key = row['group_id'] + ':' + row['artifact_id']
            dependencies.setdefault(key,row)
    for content in metadata[:500]:
        values = dict(re.findall(r'^\s*(groupId|artifactId|version)\s*=\s*(.*?)\s*$',content,re.M))
        if values.get('groupId') and values.get('artifactId') and values.get('version'):
            row=dict(group_id=values['groupId'],artifact_id=values['artifactId'],version=values['version'],version_status='EXACT')
            dependencies.setdefault(values['groupId']+':'+values['artifactId'],row)
    parsed_jars=[]
    for name in sorted(dependency_names):
        match=re.fullmatch(r'(.+?)-([0-9][A-Za-z0-9_.+\-]*)\.jar',name)
        if match:
            parsed_jars.append(dict(artifact_id=match.group(1),version=match.group(2),source='ARCHIVE_LIBRARY_NAME'))
    all_deps=list(dependencies.values())
    spring_boot_versions={d['version'] for d in all_deps if d['group_id']=='org.springframework.boot' and d['artifact_id']=='spring-boot'}
    for manifest in manifests:
        match=re.search(r'(?im)^Spring-Boot-Version:\s*([^\r\n]+)',manifest)
        if match:spring_boot_versions.add(match.group(1).strip())
    if not spring_boot_versions:
        spring_boot_versions.update(row['version'] for row in parsed_jars if row['artifact_id'].startswith('spring-boot-'))
    external_names={edge.get('target','') for edge in static.get('external_edges',[])}
    javax_types=sorted(name for name in external_names if name.startswith(('javax.','javax/')))
    jakarta_types=sorted(name for name in external_names if name.startswith(('jakarta.','jakarta/')))
    frameworks=[]
    if spring_boot_versions:frameworks.append(dict(name='Spring Boot',versions=sorted(spring_boot_versions),evidence='Archive manifest, Maven metadata, or bundled library filename.'))
    build_tools=[]
    if has_maven_descriptor:
        build_tools.append(dict(name='Maven',evidence='pom.xml found in uploaded archive.'))
    if has_gradle_descriptor:
        build_tools.append(dict(name='Gradle',evidence='Gradle build/settings descriptor found in uploaded archive.'))
    if dependency_names:
        build_tools.append(dict(name='Packaged Java libraries',evidence='Library JARs found in the archive. This does not identify the build tool.'))
    return dict(schema_version='tech-inventory-1',status='PARTIAL' if all_deps or parsed_jars or majors else 'UNAVAILABLE',
        bytecode=dict(class_count=sum(majors.values()),major_versions=dict(sorted(majors.items())),java_targets=java_versions,
            mapping_note='Class-file major version N maps to Java N-44 for supported modern bytecode versions.'),
        build_tools=build_tools,frameworks=frameworks,dependencies=all_deps,bundled_libraries=parsed_jars[:1000],
        dependency_inventory_status='EXACT_AND_PARTIAL' if all_deps else 'ARCHIVE_FILENAMES_ONLY' if parsed_jars else 'NOT_FOUND',
        namespace_usage=dict(javax_count=len(javax_types),jakarta_count=len(jakarta_types),javax_examples=javax_types[:20],jakarta_examples=jakarta_types[:20]),
        # Filled by app.insight.lifecycle.compatibility_summary in the pipeline from the dated rules file.
        compatibility=dict(java_lifecycle='PENDING_RULE_EVALUATION',framework_lifecycle='PENDING_RULE_EVALUATION',deprecated_apis='SEE_TECHNICAL_DEBT_RULE_DEPRECATED_API',
            vulnerability_advisories='OUT_OF_SCOPE',reason='Lifecycle status is evaluated against app/insight/rules/lifecycle-rules.yaml; vulnerability advisories are not assessed.'),
        limitations=['Maven property and parent-managed versions may be unresolved in the artifact metadata.',
            'Project ZIP files containing only target/classes may not include build descriptors or dependency versions.',
            'Bundled library filenames are not a complete dependency lockfile.',
            'End-of-life status comes from a dated rules file and is only as current as its review date; vulnerability advisories are not assessed.'])
