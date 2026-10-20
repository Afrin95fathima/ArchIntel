import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { ItemDescription } from './ItemDescription';

afterEach(cleanup);
// Text produced by backend/tests/test_modernization_description.py on the Spring PetClinic fixture.
const owner = { title: 'Type Owner: 3 classes, 1 package', target: { domain: 'Type Owner', class_count: 3, packages: ['org.springframework.samples.petclinic.owner'], key_classes: ['org.springframework.samples.petclinic.owner.PetType', 'org.springframework.samples.petclinic.owner.NamedEntity'] },
  current_state: ['Type Owner has 3 classes in 1 package: org.springframework.samples.petclinic.owner.', 'Runtime: 2 of 3 classes observed (66.67%).'],
  selected_because: ['Decision COLLECT_MORE_EVIDENCE was chosen because: Selected sessions observed 2 of 3 classes of Type Owner (66.67%, minimum 80%).'],
  blockers: [{ code: 'RUNTIME_OBSERVATION_GAP', meaning: 'The selected runtime sessions do not cover enough of the domain.', resolve: 'Exercise the unobserved entry points and capture a new architecture version.', subjects: ['Type Owner'], detail: 'Selected sessions observed 2 of 3 classes of Type Owner (66.67%, minimum 80%).' }],
  order: ['Wave 4 of 5.', 'Depends on Vet (2 dependency edges, wave 2).'],
  formulas: [{ name: 'Heuristic cost index (orders the waves)', value: 11, formula: 'classes 3 / 20 + 1.5 x 1 crossing pairs + 8 x 1 shared repositories' }] };

it('shows target, state, reason, named blockers, order and formulas with the analysis values', () => {
  render(<ItemDescription item={owner} />);
  expect(screen.getByText('Type Owner: 3 classes, 1 package. Packages: org.springframework.samples.petclinic.owner. Key classes: PetType, NamedEntity.')).toBeTruthy();
  expect(screen.getByText('Runtime: 2 of 3 classes observed (66.67%).')).toBeTruthy();
  expect(screen.getByText(/Decision COLLECT_MORE_EVIDENCE was chosen because/)).toBeTruthy();
  const blocker = screen.getByText('RUNTIME_OBSERVATION_GAP').closest('li')!;
  expect(within(blocker).getByText(/Named: Type Owner\./)).toBeTruthy();
  expect(within(blocker).getByText(/Resolve: Exercise the unobserved entry points/)).toBeTruthy();
  expect(screen.getByText('Depends on Vet (2 dependency edges, wave 2).')).toBeTruthy();
  expect(screen.getByText(/classes 3 \/ 20 \+ 1\.5 x 1 crossing pairs/)).toBeTruthy();
});
