import copy
import zipfile
from types import SimpleNamespace as Row
import pytest
from app.evidence.builder import digest
from app.transformation.validation import evaluate
from app.transformation import sandbox, workspace
from app.transformation.architecture import compare, expected_improvement
from app.transformation.models import TransformationTask, BuildRun
from app.models import AnalysisRun
from app.services.ingestion import file_hash
from test_runtime import live
from test_transformation import prepared, base, revision, proposed, refresh


def evidence():
    hashes = {'src/App.java': 'a'*64, 'src/AppTest.java': 'b'*64}
    task = Row(document=dict(complete_source_snapshot=True, expected_artifact_sha256='c'*64,
                             workspace=dict(baseline=hashes, current={**hashes, 'src/App.java': 'd'*64})))
    change = Row(fingerprint='e'*64)
    contract = Row(id='contract', document=dict(test_file='src/AppTest.java', test_file_sha256='b'*64,
                                               test_case='AppTest#contract', critical=True))
    contract.review = dict(hash=digest(contract.document))
    runs = []
    for kind, manifest in [('BASELINE', task.document['workspace']['baseline']), ('CANDIDATE', task.document['workspace']['current'])]:
        runs.append(Row(id=kind, kind=kind, state='PASSED', document=dict(
            input_sha256=digest(manifest), changeset_fingerprint=change.fingerprint,
            result=dict(image_id='sha256:'+'f'*64, artifact_sha256='c'*64, tests=1, failures=0, errors=0,
                        skipped=0, cases=[dict(name='AppTest#contract', passed=True)]))))
    return task, runs, [contract], change


def statuses(result): return {g['name']: g['status'] for g in result['gates']}


def test_passing_contracts_never_substitute_for_security_and_architecture():
    result = evaluate(*evidence())
    assert statuses(result)['REVIEWED_CONTRACT_COMPARISON'] == 'PASS'
    assert statuses(result)['GENERATED_CODE_SECURITY'] == 'NOT_RUN'
    assert statuses(result)['ARCHITECTURE_REANALYSIS'] == 'NOT_RUN'
    assert result['state'] == 'BLOCKED' and result['approval_eligible'] is False


@pytest.mark.parametrize('problem', ['changed_test','missing_case','duplicate_case','skipped_case','image',
                                    'source','changeset','review','latest_failure','removed_extra_case'])
def test_comparison_rejects_misleading_success(problem):
    task, runs, contracts, change = evidence()
    result = runs[-1].document['result']
    if problem == 'changed_test': task.document['workspace']['current']['src/AppTest.java'] = '9'*64
    if problem == 'missing_case': result['cases'] = []
    if problem == 'duplicate_case': result['cases'] *= 2
    if problem == 'skipped_case': result['cases'][0]['passed'] = False
    if problem == 'image': result['image_id'] = 'sha256:'+'8'*64
    if problem == 'source': runs[-1].document['input_sha256'] = '7'*64
    if problem == 'changeset': runs[-1].document.pop('changeset_fingerprint')
    if problem == 'review': contracts[0].review = None
    if problem == 'latest_failure':
        failed = copy.deepcopy(runs[-1]); failed.id = 'retry'; failed.state = 'FAILED'; runs.append(failed)
    if problem == 'removed_extra_case': runs[0].document['result']['cases'].append(dict(name='Other#test', passed=True))
    assert statuses(evaluate(task, runs, contracts, change))['REVIEWED_CONTRACT_COMPARISON'] == 'FAIL'


def test_missing_builds_are_not_run():
    task, _, contracts, change = evidence()
    result = evaluate(task, [], contracts, change)
    assert statuses(result)['BASELINE_BUILD'] == 'NOT_RUN'
    assert statuses(result)['CANDIDATE_BUILD'] == 'NOT_RUN'


def test_security_results_are_bound_and_never_replace_dependency_scans():
    task, runs, contracts, change = evidence()
    task.document['security_analysis']=dict(state='PASS', input_sha256=digest(task.document['workspace']['current']),
        build_id=runs[-1].id, changeset_fingerprint=change.fingerprint, artifact_sha256='c'*64)
    result=evaluate(task,runs,contracts,change)
    assert statuses(result)['JAVA_SECURITY_ANALYSIS']=='PASS'
    assert statuses(result)['GENERATED_CODE_SECURITY']=='NOT_RUN'
    for key in ('input_sha256','build_id','changeset_fingerprint','artifact_sha256'):
        modified=copy.deepcopy(task);modified.document['security_analysis'][key]='changed'
        assert statuses(evaluate(modified,runs,contracts,change))['JAVA_SECURITY_ANALYSIS']=='FAIL'


def test_architecture_diff_is_deterministic_and_does_not_guess_renames():
    before = dict(algorithm_version='1', configuration={'seed': 42}, summary={'class_count': 2},
        classes=[dict(id='a.A', domain_id='d1'), dict(id='a.Legacy', domain_id='d1')],
        edges=[dict(source='a.A', target='a.Legacy', dependency_type='METHOD_CALL')],
        cycles=[], issues=[])
    after = dict(algorithm_version='1', configuration={'seed': 42}, summary={'class_count': 2},
        classes=[dict(id='a.A', domain_id='d2'), dict(id='a.NewName', domain_id='d2')],
        edges=[], cycles=[], issues=[])
    first = compare(before, after); second = compare(before, after)
    assert first == second and first['eligibility'] == 'ELIGIBLE'
    assert first['classes']['removed'] == ['a.Legacy'] and first['classes']['added'] == ['a.NewName']
    assert first['classes']['renames'] == [] and first['edges']['removed']
    changed = copy.deepcopy(after); changed['algorithm_version'] = '2'
    assert compare(before, changed)['eligibility'] == 'INCONCLUSIVE'


def test_expected_coupling_improvement_is_measured_and_requires_inventory_preservation():
    before = dict(classes=[dict(id='a.A', domain_id='d1'), dict(id='b.B', domain_id='d2')],
        edges=[dict(source='a.A', target='b.B', dependency_type='METHOD_CALL')], cycles=[], issues=[])
    after = dict(classes=[dict(id='a.A', domain_id='d1'), dict(id='b.B', domain_id='d2')], edges=[], cycles=[], issues=[])
    result = expected_improvement(before, after, 'd1', 'REDUCE_COUPLING_FIRST')
    assert result['state'] == 'PASS' and result['baseline_value'] == 1 and result['candidate_value'] == 0
    missing = dict(after, classes=[dict(id='a.A', domain_id='d1')])
    assert expected_improvement(before, missing, 'd1', 'REDUCE_COUPLING_FIRST')['state'] == 'FAIL'


def test_cycle_improvement_counts_only_target_domain_cycles():
    before = dict(classes=[dict(id='a.A', domain_id='d1'), dict(id='b.B', domain_id='d2')], edges=[],
        cycles=[dict(level='CLASS', members=['a.A','b.B'])], issues=[])
    after = dict(before, cycles=[])
    result = expected_improvement(before, after, 'd1', 'BREAK_CYCLE_FIRST')
    assert result['metric'] == 'CLASS_CYCLE_COUNT' and result['state'] == 'PASS'


def test_capture_never_deletes_an_existing_destination(tmp_path, monkeypatch):
    from app.config import Settings
    target = tmp_path/'existing.jar'
    target.write_bytes(b'keep-existing-data')
    config = Settings(_env_file=None)
    monkeypatch.setattr(sandbox, 'capabilities', lambda *_: {'available': True})
    monkeypatch.setattr(sandbox, 'call', lambda *args, **kwargs: b'not-a-jar')
    monkeypatch.setattr(sandbox, 'reports', lambda *_: dict(tests=1, skipped=0, failures=0, errors=0, cases=[]))
    with pytest.raises(sandbox.SandboxError):
        sandbox.run(config, Row(document={'artifact_path': 'target/app.jar'}), 'test', tmp_path, target)
    assert target.read_bytes() == b'keep-existing-data'


def test_invalid_captured_archive_is_removed(tmp_path, monkeypatch):
    from app.config import Settings
    target = tmp_path/'invalid.jar'
    monkeypatch.setattr(sandbox, 'capabilities', lambda *_: {'available': True})
    monkeypatch.setattr(sandbox, 'call', lambda *args, **kwargs: b'not-a-jar')
    monkeypatch.setattr(sandbox, 'reports', lambda *_: dict(tests=1, skipped=0, failures=0, errors=0, cases=[]))
    with pytest.raises(sandbox.SandboxError):
        sandbox.run(Settings(_env_file=None), Row(document={'artifact_path': 'target/app.jar'}), 'test', tmp_path, target)
    assert not target.exists()


def test_api_comparison_is_revision_bound_idempotent_and_invalidated(prepared, monkeypatch):
    d = prepared; c = d['client']
    assert c.post(base(d)+'/validate', json=revision(d)).status_code == 409
    contract = c.post(base(d)+'/contracts', json=dict(name='Value contract', test_file='src/AppTest.java',
        test_case='AppTest#contract', scenario='Invoke the selected sample method',
        expected_behavior='Return the documented baseline value', critical=True)).json()['contracts'][0]
    assert c.post(base(d)+'/contracts/'+contract['id']+'/review', json=revision(d)).status_code == 200
    result = evidence()[1][0].document['result']; result['artifact_sha256'] = '0'*64
    monkeypatch.setattr(sandbox, 'run', lambda *args: copy.deepcopy(result))
    assert c.post(base(d)+'/builds/BASELINE', json=revision(d)).status_code == 200
    change = proposed(d)
    assert c.post(base(d)+'/changesets/'+change['id']+'/review', json=dict(**revision(d), action='APPROVE_STAGING', fingerprint=change['fingerprint'])).status_code == 200
    assert c.post(base(d)+'/changesets/'+change['id']+'/stage', json=revision(d)).status_code == 200
    assert c.post(base(d)+'/builds/CANDIDATE', json=revision(d)).status_code == 200
    old = revision(d)
    response = c.post(base(d)+'/validate', json=old)
    assert response.status_code == 200, response.text
    validated = response.json()
    assert validated['validation']['freshness'] == 'CURRENT'
    assert statuses(validated['validation'])['REVIEWED_CONTRACT_COMPARISON'] == 'PASS'
    assert c.post(base(d)+'/validate', json=old).status_code == 409
    again = c.post(base(d)+'/validate', json=revision(d)).json()
    assert again['revision'] == validated['revision']
    assert again['validation']['fingerprint'] == validated['validation']['fingerprint']
    result['image_id'] = 'sha256:'+'1'*64
    assert c.post(base(d)+'/builds/CANDIDATE', json=revision(d)).status_code == 200
    assert refresh(d)['validation']['freshness'] == 'STALE'
    blocked = c.post(base(d)+'/validate', json=revision(d)).json()
    assert statuses(blocked['validation'])['BUILD_ENVIRONMENT'] == 'INCONCLUSIVE'
    assert c.post(base(d)+'/actions', json=dict(**revision(d), action='ROLLBACK')).status_code == 200
    assert refresh(d)['validation']['freshness'] == 'STALE'


def test_phase7_publication_impact_review_and_approval_require_completed_evidence(prepared):
    d=prepared;c=d['client'];root=base(d)
    response=c.post(root+'/expected-impact/review',json=dict(**revision(d),
        action='ACCEPT',impact_fingerprint='f'*64))
    assert response.status_code==409
    response=c.post(root+'/candidate-version',json=revision(d))
    assert response.status_code==409
    response=c.post(root+'/final-approval',json=revision(d))
    assert response.status_code==409


def test_candidate_reanalysis_reuses_static_pipeline_and_binds_diff(prepared, monkeypatch):
    d = prepared; c = d['client']
    result = evidence()[1][0].document['result']; result['artifact_sha256'] = '0'*64
    monkeypatch.setattr(sandbox, 'run', lambda *args: copy.deepcopy(result))
    assert c.post(base(d)+'/builds/BASELINE', json=revision(d)).status_code == 200
    change = proposed(d)
    assert c.post(base(d)+'/changesets/'+change['id']+'/review', json=dict(**revision(d), action='APPROVE_STAGING', fingerprint=change['fingerprint'])).status_code == 200
    assert c.post(base(d)+'/changesets/'+change['id']+'/stage', json=revision(d)).status_code == 200
    assert c.post(base(d)+'/builds/CANDIDATE', json=revision(d)).status_code == 200
    with c.app.state.sessions() as db:
        task = db.get(TransformationTask, d['task']['id'])
        build = list(db.query(BuildRun).filter_by(task_id=task.id, kind='CANDIDATE'))[-1]
        target = workspace.root(c.app.state.config, task)/'artifacts'/(build.id+'.jar')
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, 'w') as archive: archive.writestr('sample/App.class', b'\xca\xfe\xba\xbe')
        capture = dict(path=str(target), size=target.stat().st_size, sha256=file_hash(target))
        build.document = dict(build.document, result=dict(build.document['result'], artifact_sha256=capture['sha256'], artifact_capture=capture))
        db.commit()
    submitted = []
    monkeypatch.setattr(c.app.state.worker.scanner, 'available', lambda: True)
    monkeypatch.setattr(c.app.state.worker, 'submit', lambda identity: submitted.append(identity))
    queued = c.post(base(d)+'/reanalyze', json=revision(d)); assert queued.status_code == 200, queued.text
    assert queued.json()['document']['architecture_reanalysis']['state'] == 'QUEUED' and submitted
    with c.app.state.sessions() as db:
        run = db.get(AnalysisRun, submitted[0])
        baseline = db.get(AnalysisRun, d['version']['analysis_id'])
        run.status = 'COMPLETED'; run.result = dict(copy.deepcopy(baseline.result), artifact={'sha256': capture['sha256']}); db.commit()
    complete = c.post(base(d)+'/reanalyze', json=revision(d)); assert complete.status_code == 200, complete.text
    architecture = complete.json()['document']['architecture_reanalysis']
    assert architecture['state'] == 'COMPLETED'
    assert architecture['diff']['eligibility'] == 'ELIGIBLE'
    compared = c.post(base(d)+'/validate', json=revision(d)).json()['validation']
    assert statuses(compared)['ARCHITECTURE_REANALYSIS'] == 'PASS'
    assert compared['approval_eligible'] is False
    from app.transformation import security
    def scanned(*args):
        return dict(state='PASS', artifact_sha256=capture['sha256'], findings=[], dependency_scan={'state':'NOT_RUN'})
    monkeypatch.setattr(security, 'scan', scanned)
    scan=c.post(base(d)+'/security-scan',json=revision(d))
    assert scan.status_code==200, scan.text
    assert scan.json()['document']['security_analysis']['state']=='PASS'
    security_comparison=c.post(base(d)+'/validate',json=revision(d)).json()['validation']
    assert statuses(security_comparison)['JAVA_SECURITY_ANALYSIS']=='PASS'
    assert security_comparison['approval_eligible'] is False
    def failed(*args): raise sandbox.SandboxError('SECURITY_SCANNER_UNAVAILABLE')
    monkeypatch.setattr(security,'scan',failed)
    retry=c.post(base(d)+'/security-scan',json=revision(d))
    assert retry.status_code==200 and retry.json()['document']['security_analysis']['state']=='FAILED'
    blocked=c.post(base(d)+'/validate',json=revision(d)).json()['validation']
    assert statuses(blocked)['JAVA_SECURITY_ANALYSIS']=='FAIL'
    unchanged = revision(d)
    assert c.post(base(d)+'/reanalyze', json=unchanged).json()['revision'] == unchanged['expected_revision']
    target.write_bytes(b'corrupt')
    assert c.post(base(d)+'/security-scan',json=revision(d)).status_code==409
    assert c.post(base(d)+'/reanalyze', json=revision(d)).status_code == 409
