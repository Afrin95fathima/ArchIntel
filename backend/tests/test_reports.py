"""Item 6: the report is one model rendered to HTML and PDF; its figures equal the application's own API data."""
import re
import zlib

import pytest

from app.models import AnalysisRun
from insight_fixtures import snapshot
from test_runtime import live, span
from test_evidence import make, capture

SECTION_IDS = ['summary', 'profile', 'architecture', 'problems', 'aging', 'cycles', 'runtime', 'plan', 'risks', 'appendix']


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




def sentences(text):
    return [s for s in re.split(r'(?<=[.!?])\s+(?=[A-Z0-9(])', text.strip()) if s]


def petclinic_report(live, with_runtime=False):
    with live.app.state.sessions() as db:
        original = db.get(AnalysisRun, live.run_id)
        result = dict(snapshot('petclinic'), artifact=dict(filename='petclinic.jar', sha256='f' * 64, size=1), scanner=dict(name='fixture', version='1'), limitations=[])
        run = AnalysisRun(application_id=original.application_id, artifact_id=original.artifact_id, status='COMPLETED', result=result)
        db.add(run); db.commit(); analysis = run.id
    response = live.post(f'/api/v1/applications/{live.app_id}/architecture-versions', json=dict(analysis_id=analysis, name='PetClinic', runtime_session_ids=[]))
    assert response.status_code == 201, response.text
    version = response.json()
    base = f"/api/v1/architecture-versions/{version['id']}/modernization"
    created = live.post(base, json=dict(strategy='MODULAR_MONOLITH', objective='Produce the report'))
    assert created.status_code == 201, created.text
    return base, created.json()['id'], analysis, version


def test_report_has_ten_sections_each_with_plain_terms_and_technical_detail(live):
    base, aid, *_ = petclinic_report(live)
    report = live.get(f'{base}/{aid}/report.json').json()
    assert [s['id'] for s in report['sections']] == SECTION_IDS and [s['number'] for s in report['sections']] == list(range(1, 11))
    for section in report['sections']:
        count = sum(len(sentences(p)) for p in section['plain'])
        assert 2 <= count <= 4, (section['id'], count, section['plain'])
        assert section['technical'], section['id']
    assert report['numbers_check']['unregistered'] == []


def test_the_plain_text_names_the_applications_own_classes_domains_and_numbers(live):
    base, aid, *_ = petclinic_report(live)
    text = {s['id']: ' '.join(s['plain']) for s in live.get(f'{base}/{aid}/report.json').json()['sections']}
    assert '24 classes in 5 packages, grouped into 5 candidate domains' in text['summary'] and 'Type Owner' in text['summary'] and 'Vet' in text['summary']
    assert 'controller dependencies on entities (8 of 15 dependency edges, 53.3%)' in text['summary']
    assert 'Java 17' in text['summary'] or 'compiled for Java 17' in text['summary']
    assert '18 entry points were detected (17 HTTP endpoints, 1 main method)' in text['profile']
    assert 'Database tables seen at runtime are not measured: no runtime session is attached.' in text['profile']
    assert 'The code falls into 5 layers: Presentation 6, Services and application logic 2, Data access 3, Domain model 10, Configuration and bootstrap 3 classes.' in text['architecture'] and '15 dependency edges run across 3 domain pairs' in text['architecture']
    assert '2 technologies need replacing: Java bytecode target level, Spring Boot' in text['aging'] and 'Class files target Java 17' in text['aging'] and 'no language change' in text['aging'].lower()
    assert 'No runtime session is attached, so nothing was observed' in text['runtime']


def test_report_figures_equal_the_application_api_data(live):
    base, aid, analysis, version = petclinic_report(live)
    report = live.get(f'{base}/{aid}/report.json').json()
    facts = {f['id']: f for f in report['facts']}
    summary = live.get(f'/api/v1/analyses/{analysis}/summary').json()
    debt = live.get(f'/api/v1/analyses/{analysis}/insight/debt').json()
    cycles = live.get(f'/api/v1/analyses/{analysis}/insight/cycles').json()
    context = live.get(f"/api/v1/architecture-versions/{version['id']}/modernization/context").json()
    plan = live.get(f'{base}/{aid}').json()['document']
    assert facts['classes']['value'] == summary['class_count'] == context['counts']['classes']['value']
    assert facts['packages']['value'] == summary['package_count'] and facts['domains']['value'] == summary['domain_count']
    assert facts['entry_points']['value'] == context['counts']['entry_points']['value']
    rates = {r['id']: r for r in debt['rates']['rates']}
    cited = [rid for rid in rates if f'rate_{rid}_n' in facts]
    assert cited
    for rid in cited:
        assert (facts[f'rate_{rid}_n']['value'], facts[f'rate_{rid}_d']['value'], facts[f'rate_{rid}_pct']['value']) == (rates[rid]['numerator'], rates[rid]['denominator'], rates[rid]['percentage'])
    assert facts['aging_items']['value'] == len(plan['technology_plan']['items']) == 2
    assert facts['waves']['value'] == len(plan['waves']) and facts['cross_edges']['value'] == sum(r['edge_count'] for r in plan['domain_dependency_matrix']['rows'])
    problems = next(t for t in next(s for s in report['sections'] if s['id'] == 'summary')['technical'] if t.get('caption') == 'Top five technical problems')
    for row in problems['rows']:
        rate = next(r for r in debt['rates']['rates'] if r['label'] == row[0])
        assert row[1:4] == [str(rate['numerator']), f"{rate['denominator']} {rate['unit']}", f"{rate['percentage']}%"]
    assert len([c for c in cycles['groups'] if c['level'] == 'CLASS']) == 0 and 'No class-level dependency cycle was found.' in ' '.join(next(s for s in report['sections'] if s['id'] == 'cycles')['plain'])


def test_html_report_is_self_contained_with_both_diagrams_and_every_plain_sentence(live):
    base, aid, *_ = petclinic_report(live)
    report = live.get(f'{base}/{aid}/report.json').json()
    response = live.get(f'{base}/{aid}/report.html')
    assert response.status_code == 200 and response.headers['content-type'].startswith('text/html')
    html = response.text
    assert '<script' not in html and html.count('In plain terms') == 10 and html.count('Technical detail') == 10
    ids = re.findall(r' id="([^"]+)"', html)
    assert len(ids) == len(set(ids)), 'duplicate element ids in the report'
    assert html.count('<svg') == 2 and 'aria-labelledby="hld-title hld-desc"' in html and 'aria-labelledby="map-title map-desc"' in html
    assert [m for m in re.findall(r'<h2 id="h-(\w+)"', html)] == SECTION_IDS
    from html import escape
    for section in report['sections']:
        for paragraph in section['plain']:
            assert escape(paragraph, quote=True) in html
    assert 'Owner Visit' in html and 'Type Owner' in html and '>24<' in html
    assert live.get(f'{base}/{aid}/report.html?download=true').headers['content-disposition'].startswith('attachment; filename="archintel-Test-')


def test_pdf_report_is_valid_and_carries_the_same_text(live):
    base, aid, *_ = petclinic_report(live)
    report = live.get(f'{base}/{aid}/report.json').json()
    response = live.get(f'{base}/{aid}/report.pdf')
    assert response.status_code == 200 and response.headers['content-type'].startswith('application/pdf')
    assert 'attachment; filename="archintel-Test-' in response.headers['content-disposition']
    pdf = response.content
    assert pdf.startswith(b'%PDF-1.4') and pdf.endswith(b'%%EOF\n')
    assert_pdf_pages_resolve(pdf)
    assert pdf_page_count(pdf) >= 12
    text = pdf_text(pdf).lower()
    for section in report['sections']:
        assert f"{section['number']}. {section['title']}".lower().encode('ascii') in text
    assert text.count(b'in plain terms') == 10 and b'technical detail' in text
    assert b'type owner' in text and b'high-level architecture' in text and b'domain dependency matrix' in text and b'fact table' in text


def test_runtime_sections_report_the_session_numbers_when_a_session_is_attached(live):
    sid = capture(live, span(1, 'app.a.A'), span(2, 'app.b.B', 1), span(3, 'app.d.D', 2), span(4, 'app.x.X'), span(5, 'app.b.B', 4))
    version = make(live, [sid])
    created = live.post(f"/api/v1/architecture-versions/{version['id']}/modernization", json=dict(strategy='MODULAR_MONOLITH', objective='Runtime report'))
    assert created.status_code == 201, created.text
    report = live.get(f"/api/v1/architecture-versions/{version['id']}/modernization/{created.json()['id']}/report.json").json()
    text = {s['id']: ' '.join(s['plain']) for s in report['sections']}
    assert '1 runtime session observed 3 of 4 classes (75.0%)' in text['runtime']
    sessions = next(t for t in next(s for s in report['sections'] if s['id'] == 'runtime')['technical'] if t.get('caption') == 'Sessions')
    assert sessions['rows'][0][0] == 'Test' and sessions['rows'][0][3:5] == ['1', '5'] and sessions['rows'][0][5] == sid
    assert report['numbers_check']['unregistered'] == []


def test_report_carries_the_non_functional_constraints_in_plain_terms_and_in_tables(live):
    base, aid, *_ = petclinic_report(live)
    report = live.get(f'{base}/{aid}/report.json').json()
    sections = {s['id']: s for s in report['sections']}
    assert any('non-functional risk indicator' in sentence for sentence in sections['plan']['plain'])
    technical = {t.get('caption') or t.get('title'): t for t in sections['risks']['technical']}
    risks = technical['Non-functional risk indicators']
    assert risks['columns'][:4] == ['Rule', 'Severity', 'Category', 'Detection'] and len(risks['rows']) >= 3
    assert {row[3] for row in risks['rows']} <= {'DETECTED', 'INFERRED'} and 'none is a measurement' in risks['note']
    assert {'Business capabilities and technical domains', 'Components shared across domains', 'Not examined for non-functional concerns'} <= set(technical)
    assert any('SECURITY' == row[2] for row in risks['rows']) and any(row[0] == 'RISK-DATA-SHARED-MODEL' for row in risks['rows'])
    html = live.get(f'{base}/{aid}/report.html').text
    assert 'Non-functional risk indicators' in html and 'Components shared across domains' in html
    pdf = pdf_text(live.get(f'{base}/{aid}/report.pdf').content).lower()
    assert b'non-functional risk indicators' in pdf and b'components shared across domains' in pdf and b'not examined for non-functional concerns' in pdf and b'risk-data-shared-model' in pdf
