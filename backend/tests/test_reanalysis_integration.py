"""Real local Docker -> bounded artifact capture -> existing analysis worker.

The candidate edit is a hand-authored controlled fixture, not a generated refactor.
"""
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import pytest
from app.config import Settings
from app.models import Artifact, AnalysisRun
from app.transformation import sandbox
from app.transformation.architecture import compare
from test_runtime import live


@pytest.mark.skipif(os.getenv('ARCHINTEL_RUN_DOCKER_TESTS') != '1', reason='Requires pinned local build image and static scanner')
def test_real_candidate_artifacts_produce_measured_dependency_diff(live, tmp_path):
    config = live.app.state.config
    config.build_sandbox_image = Settings().build_sandbox_image
    assert sandbox.capabilities(config)['available']
    snapshots = []
    captures = []
    for kind in ('baseline', 'candidate'):
        source = tmp_path / kind
        shutil.copytree(Path(__file__).parent/'fixtures/reanalysis', source)
        if kind == 'candidate':
            (source/'src/main/java/local/archintel/App.java').write_text(
                'package local.archintel; public class App { public int value() { return 1; } }\n', encoding='utf-8')
        task = SimpleNamespace(document={'artifact_path': 'target/application.jar'})
        target = tmp_path/'captures'/(kind+'.jar')
        result = sandbox.run(config, task, str(uuid4()), source, target)
        assert result['tests'] == 1 and result['cases'][0]['passed']
        captures.append(result)
        with live.app.state.sessions() as db:
            artifact = Artifact(application_id=live.app_id, filename=target.name, path=str(target),
                sha256=result['artifact_sha256'], size=target.stat().st_size)
            db.add(artifact); db.flush()
            run = AnalysisRun(application_id=live.app_id, artifact_id=artifact.id)
            db.add(run); db.commit(); identity = run.id
        live.app.state.worker.run(identity)
        with live.app.state.sessions() as db:
            run = db.get(AnalysisRun, identity)
            assert run.status == 'COMPLETED', run.error_message
            snapshots.append(run.result)
    assert captures[0]['artifact_sha256'] != captures[1]['artifact_sha256']
    diff = compare(*snapshots)
    assert diff['eligibility'] == 'ELIGIBLE'
    assert ['local.archintel.App', 'local.archintel.Value', 'METHOD_CALL'] in diff['edges']['removed']
    assert diff['classes']['removed'] == []
    assert diff['classes']['added'] == []
    assert diff['cycles']['added'] == []


@pytest.mark.skipif(os.getenv('ARCHINTEL_RUN_DOCKER_TESTS') != '1', reason='Requires pinned local build image')
def test_real_ast_recipe_compiles_and_preserves_contract(live, tmp_path):
    config=live.app.state.config;config.build_sandbox_image=Settings().build_sandbox_image
    source=tmp_path/'recipe';shutil.copytree(Path(__file__).parent/'fixtures/reanalysis',source)
    (source/'src/main/java/local/archintel/App.java').write_text(
        'package local.archintel; import java.util.List; public class App { public int value() { return 1; } public List<String> labels() { return List.of("ok"); } }', encoding='utf-8')
    task=SimpleNamespace(document={'artifact_path':'target/application.jar'})
    generated=sandbox.refactor(config,task,str(uuid4()),source,'src/main/java/local/archintel/App.java',
        'src/main/java/local/archintel/AppBoundary.java','AppBoundary',['value','labels'])
    (source/'src/main/java/local/archintel/App.java').write_text(generated['contents'][0],encoding='utf-8')
    (source/'src/main/java/local/archintel/AppBoundary.java').write_text(generated['contents'][1],encoding='utf-8')
    result=sandbox.run(config,task,str(uuid4()),source,tmp_path/'recipe.jar')
    assert result['tests']==1 and result['failures']==0 and result['errors']==0
    assert result['cases']==[dict(name='local.archintel.AppTest#preservesValue',passed=True)]


@pytest.mark.skipif(os.getenv('ARCHINTEL_RUN_DOCKER_TESTS') != '1', reason='Requires pinned build and security images')
def test_real_security_scanner_detects_weak_crypto_and_accepts_clean_fixture(tmp_path):
    from app.transformation.security import scan
    config=Settings()
    for unsafe in (False, True):
        source=tmp_path/('unsafe' if unsafe else 'clean')
        shutil.copytree(Path(__file__).parent/'fixtures/reanalysis',source)
        if unsafe:
            (source/'src/main/java/local/archintel/Weak.java').write_text(
                'package local.archintel; public class Weak { public byte[] hash(byte[] data) throws Exception { return java.security.MessageDigest.getInstance("MD5").digest(data); } }',encoding='utf-8')
        target=tmp_path/('unsafe.jar' if unsafe else 'clean.jar')
        sandbox.run(config,SimpleNamespace(document={'artifact_path':'target/application.jar'}),str(uuid4()),source,target)
        result=scan(config,target)
        assert result['state']==('FAIL' if unsafe else 'PASS'),result
        if unsafe: assert any('MD5' in f['rule'] for f in result['findings'])
        assert result['dependency_scan']['state']=='NOT_RUN'
