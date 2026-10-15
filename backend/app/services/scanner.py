"""jQAssistant scans into a job-owned Neo4j store, then a read-only exporter reads it."""
import json
import os
from pathlib import Path
import subprocess
import yaml
from app.config import Settings, ROOT


class ScannerError(RuntimeError):
    pass


class JQAssistantScanner:
    def __init__(self, settings: Settings):
        self.settings = settings

    def command(self) -> list[str]:
        java, jqa = self.settings.runtime_paths()
        executable = java / 'bin' / ('java.exe' if os.name == 'nt' else 'java')
        jars = list((jqa / 'lib').glob('com.buschmais.jqassistant.cli-jqassistant-commandline-neo4jv5-*.jar'))
        if not executable.exists() or not jars or not (ROOT / '.runtime/exporter/ExportGraph.class').exists():
            raise ScannerError('Scanner runtime is incomplete. Run the setup script and build the graph exporter.')
        return [str(executable), '-Xmx1536m', '-XX:ActiveProcessorCount=2',
            '--add-opens=java.base/java.nio=ALL-UNNAMED', '--add-opens=java.base/java.lang=ALL-UNNAMED',
            '--add-opens=java.base/sun.nio.ch=ALL-UNNAMED', '-jar', str(jars[0])]

    def available(self) -> bool:
        try:
            self.command()
            return True
        except ScannerError:
            return False

    def scan(self, work: Path, class_dir: Path, on_stage) -> tuple[list[dict], list[dict]]:
        configuration = {'jqassistant': {
            'store': {'uri': (work / 'store').resolve().as_uri(), 'embedded': {
                'connector-enabled': False, 'apoc-enabled': False,
                'neo4j-properties': {'server.memory.pagecache.size': '256m'}}},
            'scan': {'reset': False, 'continue-on-error': False}}}
        (work / '.jqassistant.yml').write_text(yaml.safe_dump(configuration), encoding='utf-8')
        command = self.command()
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        try:
            result = subprocess.run(command + ['scan', '-f', 'java:classpath::' + str(class_dir)], cwd=work,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=self.settings.scan_timeout_seconds,
                creationflags=flags)
        except subprocess.TimeoutExpired as error:
            raise ScannerError('jQAssistant exceeded the scan time limit.') from error
        if result.returncode:
            raise ScannerError('jQAssistant scan failed. Verify Java/scanner versions and artifact compatibility.')
        on_stage('GRAPH_EXTRACTION', 30)
        _, jqa = self.settings.runtime_paths()
        owned_types = {p.relative_to(class_dir).as_posix()[:-6].replace('/', '.') for p in class_dir.rglob('*.class')}
        owned_file = work / 'owned-types.json'
        owned_file.write_text(json.dumps(sorted(owned_types)), encoding='utf-8')
        export_command = command[:-2] + ['-cp', str(ROOT / '.runtime/exporter') + os.pathsep + str(jqa / 'lib/*'),
            'ExportGraph', str(work / 'store'), str(self.settings.max_classes), str(self.settings.max_edges), str(owned_file)]
        try:
            export = subprocess.run(export_command, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=self.settings.scan_timeout_seconds, creationflags=flags)
        except subprocess.TimeoutExpired as error:
            raise ScannerError('Graph extraction exceeded the time limit.') from error
        if export.returncode:
            raise ScannerError('Graph export failed or the dependency limit was exceeded.')
        marker = b'ARCHINTEL_GRAPH_JSON:'
        lines = [line[len(marker):] for line in export.stdout.splitlines() if line.startswith(marker)]
        if not lines:
            raise ScannerError('Graph exporter returned no structured result.')
        data = json.loads(lines[-1])
        rows = [r for r in data['classes'] if r['fqn'] in owned_types]
        if not rows:
            raise ScannerError('Scanner returned no compiled Java types.')
        if len(rows) > self.settings.max_classes:
            raise ScannerError('Scanned class count exceeds the limit.')
        classes = [dict(fqn=r['fqn'], simple_name=r['fqn'].rsplit('.',1)[-1],
            package_name=r['fqn'].rpartition('.')[0] or '(default)',
            class_type='INTERFACE' if 'Interface' in r['labels'] else 'ENUM' if 'Enum' in r['labels'] else 'CLASS',
            is_abstract=bool(r['properties'].get('abstract',False) or 'Abstract' in r['labels']),
            is_interface='Interface' in r['labels'], method_count=r['method_count'],
            field_count=r['field_count'], annotations=r['annotations'], methods=r.get('methods',[])) for r in rows if r['fqn']]
        primitive_types = {'boolean','byte','char','short','int','long','float','double','void'}
        edges = []
        for edge in data['edges']:
            if edge['source'] not in owned_types or not edge['target']:
                continue
            target = edge['target']
            while target.endswith('[]'):
                target = target[:-2]
            if target not in primitive_types:
                edges.append(dict(edge, target=target))
        typed = {(e['source'],e['target']) for e in edges if e['dependency_type']!='OTHER'}
        edges = [e for e in edges if e['dependency_type']!='OTHER' or (e['source'],e['target']) not in typed]
        return classes, edges
