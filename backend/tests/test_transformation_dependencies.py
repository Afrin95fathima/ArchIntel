import json
import zipfile
from datetime import datetime, timezone, timedelta
import pytest
from app.transformation.dependencies import metadata, parse_report
from app.transformation.sandbox import SandboxError


def test_dependency_database_requires_recent_trusted_timestamp():
    now=datetime.now(timezone.utc)
    assert metadata(json.dumps({'UpdatedAt':now.isoformat()}).encode(),now)['sha256']
    for updated in (now-timedelta(days=8),now+timedelta(hours=1)):
        with pytest.raises(SandboxError): metadata(json.dumps({'UpdatedAt':updated.isoformat()}).encode(),now)
    with pytest.raises(SandboxError): metadata(b'{}',now)


def test_empty_dependency_inventory_never_passes():
    result=parse_report(b'{"SchemaVersion":2,"Results":[]}')
    assert result['state']=='INCONCLUSIVE' and result['reason']=='NO_PACKAGES_IDENTIFIED'


def test_dependency_findings_are_preserved_even_without_a_fix():
    result=parse_report(json.dumps(dict(SchemaVersion=2,Results=[dict(Type='jar',Packages=[dict(Name='sample:unsafe',Version='1.0')],
        Vulnerabilities=[dict(VulnerabilityID='CVE-2021-44228',PkgName='sample:unsafe',InstalledVersion='1.0',Severity='CRITICAL')])])).encode())
    assert result['state']=='FAIL' and result['findings'][0]['fixed']==''
    assert result['coverage']=='PACKAGED_JAVA_ONLY'


def test_spring_boot_archive_libraries_are_enumerated_without_path_extraction(tmp_path):
    from app.transformation.dependencies import _archive_libraries
    artifact=tmp_path/'app.jar'
    with zipfile.ZipFile(artifact,'w') as archive:
        archive.writestr('BOOT-INF/lib/spring-core.jar',b'jar-bytes')
        archive.writestr('BOOT-INF/classes/App.class',b'\xca\xfe\xba\xbe')
    rows=_archive_libraries(artifact,'SPRING_BOOT')
    assert [row.filename for row in rows]==['BOOT-INF/lib/spring-core.jar']
    with zipfile.ZipFile(artifact,'a') as archive: archive.writestr('BOOT-INF/lib/../escape.jar',b'unsafe')
    with pytest.raises(SandboxError,match='DEPENDENCY_ARCHIVE_UNSAFE_PATH'):
        _archive_libraries(artifact,'SPRING_BOOT')


def test_real_scan_invokes_rootfs_java_archive_analyzer(tmp_path, monkeypatch):
    import hashlib
    from types import SimpleNamespace
    from datetime import datetime, timezone
    from app.transformation import dependencies
    cache=tmp_path/'cache';(cache/'db').mkdir(parents=True);(cache/'java-db').mkdir()
    stamp=datetime.now(timezone.utc).isoformat().replace('+00:00','Z').encode()
    for kind in ('db','java-db'):
        (cache/kind/'metadata.json').write_bytes(json.dumps({'UpdatedAt':stamp.decode()}).encode())
    artifact=tmp_path/'app.jar'
    with zipfile.ZipFile(artifact,'w') as archive:
        archive.writestr('BOOT-INF/lib/logback.jar',b'fixture')
    monkeypatch.setattr(dependencies.sandbox,'capabilities',lambda config:dict(available=True))
    calls=[]
    report=json.dumps(dict(SchemaVersion=2,Results=[dict(Type='jar',Packages=[dict(Name='sample:lib',Version='1.0')],
        Vulnerabilities=[dict(VulnerabilityID='CVE-2024-0001',PkgName='sample:lib',InstalledVersion='1.0',FixedVersion='1.1',Severity='HIGH')])])).encode()
    def fake_call(args,**kwargs):
        calls.append(args)
        if args[2:4]==['trivy','--version']:
            return b'{"Version":"0.75.0"}'
        if args[2]=='cat':
            return json.dumps({'UpdatedAt':stamp.decode()}).encode()
        if args[2:4]==['trivy','--cache-dir']:
            return report
        return b''
    monkeypatch.setattr(dependencies.sandbox,'call',fake_call)
    config=SimpleNamespace(dependency_sandbox_image='sha256:'+'1'*64,dependency_database_dir=cache)
    result=dependencies.scan(config,artifact,{'packaging':'SPRING_BOOT'})
    scan_call=next(call for call in calls if 'rootfs' in call)
    assert scan_call[scan_call.index('rootfs')]=='rootfs'
    assert result['state']=='FAIL' and result['findings'][0]['id']=='CVE-2024-0001'
