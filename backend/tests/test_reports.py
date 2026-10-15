from types import SimpleNamespace
import re
import zlib

from app.reports.modernization_pdf import render_modernization_report


def fixture(runtime=True):
    app = SimpleNamespace(name='Concord')
    run = SimpleNamespace(id='analysis-id', result={
        'summary': {'class_count': 25, 'package_count': 4, 'dependency_count': 31, 'domain_count': 2,
                    'artifact': {'filename': 'concord.jar', 'sha256': 'a' * 64}, 'issue_counts': {'HIGH': 1}},
        'domains': [{'id': 'd1', 'name': 'Console', 'class_count': 15}],
        'issues': [{'severity': 'HIGH', 'title': 'Cross-domain cycle', 'description': 'Review before extraction.'}],
    })
    coverage = {key: {'observed': 3, 'total': 10, 'percentage': 30.0} for key in ('classes', 'entry_points', 'methods', 'dependencies', 'domains')}
    version = SimpleNamespace(name='Concord runtime capture', id='version-id', fingerprint='b' * 64,
        manifest={'runtime_session_ids': ['session-id'] if runtime else [], 'artifact_sha256': 'a' * 64},
        document={'coverage': coverage, 'quality': {'dropped_spans': 0}, 'graph': {'nodes': [{}] * 4, 'edges': [{}] * 3},
                  'evidence_count': 5, 'facts_count': 2, 'unknowns': ['Data ownership is unconfirmed.']})
    assessment = SimpleNamespace(id='proposal-id', document={
        'decision_brief': {'summary': 'A reviewable plan.', 'selected_strategy': 'MICROSERVICES', 'objective': 'Modernize safely.',
                           'strategy_comparison': [], 'unresolved_questions': ['Who owns the database?'], 'next_step': 'Review boundaries.'},
        'validation': {'status': 'VALIDATED'}, 'assessments': [{'domain_id': 'd1', 'domain_name': 'Console', 'structural_score': 70,
            'runtime_score': 60, 'combined_score': 66, 'confidence_score': 40, 'confidence_label': 'LIMITED', 'blockers': ['DOMAIN_REVIEW_REQUIRED']}],
        'decisions': [{'domain_id': 'd1', 'action': 'Collect more evidence.', 'blockers': ['DOMAIN_REVIEW_REQUIRED']}],
        'waves': [{'number': 1, 'domains': ['d1'], 'reason': 'Review dependencies.', 'blockers': []}],
        'limitations': ['Scores are heuristic.'], 'rule_version': 'rules-v1', 'calibration_version': 'cal-v1',
        'target': {'strategy': 'MICROSERVICES', 'objective': 'Modernize safely.'},
    })
    sessions = [SimpleNamespace(name='Demo session', environment='LOCAL', status='COMPLETED', trace_count=2, span_count=3, id='session-id')] if runtime else []
    return app, run, version, assessment, sessions


def pdf_text(pdf):
    streams = re.findall(rb'/Length (\d+) /Filter /FlateDecode >>\nstream\n', pdf)
    content = []
    position = 0
    for match in re.finditer(rb'/Length (\d+) /Filter /FlateDecode >>\nstream\n', pdf):
        size = int(match.group(1))
        start = match.end()
        content.append(zlib.decompress(pdf[start:start + size]))
        position = start + size
    assert streams
    return b'\n'.join(content)


def assert_pdf_pages_resolve(pdf):
    objects = {int(match.group(1)): match.group(2) for match in re.finditer(rb'(\d+) 0 obj\n(.*?)\nendobj', pdf, re.S)}
    catalog_id = int(re.search(rb'/Root (\d+) 0 R', pdf).group(1))
    pages_id = int(re.search(rb'/Pages (\d+) 0 R', objects[catalog_id]).group(1))
    page_ids = [int(value) for value in re.findall(rb'(\d+) 0 R', re.search(rb'/Kids \[(.*?)\]', objects[pages_id]).group(1))]
    assert page_ids and len(page_ids) == int(re.search(rb'/Count (\d+)', objects[pages_id]).group(1))
    for page_id in page_ids:
        page = objects[page_id]
        assert b'/Type /Page' in page
        content_id = int(re.search(rb'/Contents (\d+) 0 R', page).group(1))
        assert b'/Filter /FlateDecode' in objects[content_id]
    xref_offset = int(re.search(rb'startxref\n(\d+)', pdf).group(1))
    assert pdf[xref_offset:].startswith(b'xref\n')


def pdf_page_count(pdf):
    pages = re.search(rb'/Type /Pages /Kids \[(.*?)\] /Count (\d+)', pdf, re.S)
    assert pages
    return int(pages.group(2))


def test_consolidated_pdf_includes_all_four_evidence_layers_and_plan_caveats():
    values = fixture()
    pdf = render_modernization_report(*values[:4], values[4], {'state': 'PENDING'})
    assert pdf.startswith(b'%PDF-1.4') and pdf.endswith(b'%%EOF\n')
    assert_pdf_pages_resolve(pdf)
    assert 8 <= pdf_page_count(pdf) <= 14
    text = pdf_text(pdf)
    for expected in (b'Static analysis', b'Dynamic analysis', b'Digital twin', b'Modernization proposal',
                     b'Cross-domain cycle', b'Demo session', b'MICROSERVICES', b'heuristic', b'ownership'):
        assert expected.lower() in text.lower()
    for expected in (b'Architecture scale', b'Findings by severity', b'Candidate domain size',
                     b'Observed runtime coverage', b'Digital twin evidence',
                         b'Readiness and confidence by domain',
                     b'Proposed modernization waves'):
        assert expected.lower() in text.lower()
    assert b'proposal schema check' in text.lower() and b'passed' in text.lower()


def test_report_marks_dynamic_layer_unavailable_when_snapshot_is_static_only():
    app, run, version, assessment, sessions = fixture(runtime=False)
    pdf = render_modernization_report(app, run, version, assessment, sessions, {'state': 'UNAVAILABLE'})
    assert b'runtime coverage is not' in pdf_text(pdf).lower()

