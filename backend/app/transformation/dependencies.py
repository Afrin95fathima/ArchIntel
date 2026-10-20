"""Offline packaged-Java dependency vulnerability evidence.

This scans identified packages inside an artifact. It cannot attest to external
runtime dependencies of thin JARs, so coverage remains a separate acceptance gate.
"""
import json
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from pathlib import PurePosixPath
from types import SimpleNamespace
from uuid import uuid4
from . import sandbox, workspace

VERSION='0.75.0'


def metadata(raw, now=None):
    try:
        value=json.loads(raw)
        updated=datetime.fromisoformat(value['UpdatedAt'].replace('Z','+00:00'))
        clock=now or datetime.now(timezone.utc)
        if updated.tzinfo is None or updated > clock+timedelta(minutes=5) or clock-updated > timedelta(days=7):
            raise ValueError()
        return dict(updated_at=updated.isoformat(), sha256=workspace.sha(raw))
    except (KeyError, TypeError, ValueError): raise sandbox.SandboxError('DEPENDENCY_DATABASE_STALE_OR_INVALID')


def parse_report(raw):
    try:
        if not raw or len(raw)>4194304: raise ValueError()
        report=json.loads(raw)
        if report.get('SchemaVersion')!=2: raise ValueError()
        results=report.get('Results') or []
        packages=set(); findings=[]
        for result in results:
            if result.get('Type')!='jar': raise ValueError()
            for package in result.get('Packages') or []:
                name,version=package.get('Name'),package.get('Version')
                if not isinstance(name,str) or not isinstance(version,str) or not name or not version: raise ValueError()
                packages.add((name[:300],version[:100]))
            for finding in result.get('Vulnerabilities') or []:
                if len(findings)>=2000: raise ValueError()
                severity=finding.get('Severity')
                if severity not in ('UNKNOWN','LOW','MEDIUM','HIGH','CRITICAL'): raise ValueError()
                findings.append(dict(id=str(finding['VulnerabilityID'])[:120], package=str(finding['PkgName'])[:300],
                    installed=str(finding['InstalledVersion'])[:100], fixed=str(finding.get('FixedVersion',''))[:100],severity=severity))
        findings=list({(f['id'],f['package'],f['installed'],f['fixed'],f['severity']):f for f in findings}.values())
        return dict(state='FAIL' if findings else ('PASS' if packages else 'INCONCLUSIVE'),
            reason='IDENTIFIED_PACKAGES_ONLY' if packages else 'NO_PACKAGES_IDENTIFIED',
            packages=[dict(name=n,version=v) for n,v in sorted(packages)],findings=findings,
            report_sha256=workspace.sha(raw),coverage='PACKAGED_JAVA_ONLY', tool='Trivy', tool_version=VERSION)
    except (TypeError, ValueError, KeyError, AttributeError): raise sandbox.SandboxError('INVALID_DEPENDENCY_REPORT')


def _archive_libraries(artifact, packaging):
    prefixes = {'SPRING_BOOT': ('BOOT-INF/lib/',), 'WAR': ('WEB-INF/lib/',), 'JAR': ('lib/',)}.get(packaging, ())
    expanded = 0
    with zipfile.ZipFile(artifact) as archive:
        for row in archive.infolist():
            normalized=row.filename.replace('\\','/')
            parts=PurePosixPath(normalized)
            if parts.is_absolute() or '..' in parts.parts or ':' in normalized or '\x00' in normalized or stat.S_ISLNK(row.external_attr >> 16) or row.flag_bits & 1:
                raise sandbox.SandboxError('DEPENDENCY_ARCHIVE_UNSAFE_PATH')
        rows = [row for row in archive.infolist() if not row.is_dir() and row.filename.endswith('.jar') and
                any(row.filename.startswith(prefix) for prefix in prefixes)]
        if len(rows) > 1000: raise sandbox.SandboxError('DEPENDENCY_ARCHIVE_LIMIT')
        for row in rows:
            expanded += row.file_size
            if row.file_size <= 0 or expanded > 400 * 1024 * 1024:
                raise sandbox.SandboxError('DEPENDENCY_ARCHIVE_LIMIT')
    return rows


def scan(config, artifact, manifest=None):
    image=config.dependency_sandbox_image
    if not sandbox.capabilities(SimpleNamespace(build_sandbox_image=image))['available']:
        return dict(state='NOT_RUN',reason='DEPENDENCY_SCANNER_UNAVAILABLE',coverage='UNKNOWN')
    workspace.no_links(artifact); before=workspace.sha(artifact.read_bytes())
    packaging=(manifest or {}).get('packaging','JAR')
    database_dir=Path(config.dependency_database_dir).resolve()
    workspace.no_links(database_dir)
    if not database_dir.is_dir():
        return dict(state='NOT_RUN',reason='DEPENDENCY_DATABASE_NOT_PROVISIONED',coverage='UNKNOWN')
    name='archintel-dependencies-'+str(uuid4())
    stage=None
    try:
        stage=tempfile.TemporaryDirectory(prefix='archintel-dependencies-',dir=artifact.parent)
        root=Path(stage.name)
        rows=_archive_libraries(artifact,packaging)
        if rows:
            with zipfile.ZipFile(artifact) as archive:
                for index,row in enumerate(rows):
                    target=root/f'dependency-{index:04d}.jar'
                    with archive.open(row) as source, target.open('xb') as output:
                        shutil.copyfileobj(source,output,length=1024*1024)
        else:
            shutil.copyfile(artifact,root/'application.jar')
        sandbox.call(sandbox.run_args(name,root,image,extra_mounts=[(database_dir,'/opt/trivy-cache',True)]))
        version=json.loads(sandbox.call(['exec',name,'trivy','--version','--format','json']))
        if version.get('Version')!=VERSION: raise sandbox.SandboxError('DEPENDENCY_SCANNER_VERSION_MISMATCH')
        db={kind:metadata(sandbox.call(['exec',name,'cat','/opt/trivy-cache/'+kind+'/metadata.json'])) for kind in ('db','java-db')}
        # `filesystem` indexes project manifests but does not analyze packaged JARs
        # found in the staged directory. `rootfs` runs the Java archive analyzer.
        raw=sandbox.call(['exec',name,'trivy','--cache-dir','/opt/trivy-cache','rootfs',
            '--config','', '--ignorefile','', '--offline-scan','--skip-db-update','--skip-java-db-update',
            '--skip-version-check','--disable-telemetry','--scanners','vuln','--pkg-types','library',
            '--list-all-pkgs','--parallel','1','--format','json','--timeout','180s','/input'],timeout=190,limit=4194304)
        result=parse_report(raw)
        if workspace.sha(artifact.read_bytes())!=before: raise sandbox.SandboxError('DEPENDENCY_ARTIFACT_CHANGED')
        complete=packaging=='SPRING_BOOT' and len(rows)>0
        return dict(result,image_id=image,artifact_sha256=before,databases=db,
            coverage='PACKAGED_ARCHIVE_COMPLETE' if complete else 'PACKAGED_ARCHIVE_PARTIAL',
            runtime_inventory=dict(packaging=packaging,embedded_archives=len(rows),scanned_archives=max(1,len(rows)),
                complete=complete,limitations=['External launch classpaths, mounted libraries and runtime-injected dependencies are outside the JAR or WAR scan.']
                    if complete else ['Thin JARs and container-provided or externally resolved runtime dependencies are not proven by archive scanning.']))
    finally:
        try: sandbox.call(['rm','-f','-v',name],timeout=15)
        except (sandbox.SandboxError,OSError): pass
        if stage: stage.cleanup()
