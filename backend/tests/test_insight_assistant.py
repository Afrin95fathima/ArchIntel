"""WP7: tools, evidence verification and the evaluation harness (pass rate + hallucination check)."""
from pathlib import Path
from app.insight.assistant.evaluate import run_file
from app.insight.assistant.evidence import Index, check_answer
from app.insight.assistant.tools import Tools, CATALOG
from insight_fixtures import model, PETCLINIC

QUESTIONS = Path(__file__).parent / 'evaluation' / 'petclinic_questions.json'


def test_evaluation_harness_reports_pass_rate_and_no_hallucinated_classes():
    report = run_file(model('petclinic'), QUESTIONS)
    failed = [r for r in report['results'] if not r['passed']]
    print(f"\nASSISTANT EVALUATION: {report['passed']}/{report['total']} passed ({report['pass_rate']:.0%}); hallucinated answers: {report['hallucinated_answers']}")
    for r in failed:
        print('  FAIL', r['q'], r['failures'])
    assert report['total'] >= 30
    assert report['hallucinated_answers'] == 0
    assert report['pass_rate'] >= 0.95, failed


def test_every_tool_is_registered_read_only_and_scoped():
    assert set(CATALOG) == {'get_package', 'get_class', 'get_dependencies', 'get_dependents', 'get_cycles', 'get_debt_findings', 'get_runtime_coverage',
        'get_entry_points', 'get_aging_findings', 'get_class_source', 'search_classes', 'get_metrics', 'get_responsibilities'}
    tools = Tools(model('petclinic'), None, 'a1')
    assert tools.call('delete_everything', {})['error'] == 'UNKNOWN_TOOL'
    assert tools.call('get_class', {'name': 'Owner', 'evil': 1})['error'] == 'UNKNOWN_ARGUMENTS'
    assert tools.call('get_class', {'name': 'NoSuchClass'})['error'] == 'NOT_FOUND'


def test_tool_results_cite_existing_evidence_and_ambiguity_is_reported():
    tools = Tools(model('edgecases'), None, 'a1')
    index = Index(model('edgecases'))
    for tool, args in [('get_class', {'name': 'ItemService'}), ('get_debt_findings', {}), ('get_cycles', {}), ('get_aging_findings', {}), ('get_entry_points', {}),
                       ('search_classes', {'query': 'Order'}), ('get_metrics', {'top': 'class.fan_out'}), ('get_dependents', {'name': 'Order'}), ('get_package', {'name': 'com.fixture.edge.legacy'})]:
        result = tools.call(tool, args)
        assert result['ok'], (tool, result)
        assert all(index.exists(e) for e in result['evidence']), (tool, [e for e in result['evidence'] if not index.exists(e)])
    assert tools.call('get_class', {'name': 'Order'})['ok'] is True           # unique simple name
    assert tools.call('get_class', {'name': 'cycle'})['error'] == 'NOT_FOUND'


def test_verifier_removes_missing_citations_and_invented_classes():
    index = Index(model('petclinic'))
    kept, removed = check_answer(index, [
        dict(text='OwnerController uses OwnerRepository.', cites=[f'class:{PETCLINIC}.owner.OwnerController']),
        dict(text='PaymentGateway is called by OwnerController.', cites=[f'class:{PETCLINIC}.owner.OwnerController']),
        dict(text='Cites something that is not there.', cites=['class:com.nope.Ghost']),
        dict(text='No citation at all.', cites=[]),
        dict(text='Edge that does not exist.', cites=[f'edge:{PETCLINIC}.owner.Owner->{PETCLINIC}.vet.Vet'])])
    assert [k['text'] for k in kept] == ['OwnerController uses OwnerRepository.']
    assert sorted(r['reason'] for r in removed) == ['CITATION_NOT_FOUND', 'CITATION_NOT_FOUND', 'NO_CITATION', 'UNKNOWN_IDENTIFIER']


def test_source_tool_is_bounded_and_labelled(tmp_path):
    from app.config import Settings
    tools = Tools(model('petclinic'), Settings(_env_file=None, data_dir=tmp_path), 'a1')
    result = tools.call('get_class_source', {'name': 'Visit'})
    assert result['data']['kind'] == 'BYTECODE_OUTLINE' and len(result['data']['text']) <= 6000 and 'not original source' in result['data']['text']
    denied = Tools(model('petclinic'), Settings(_env_file=None, data_dir=tmp_path, source_store_mode='DENY'), 'a1').call('get_class_source', {'name': 'Visit'})
    assert denied['data']['available'] is False and 'source_store_mode=DENY' in denied['data']['reason']


def test_heldout_paraphrases_are_reported_separately():
    report = run_file(model('petclinic'), Path(__file__).parent / 'evaluation' / 'petclinic_heldout.json')
    print(f"\nHELD-OUT PARAPHRASES: {report['passed']}/{report['total']} passed ({report['pass_rate']:.0%}); hallucinated answers: {report['hallucinated_answers']}")
    for r in report['results']:
        if not r['passed']:
            print('  FAIL', r['q'], r['failures'])
    assert report['hallucinated_answers'] == 0          # the honest bar: never invent, even when the question is not understood
    assert report['pass_rate'] >= 0.6


def test_responsibility_tool_cites_real_evidence_and_narrow_words_narrow_the_rules():
    tools, index = Tools(model('petclinic'), None, 'a1'), Index(model('petclinic'))
    caching = tools.call('get_responsibilities', {'concern': 'caching'})
    assert caching['ok'] and {i['id'].rsplit('.', 1)[-1] for i in caching['data']['items']} == {'CacheConfiguration', 'VetRepository'}
    assert all(index.exists(e) for e in caching['evidence']) and any(e.startswith('resp:') for e in caching['evidence'])
    performance = tools.call('get_responsibilities', {'concern': 'PERFORMANCE'})['data']
    assert performance['total'] > caching['data']['total']                      # the category is wider than the word "caching"
    scoped = tools.call('get_responsibilities', {'name': 'OwnerController'})
    assert scoped['data']['items'][0]['primary'] == 'MIXED' and all(index.exists(e) for e in scoped['evidence'])
    assert tools.call('get_responsibilities', {'concern': 'astrology'})['error'] == 'UNKNOWN_CONCERN'
    assert tools.call('get_responsibilities', {'name': 'NoSuchClass'})['error'] == 'NOT_FOUND'
    assert tools.call('get_responsibilities', {'evil': 1})['error'] == 'UNKNOWN_ARGUMENTS'


def test_the_verifier_accepts_real_responsibility_ids_and_rejects_invented_ones():
    index, m = Index(model('petclinic')), model('petclinic')
    real = next(iter(m.responsibility['evidence']))
    risk = m.responsibility['risks'][0]['id']
    assert index.exists('resp:' + real) and index.exists('risk:' + risk)
    assert not index.exists('resp:resp-evidence-doesnotexist') and not index.exists('risk:resp-risk-doesnotexist')
    kept, removed = check_answer(index, [dict(text='A claim.', cites=['resp:' + real]), dict(text='An invented claim.', cites=['resp:resp-evidence-doesnotexist'])])
    assert [s['text'] for s in kept] == ['A claim.'] and removed[0]['reason'] == 'CITATION_NOT_FOUND'


def test_routes_that_change_data_are_answered_from_the_http_method_and_never_by_guessing():
    report = run_file(model('petclinic'), QUESTIONS)
    results = {r['q']: r for r in report['results']}
    for question in ('Which HTTP routes change data?', 'Which routes in OwnerController modify state?'):
        assert results[question]['passed'], results[question]['failures']
