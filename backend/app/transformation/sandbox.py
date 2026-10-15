"""Fail-closed local Docker adapter. Customer code never runs in a host subprocess."""
import io
import json
import os
import shutil
import subprocess
import tarfile
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from app.services.ingestion import validate_archive, ArtifactError
from .workspace import relative, sha, no_links


class SandboxError(ValueError): pass


def binary():
    """Resolve Docker after a per-user Desktop install, including old API shells."""
    found = shutil.which('docker')
    if found:
        return found
    if os.name == 'nt':
        local = os.environ.get('LOCALAPPDATA')
        if local:
            candidate = Path(local) / 'Programs' / 'DockerDesktop' / 'resources' / 'bin' / 'docker.exe'
            if candidate.is_file():
                return str(candidate)
    return None


def command(*args):
    executable = binary()
    if not executable: raise SandboxError('SANDBOX_UNAVAILABLE')
    host = 'npipe:////./pipe/docker_engine' if os.name == 'nt' else 'unix:///var/run/docker.sock'
    return [executable, '--host', host, *args]


def call(args, timeout=20, limit=1048576):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(('DOCKER_', 'GIT_'))}
    process = subprocess.Popen(command(*args), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    output = bytearray(); overflow = []
    def read():
        while True:
            chunk = process.stdout.read(65536)
            if not chunk: break
            if len(output) + len(chunk) > limit:
                overflow.append(True); process.kill(); break
            output.extend(chunk)
    reader = threading.Thread(target=read, daemon=True); reader.start()
    try: code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill(); process.wait(); reader.join(3); raise SandboxError('BUILD_TIMEOUT')
    reader.join(3)
    if overflow: raise SandboxError('OUTPUT_LIMIT')
    if code: raise SandboxError('SANDBOX_COMMAND_FAILED')
    return bytes(output)


def capabilities(config):
    if not binary(): return dict(available=False, reason='Docker is not installed. Host build execution is disabled.')
    if not config.build_sandbox_image: return dict(available=False, reason='Configure a locally installed immutable BUILD_SANDBOX_IMAGE with Maven, JDK and offline dependencies.')
    try:
        info = json.loads(call(['info', '--format', '{{json .}}']))
        if info.get('OSType') != 'linux': raise SandboxError('LINUX_CONTAINERS_REQUIRED')
        image = json.loads(call(['image', 'inspect', config.build_sandbox_image]))[0]
        if image['Id'] != config.build_sandbox_image: raise SandboxError('IMAGE_ID_MISMATCH')
        if image.get('Config', {}).get('Volumes'): raise SandboxError('IMAGE_DECLARED_WRITABLE_VOLUMES')
        return dict(available=True, reason='Local pinned Linux build image available.', image_id=image['Id'])
    except (SandboxError, ValueError, KeyError, OSError): return dict(available=False, reason='Local Linux sandbox or pinned image is unavailable.')


def run_args(name, path, image, extra_mounts=()):
    args = ['run', '-d', '--name', name, '--pull=never', '--network=none', '--read-only', '--user=1000:1000',
        '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=256', '--memory=1024m', '--memory-swap=1024m', '--cpus=2',
        '--no-healthcheck', '--log-driver=none', '--tmpfs', '/tmp:rw,nosuid,size=64m,uid=1000,gid=1000',
        '--tmpfs', '/work:rw,nosuid,size=512m,uid=1000,gid=1000', '--mount', 'type=bind,source=' + str(path.resolve()) + ',target=/input,readonly',
    ]
    for source,target,readonly in extra_mounts:
        args.extend(['--mount','type=bind,source='+str(Path(source).resolve())+',target='+target+(',readonly' if readonly else '')])
    args.extend(['--entrypoint=/bin/sh', image, '-c', 'sleep 660'])
    return args


def reports(data):
    cases = []; failures = 0; errors = 0; skipped = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as archive:
        members = archive.getmembers()
        if len(members) > 2000: raise SandboxError('REPORT_LIMIT')
        for member in members:
            if not member.name.endswith('.xml'): continue
            if not member.isfile() or member.size > 1048576: raise SandboxError('INVALID_TEST_REPORT')
            raw = archive.extractfile(member).read()
            if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper(): raise SandboxError('INVALID_TEST_REPORT')
            root = ET.fromstring(raw)
            for case in root.iter('testcase'):
                failed = case.find('failure') is not None or case.find('error') is not None
                skip = case.find('skipped') is not None
                failures += int(case.find('failure') is not None); errors += int(case.find('error') is not None); skipped += int(skip)
                cases.append(dict(name=(case.get('classname', '') + '#' + case.get('name', ''))[:300], passed=not failed and not skip))
    if not cases: raise SandboxError('NO_TEST_RESULTS')
    return dict(tests=len(cases), failures=failures, errors=errors, skipped=skipped, cases=cases)


def run(config, task, run_id, path, artifact_target=None):
    available = capabilities(config)
    if not available['available']: raise SandboxError('SANDBOX_UNAVAILABLE')
    name = 'archintel-build-' + run_id
    artifact = relative(task.document['artifact_path'])
    if ',' in str(path): raise SandboxError('UNSUPPORTED_MOUNT_PATH')
    try:
        call(run_args(name, path, config.build_sandbox_image))
        # Both scripts are fixed server-owned commands; repository wrappers are never run on the host.
        call(['exec', name, '/bin/sh', '-c', 'cp -R /input/. /work/ && cd /work && HOME=/work mvn -o -B -Dmaven.repo.local=/opt/m2/repository -Dmaven.test.failure.ignore=false -DskipTests=false -Dmaven.test.skip=false package'], timeout=config.build_timeout_seconds, limit=2097152)
        # Stream through fixed in-container tools. Docker Desktop's archive API
        # cannot reliably read files created on a container tmpfs.
        report_archive = call(['exec', name, 'tar', '-C', '/work/target/surefire-reports', '-cf', '-', '.'], limit=8388608)
        result = reports(report_archive)
        call(['exec', name, '/bin/sh', '-c', 'test -f "$1" && test ! -L "$1"', 'archintel-check', '/work/' + artifact])
        content = call(['exec', name, 'cat', '/work/' + artifact], limit=33554433)
        if len(content) > 33554432: raise SandboxError('INVALID_BUILD_ARTIFACT')
        result['artifact_sha256'] = sha(content)
        if artifact_target is not None:
            target = Path(artifact_target)
            no_links(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            created = False
            try:
                with target.open('xb') as output:
                    created = True
                    output.write(content)
                validate_archive(target, config)
            except (OSError, ArtifactError):
                if created: target.unlink(missing_ok=True)
                raise SandboxError('INVALID_BUILD_ARTIFACT')
            result['artifact_capture'] = dict(path=str(target), size=len(content), sha256=result['artifact_sha256'])
        result['image_id'] = config.build_sandbox_image
        result['network'] = 'NONE'; result['isolation'] = 'LOCAL_LINUX_CONTAINER'
        return result
    finally:
        try: call(['rm', '-f', '-v', name], timeout=15)
        except (SandboxError, OSError): pass


def refactor(config, task, run_id, path, implementation, interface, interface_name, methods):
    available = capabilities(config)
    if not available['available']: raise SandboxError('SANDBOX_UNAVAILABLE')
    implementation, interface = relative(implementation), relative(interface)
    name = 'archintel-refactor-' + run_id
    try:
        call(run_args(name, path, config.build_sandbox_image))
        classpath = '/opt/archintel/refactor/refactor.jar:/opt/archintel/refactor/lib/*'
        call(['exec', '-e', 'ARCHINTEL_RECIPE_METHODS=' + ','.join(methods), name, 'java', '-cp', classpath,
              'local.archintel.JavaRefactor', 'INTRODUCE_INTERFACE', '/input/' + implementation,
              '/work/modified.java', '/work/interface.java', interface_name], timeout=60, limit=65536)
        changed = call(['exec', name, 'cat', '/work/modified.java'], limit=262145)
        added = call(['exec', name, 'cat', '/work/interface.java'], limit=262145)
        if not changed or not added or len(changed) > 262144 or len(added) > 262144:
            raise SandboxError('RECIPE_OUTPUT_LIMIT')
        try: contents = [changed.decode('utf-8'), added.decode('utf-8')]
        except UnicodeDecodeError: raise SandboxError('INVALID_RECIPE_OUTPUT')
        return dict(recipe='INTRODUCE_INTERFACE', recipe_version='1.0.1', parser='JavaParser', parser_version='3.28.2', interface_name=interface_name,
                    image_id=config.build_sandbox_image, implementation_file=implementation,
                    interface_file=interface, methods=list(methods), contents=contents)
    finally:
        try: call(['rm', '-f', '-v', name], timeout=15)
        except (SandboxError, OSError): pass
