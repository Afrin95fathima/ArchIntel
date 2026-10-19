"""WP8: suggestions for unobserved PetClinic controllers name the right routes and classes."""
from app.insight.test_suggestions import build, form_fields
from insight_fixtures import model, PETCLINIC

OWNER = f'{PETCLINIC}.owner.'


def runtime_with(classes, methods=None):
    nodes = [dict(id=c, static_id=c) for c in classes]
    out = dict(runtime_graph=dict(nodes=nodes, edges=[]))
    if methods is not None:
        out['observed_methods'] = sorted(methods)
    return out


def suggestions(runtime=None):
    return {s['entry_point']['description']: s for s in build(model('petclinic', runtime))['suggestions']}


def test_without_runtime_all_entry_points_are_suggested_with_specific_routes():
    result = build(model('petclinic'))
    assert result['totals'] == dict(entry_points=18, done=0, open=18)      # 17 routes + main() and not result['runtime_included']
    by = suggestions()
    visit = by['POST /owners/{ownerId}/pets/{petId}/visits/new']
    assert visit['entry_point']['handler'] == 'VisitController.processNewVisitForm()'
    assert set(visit['exercises']['classes']) >= {OWNER + 'Owner', OWNER + 'Pet', OWNER + 'Visit', OWNER + 'OwnerRepository', PETCLINIC + '.model.BaseEntity'}
    assert visit['sample_request']['path'] == '/owners/1/pets/1/visits/new'
    fields = {f['name']: f for f in visit['sample_request']['form_fields']}
    assert fields['description']['required'] and 'must not be blank' in fields['description']['constraints']
    assert fields['date']['example'] == '2024-01-15'
    assert 'an Owner with ownerId=1 exists in the database' in visit['preconditions']
    assert any('Submit the form' in step for step in visit['action_steps'])
    assert set(fields) == {'date', 'description'}                          # Visit only; the Owner comes from the path; id is generated
    assert 'Fill in the required fields: description.' in visit['action_steps']
    assert any('hasErrors' in c or 'validation error' in c for c in visit['edge_cases'])


def test_owner_form_constraints_include_inherited_fields_and_patterns():
    fields = {f['name']: f for f in form_fields(model('petclinic').facts, OWNER + 'Owner')}
    assert set(fields) >= {'firstName', 'lastName', 'address', 'city', 'telephone'}
    assert fields['telephone']['example'] == '1111111111' and 'must match \\d{10}' in fields['telephone']['constraints']
    assert fields['firstName']['required']


def test_observed_entry_points_become_done_and_gain_is_counted_after_observed_classes():
    observed = [OWNER + 'OwnerController', OWNER + 'OwnerRepository', OWNER + 'Owner', PETCLINIC + '.model.Person', PETCLINIC + '.model.BaseEntity', OWNER + 'Pet']
    result = build(model('petclinic', runtime_with(observed, {(OWNER + 'OwnerController', 'showOwner')})))
    assert [d['entry_point'] for d in result['done']] == ['GET /owners/{ownerId}']
    assert result['limitation'] == 'Observation is matched per handler method.'
    by = {s['entry_point']['description']: s for s in result['suggestions']}
    assert 'GET /owners/{ownerId}' not in by
    vets = by['GET /vets.html']
    assert set(vets['exercises']['classes']) >= {PETCLINIC + '.vet.VetController', PETCLINIC + '.vet.Vets', PETCLINIC + '.vet.VetRepository'}
    assert vets['expected_gain']['new_classes'] == 3          # Vets, VetRepository, VetController; Vet is only a type argument and OWNER + 'Owner' not in vets['expected_gain']['class_names']
    assert vets['sample_request']['query_parameters'][0] == dict(name='page', type='int', required=True, default='1', example='1', constraints=[])


def test_ranking_is_greedy_by_new_classes():
    result = build(model('petclinic', runtime_with([OWNER + 'OwnerController'], set())))
    gains = [s['expected_gain']['new_classes'] for s in result['suggestions']]
    assert gains == sorted(gains, reverse=True) and gains[0] > gains[-1] >= 0
    assert [s['rank'] for s in result['suggestions']] == list(range(1, len(gains) + 1))


def test_class_level_fallback_is_labelled():
    result = build(model('petclinic', runtime_with([OWNER + 'OwnerController'])))
    assert 'class-level observation' in result['limitation']
    assert not any(s['entry_point']['handler_class'] == OWNER + 'OwnerController' for s in result['suggestions'])


def test_other_entry_kinds_get_specific_steps():
    by = {s['entry_point']['handler']: s for s in build(model('edgecases'))['suggestions']}
    assert by['ReminderJob.sendReminders()']['action_steps'][0].startswith('Wait for the schedule (cron 0 0 * * * *)')
    assert by['OrderEvents.consume()']['action_steps'][0] == 'Publish a message to orders so the listener consume() receives it.'
    assert by['OrderEvents.billing()']['action_steps'][0].endswith('billing.queue so the listener billing() receives it.')
    search = by['ItemController.search()']
    assert search['sample_request']['query_parameters'][0]['constraints'] == ['NotNull', 'Size(max=40, min=2)']
