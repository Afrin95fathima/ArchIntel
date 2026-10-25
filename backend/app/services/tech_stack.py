"""Bounded offline technology inventory from bytecode and archive metadata."""
from collections import Counter
from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET


MAX_POMS = 500
# Framework families named in the inventory when their main artifact is a resolved dependency (inventory only; support
# status comes from lifecycle-rules.yaml).
FRAMEWORK_ARTIFACTS = {
    'org.springframework:spring-core': 'Spring Framework', 'org.eclipse.jetty:jetty-server': 'Jetty', 'org.apache.tomcat.embed:tomcat-embed-core': 'Tomcat',
    'com.google.inject:guice': 'Guice', 'org.jboss.resteasy:resteasy-core': 'RESTEasy', 'org.glassfish.jersey.core:jersey-server': 'Jersey',
    'org.jooq:jooq': 'jOOQ', 'org.hibernate.orm:hibernate-core': 'Hibernate ORM', 'org.hibernate:hibernate-core': 'Hibernate ORM',
    'org.apache.shiro:shiro-core': 'Apache Shiro', 'org.liquibase:liquibase-core': 'Liquibase', 'org.flywaydb:flyway-core': 'Flyway',
    'io.quarkus:quarkus-core': 'Quarkus', 'io.micronaut:micronaut-core': 'Micronaut', 'io.dropwizard:dropwizard-core': 'Dropwizard',
    'com.fasterxml.jackson.core:jackson-databind': 'Jackson',
}
PROPERTY = re.compile(r'\$\{([^}]+)\}')


def _local(tag):
    return tag.rsplit('}', 1)[-1]


def _child(element, name):
    return next((c for c in element if _local(c.tag) == name), None) if element is not None else None


def _text(element, name):
    child = _child(element, name)
    return (child.text or '').strip() if child is not None and child.text else ''


def _dependency_list(container):
    rows = []
    for item in (c for c in (container if container is not None else []) if _local(c.tag) == 'dependency'):
        group, artifact = _text(item, 'groupId'), _text(item, 'artifactId')
        if group and artifact:
            rows.append(dict(group_id=group, artifact_id=artifact, version=_text(item, 'version') or None,
                             scope=_text(item, 'scope') or 'compile', type=_text(item, 'type') or 'jar'))
    return rows


def _pom(content):
    """Coordinates, parent, properties, managed and declared dependencies of one pom.xml; None when unreadable."""
    try:
        root = ET.fromstring(content)
    except (ET.ParseError, ValueError):
        return None
    if _local(root.tag) != 'project':
        return None
    parent = _child(root, 'parent')
    properties = _child(root, 'properties')
    management = _child(_child(root, 'dependencyManagement'), 'dependencies')
    group = _text(root, 'groupId') or _text(parent, 'groupId')
    return dict(group_id=group, artifact_id=_text(root, 'artifactId'), version=_text(root, 'version') or _text(parent, 'version'),
                parent=(_text(parent, 'groupId'), _text(parent, 'artifactId')) if parent is not None else None, parent_version=_text(parent, 'version'),
                properties={_local(p.tag): (p.text or '').strip() for p in (properties if properties is not None else [])},
                managed=_dependency_list(management), dependencies=_dependency_list(_child(root, 'dependencies')))


def _maven_dependencies(contents):
    """Declared dependencies of every module pom in the archive, with versions resolved through the parent chain inside it.

    Properties, project coordinates and dependencyManagement of parents present in the archive are applied. A version managed
    by an imported BOM, or by a parent that is not in the archive, cannot be resolved offline and stays UNRESOLVED_OR_INHERITED.
    Modules of the project itself and test-scoped dependencies are not part of the shipped dependency inventory.
    """
    poms = [p for p in (_pom(c) for c in contents) if p and p['artifact_id']]
    by_coordinates = {(p['group_id'], p['artifact_id']): p for p in poms}

    def chain(pom):
        seen = []
        while pom is not None and pom not in seen and len(seen) < 20:
            seen.append(pom)
            pom = by_coordinates.get(pom['parent']) if pom['parent'] else None
        return seen

    def properties(pom):
        values = {}
        for item in reversed(chain(pom)):
            values.update(item['properties'])
        values.update({'project.version': pom['version'], 'pom.version': pom['version'], 'version': pom['version'],
                       'project.groupId': pom['group_id'], 'project.artifactId': pom['artifact_id'], 'project.parent.version': pom['parent_version']})
        return values

    def interpolate(value, values):
        for _ in range(10):
            if not value or '${' not in value:
                break
            value = PROPERTY.sub(lambda m: values.get(m.group(1), m.group(0)), value)
        return value

    def managed_version(ancestors, values, group, artifact, depth=0):
        """dependencyManagement of the parent chain; an imported BOM found in the archive is read with its own properties."""
        for pom in ancestors:
            for item in pom['managed']:
                coordinates = (interpolate(item['group_id'], values), interpolate(item['artifact_id'], values))
                if item['scope'] == 'import':
                    bom = by_coordinates.get(coordinates)
                    if bom is not None and depth < 5:
                        found, source = managed_version(chain(bom), properties(bom), group, artifact, depth + 1)
                        if found:
                            return found, 'IMPORTED_BOM_IN_ARCHIVE' if source == 'PARENT_DEPENDENCY_MANAGEMENT' else source
                elif coordinates == (group, artifact) and item['version']:
                    return interpolate(item['version'], values), 'PARENT_DEPENDENCY_MANAGEMENT'
        return None, 'IMPORTED_BOM_OR_EXTERNAL_PARENT'

    rows, internal_count, test_count = {}, 0, 0
    for pom in poms:
        values, ancestors = properties(pom), chain(pom)
        for dependency in pom['dependencies']:
            group, artifact = interpolate(dependency['group_id'], values), interpolate(dependency['artifact_id'], values)
            if (group, artifact) in by_coordinates:
                internal_count += 1
                continue
            if dependency['scope'] == 'test':
                test_count += 1
                continue
            declared = dependency['version']
            if declared:
                version, source = interpolate(declared, values), 'DECLARED'
            else:
                version, source = managed_version(ancestors, values, group, artifact)
            version = version or None
            exact = bool(version and '${' not in version)
            row = rows.setdefault((group, artifact, version if exact else None), dict(group_id=group, artifact_id=artifact, version=version if exact else None,
                version_status='EXACT' if exact else 'UNRESOLVED_OR_INHERITED', version_source=source if exact else 'IMPORTED_BOM_OR_EXTERNAL_PARENT',
                scope=dependency['scope'], modules=0))
            row['modules'] += 1
    return list(rows.values()), dict(pom_count=len(poms), internal_module_references=internal_count, test_scoped_skipped=test_count)


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
    pom_rows, pom_stats = _maven_dependencies(pom_files[:MAX_POMS])
    resolved = {(r['group_id'], r['artifact_id']) for r in pom_rows if r['version']}
    for row in sorted(pom_rows, key=lambda r: (r['group_id'], r['artifact_id'], r['version'] or '')):
        if not row['version'] and (row['group_id'], row['artifact_id']) in resolved:
            continue
        # One row per resolved version: modules may pin different versions of the same library.
        dependencies.setdefault(row['group_id'] + ':' + row['artifact_id'] + (':' + row['version'] if row['version'] else ''), row)
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
    found = {}
    for d in all_deps:
        name = FRAMEWORK_ARTIFACTS.get(f"{d['group_id']}:{d['artifact_id']}")
        if name and d.get('version'):
            found.setdefault(name, set()).add(d['version'])
    for name, versions in sorted(found.items()):
        frameworks.append(dict(name=name, versions=sorted(versions), evidence='Resolved Maven dependency metadata.'))
    build_tools=[]
    if has_maven_descriptor:
        build_tools.append(dict(name='Maven',evidence='pom.xml found in uploaded archive.'))
    if has_gradle_descriptor:
        build_tools.append(dict(name='Gradle',evidence='Gradle build/settings descriptor found in uploaded archive.'))
    if dependency_names:
        build_tools.append(dict(name='Packaged Java libraries',evidence='Library JARs found in the archive. This does not identify the build tool (Maven or Gradle).'))
    return dict(schema_version='tech-inventory-1',status='PARTIAL' if all_deps or parsed_jars or majors else 'UNAVAILABLE',
        bytecode=dict(class_count=sum(majors.values()),major_versions=dict(sorted(majors.items())),java_targets=java_versions,
            mapping_note='Class-file major version N maps to Java N-44 for supported modern bytecode versions.'),
        build_tools=build_tools,frameworks=frameworks,dependencies=all_deps,bundled_libraries=parsed_jars[:1000],
        dependency_inventory_status='EXACT_AND_PARTIAL' if all_deps else 'ARCHIVE_FILENAMES_ONLY' if parsed_jars else 'NOT_FOUND',
        maven_resolution=pom_stats,
        namespace_usage=dict(javax_count=len(javax_types),jakarta_count=len(jakarta_types),javax_examples=javax_types[:20],jakarta_examples=jakarta_types[:20]),
        # Filled by app.insight.lifecycle.compatibility_summary in the pipeline from the dated rules file.
        compatibility=dict(java_lifecycle='PENDING_RULE_EVALUATION',framework_lifecycle='PENDING_RULE_EVALUATION',deprecated_apis='SEE_TECHNICAL_DEBT_RULE_DEPRECATED_API',
            vulnerability_advisories='OUT_OF_SCOPE',reason='Lifecycle status is evaluated against app/insight/rules/lifecycle-rules.yaml; vulnerability advisories are not assessed.'),
        limitations=['Maven versions are resolved through properties and dependencyManagement of parent poms inside the archive; versions managed by an imported BOM or an external parent stay unresolved.',
            'Project ZIP files containing only target/classes have no build descriptors; include each module pom.xml (scripts/package-java-project-zip) to get dependency versions.',
            'Bundled library filenames are not a complete dependency lockfile such as pom.xml.',
            'End-of-life status comes from lifecycle-rules.yaml and is only as current as its review date; vulnerability advisories are not assessed.'])
