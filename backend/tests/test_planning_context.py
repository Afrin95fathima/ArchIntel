"""Item 5: the planning context states exact, current facts, and 'not measured' with a reason where a fact is absent."""
import pytest
from app.models import AnalysisRun, Artifact
from app.services.engine import analyze
from app.config import Settings
from helpers import cls, edge
from insight_fixtures import snapshot
from test_runtime import live, span
from test_evidence import make, capture


def context(live, version):
    response = live.get(f"/api/v1/architecture-versions/{version['id']}/modernization/context")
    assert response.status_code == 200, response.text
    return response.json()


def test_static_only_version_reports_counts_and_marks_everything_else_not_measured(live):
    version = make(live)
    c = context(live, version)
    assert (c['counts']['classes']['value'], c['counts']['packages']['value'], c['counts']['domains']['value'], c['counts']['class_cycle_groups']['value']) == (4, 4, 1, 0)
    assert c['version']['fingerprint']['value'] == version['fingerprint'] and c['artifact']['name']['value'] == 'test.jar' and c['artifact']['sha256']['value'] == '0' * 64
    assert c['scan']['analysis_id']['value'] == live.run_id and c['scan']['scan_date']['value']
    assert c['runtime']['session_count'] == 0 and c['runtime']['sessions'] == []
    for key in ('traces', 'class_coverage', 'entry_point_coverage', 'method_coverage'):
        assert c['runtime'][key] == {'value': None, 'not_measured': 'no runtime session is attached to this version'}
    assert c['counts']['aging_technology_findings']['not_measured'] == 'this analysis has no bytecode facts; run a new analysis'
    assert c['counts']['entry_points']['not_measured'] == 'no entry point was detected'
    assert c['review']['domain_review'] == {'value': None, 'not_measured': 'no domain review is recorded for this version'}
    assert c['changes']['state'] == 'NO_EARLIER_VERSION'
    assert 'Runtime coverage is not measured because no runtime session is attached' in ' '.join(c['takes_into_account'])
    assert 'Domain review: not recorded; the review-status input of confidence is 0.' in c['takes_into_account']


def test_runtime_session_adds_ids_windows_traces_and_coverage_with_numerator_and_denominator(live):
    sid = capture(live, span(1, 'app.a.A'), span(2, 'app.b.B', 1), span(3, 'app.d.D', 2), span(4, 'app.x.X'), span(5, 'app.b.B', 4))
    c = context(live, make(live, [sid]))
    [session] = c['runtime']['sessions']
    assert session['id'] == sid and session['status'] == 'COMPLETED' and session['spans'] == 5 and session['started_at'] and session['ended_at']
    assert c['runtime']['traces']['value'] == 1 and c['runtime']['traces']['unit'] == 'traces (one per request or job)'
    coverage = c['runtime']['class_coverage']
    assert (coverage['value'], coverage['observed'], coverage['total'], coverage['text']) == (75.0, 3, 4, '75.0% (3 of 4)')
    assert c['runtime']['entry_point_coverage']['not_measured']       # no method/entry-point evidence in this capture
    assert 'Runtime coverage: 75.0% of classes (3 of 4)' in ' '.join(c['takes_into_account'])
    assert '1 unobserved classes lower the runtime coverage input of confidence; unobserved never counts as unused.' in ' '.join(c['takes_into_account'])


def test_review_is_reported_when_recorded(live):
    with live.app.state.sessions() as db:
        static = db.get(AnalysisRun, live.run_id).result
    edits = [dict(id=d['id'], name=d['name'], classes=d['classes']) for d in static['domains']]
    version = make(live, domain_edits=edits, review_reason='Architect review')
    review = context(live, version)['review']['domain_review']
    assert review['value'] is True and review['reason'] == 'Architect review' and review['actor']


def test_changes_since_the_previous_version_count_added_classes_and_dependencies(live):
    first = make(live)
    nodes = [cls('app.a.A'), cls('app.b.B'), cls('app.c.C'), cls('app.d.D'), cls('app.e.E')]
    edges = [edge('app.a.A', 'app.b.B'), edge('app.a.A', 'app.c.C'), edge('app.b.B', 'app.d.D'), edge('app.e.E', 'app.a.A')]
    with live.app.state.sessions() as db:
        original = db.get(AnalysisRun, live.run_id)
        run = AnalysisRun(application_id=original.application_id, artifact_id=original.artifact_id, status='COMPLETED', result=analyze(nodes, edges, Settings(_env_file=None)))
        db.add(run); db.commit(); newer = run.id
    response = live.post(f'/api/v1/applications/{live.app_id}/architecture-versions', json=dict(analysis_id=newer, name='Second', runtime_session_ids=[]))
    assert response.status_code == 201, response.text
    changes = context(live, response.json())['changes']
    assert changes['previous_version'] == first['id'] and changes['previous_name'] == 'Evidence version'
    assert (changes['classes_added'], changes['classes_removed'], changes['added_examples']) == (1, 0, ['app.e.E'])
    assert (changes['dependency_pairs_added'], changes['dependency_pairs_removed']) == (1, 0)
    assert changes['text'] == ('Compared with Evidence version: 1 class(es) added, 0 removed; 1 dependency pair(s) added, 0 removed; domains 1 -> 1; cycles 0 -> 0; '
                               'class coverage was not measured in both versions.')


def test_petclinic_version_counts_entry_points_aging_technology_and_cycles(live):
    with live.app.state.sessions() as db:
        original = db.get(AnalysisRun, live.run_id)
        run = AnalysisRun(application_id=original.application_id, artifact_id=original.artifact_id, status='COMPLETED', result=snapshot('petclinic'))
        db.add(run); db.commit(); pc = run.id
    response = live.post(f'/api/v1/applications/{live.app_id}/architecture-versions', json=dict(analysis_id=pc, name='PetClinic', runtime_session_ids=[]))
    assert response.status_code == 201, response.text
    c = context(live, response.json())
    # 24 classes, 5 packages, 5 domains, no class cycle; 12 GET + 5 POST controller mappings + 1 main method; Java target and Spring Boot are aging
    assert [c['counts'][k]['value'] for k in ('classes', 'packages', 'domains', 'class_cycle_groups', 'entry_points', 'aging_technology_findings')] == [24, 5, 5, 0, 18, 2]
    assert 'Aging technology: 2 finding(s) from the lifecycle rules (Java bytecode target level aging, Spring Boot aging).' in c['takes_into_account']


def test_context_endpoint_is_scoped_to_the_callers_version(live):
    assert live.get('/api/v1/architecture-versions/not-a-version/modernization/context').status_code == 404


def test_version_signatures_become_method_names_for_the_insight_model():
    from app.modernization.engine import method_name_pairs
    pairs = [('app.A', 'java.lang.String findOwner(int)'), ('app.A', 'void <init>()'), ('app.B', 'app.X save(java.lang.Integer, app.Y)')]
    assert method_name_pairs(pairs) == [('app.A', '<init>'), ('app.A', 'findOwner'), ('app.B', 'save')]


def test_observed_entry_point_in_a_version_is_not_reported_as_never_observed():
    from types import SimpleNamespace
    from app.modernization.engine import analysis_context
    static = snapshot('petclinic')
    entry = next(e for e in static['entry_points']['items'] if e.get('handler_signature'))
    classes = [c['id'] for c in static['classes']]
    observed = [[entry['handler_class'], entry['handler_signature']]]
    version = SimpleNamespace(document=dict(observed_methods=observed, coverage=dict(domain_observations=[dict(id='d', unobserved_classes=[c for c in classes if c != entry['handler_class']])])),
                              manifest=dict(method_observations_available=True))
    model = analysis_context(version, static, [dict(id='d', classes=classes)], True)['model']
    handler = next(e for e in model.entry_points['items'] if e['handler_class'] == entry['handler_class'] and e.get('handler_signature') == entry['handler_signature'])
    assert (handler['handler_class'], handler['handler_method']) in model.observed_methods
