"""Server-owned Java security analysis in an offline, read-only sandbox.

Reports contain bounded finding identifiers, not source text or raw tool logs.
SAST alone never substitutes for dependency vulnerability scanning.
"""
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from uuid import uuid4
from . import sandbox, workspace, dependencies
from app.services.ingestion import validate_archive

RULE_VERSION = 'java-security-1'
TOOL_VERSION = '4.10.4'
PLUGIN_VERSION = '1.14.0'


def parse_report(raw):
    if not raw or len(raw) > 4194304 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise sandbox.SandboxError('INVALID_SECURITY_REPORT')
    try:
        root = ET.fromstring(raw)
        if root.tag != 'BugCollection' or root.get('version') != TOOL_VERSION:
            raise ValueError()
        summary = root.find('FindBugsSummary')
        errors = root.find('Errors')
        if summary is None or int(summary.get('total_classes', '0')) <= 0 or errors is None:
            raise ValueError()
        incomplete = int(errors.attrib['errors']) > 0 or int(errors.attrib['missingClasses']) > 0 or bool(list(errors))
        findings = []
        for bug in root.findall('BugInstance'):
            if len(findings) >= 2000 or bug.get('category') != 'SECURITY': raise ValueError()
            name = bug.get('type', '')
            if not name or len(name) > 120: raise ValueError()
            priority = int(bug.get('priority', '0'))
            if priority not in (1, 2, 3): raise ValueError()
            cls = bug.find('Class')
            findings.append(dict(rule=name, priority=priority,
                class_name=(cls.get('classname', '') if cls is not None else '')[:300]))
        # Require a complete report, including zero-finding runs.
        if int(summary.get('total_bugs', '-1')) != len(findings): raise ValueError()
        return dict(state='INCONCLUSIVE' if incomplete else ('FAIL' if findings else 'PASS'),
            findings=sorted(findings, key=lambda f:(f['rule'],f['class_name'],f['priority'])),
            analyzed_classes=int(summary.get('total_classes')), incomplete=incomplete,
            report_sha256=workspace.sha(raw), tool='SpotBugs', tool_version=TOOL_VERSION,
            plugin='FindSecBugs', plugin_version=PLUGIN_VERSION, rule_version=RULE_VERSION)
    except (KeyError, ValueError, TypeError, ET.ParseError):
        raise sandbox.SandboxError('INVALID_SECURITY_REPORT')


def scan(config, artifact):
    workspace.no_links(artifact)
    image = config.security_sandbox_image
    if not sandbox.capabilities(SimpleNamespace(build_sandbox_image=image))['available']:
        raise sandbox.SandboxError('SECURITY_SCANNER_UNAVAILABLE')
    before = workspace.sha(artifact.read_bytes())
    name = 'archintel-security-' + str(uuid4())
    try:
        sandbox.call(sandbox.run_args(name, artifact.parent, image))
        sandbox.call(['exec', name, 'java', '-Xmx512m', '-cp', '/opt/security/lib/*',
            'edu.umd.cs.findbugs.LaunchAppropriateUI', '-textui', '-effort:max', '-low',
            '-pluginList', '/opt/security/lib/findsecbugs-plugin-' + PLUGIN_VERSION + '.jar',
            '-include', '/opt/security/include.xml', '-xml:withMessages', '-output', '/work/security.xml',
            '/input/' + artifact.name], timeout=180, limit=65536)
        result = parse_report(sandbox.call(['exec', name, 'cat', '/work/security.xml'], limit=4194304))
        if workspace.sha(artifact.read_bytes()) != before: raise sandbox.SandboxError('SECURITY_ARTIFACT_CHANGED')
        try:
            dependency_manifest=validate_archive(artifact,config)
            dependency_scan=dependencies.scan(config,artifact,dependency_manifest)
        except (sandbox.SandboxError, OSError, ValueError):
            dependency_scan=dict(state='INCONCLUSIVE',reason='DEPENDENCY_SCANNER_FAILED',coverage='UNKNOWN')
        return dict(result, image_id=image, artifact_sha256=before, dependency_scan=dependency_scan)
    finally:
        try: sandbox.call(['rm', '-f', '-v', name], timeout=15)
        except (sandbox.SandboxError, OSError): pass
