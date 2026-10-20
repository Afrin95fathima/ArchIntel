import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { ConfidenceBreakdown, ReadinessBreakdown } from './ScoreBreakdown';

afterEach(cleanup);
// Values from backend/tests/test_scoring.py (hand computed): Orders scores 67.2, Billing 100 with three inputs not measured.
const orders = { domain_name: 'Orders', readiness_score: 67.2, formula: 'readiness = sum(component x weight) over the measured inputs.', not_measured: [], component_details: {
  cohesion: { label: 'Cohesion', value: 60, numerator: 3, denominator: 5, weight: .2, text: "3 of 5 dependency edges leaving the domain's classes stay inside it", how_to_raise: ['Pull the 2 outgoing dependencies inside the boundary or remove them, starting with a1 (1), a2 (1).'] },
  database: { label: 'Data independence', value: 50, numerator: 1, denominator: 2, weight: .16, text: '1 of 2 repositories used by the domain are also used by another domain', how_to_raise: ['Give one domain ownership of r1 with Billing.'] },
  cycles: { label: 'Cycle freedom', value: 100, numerator: 0, denominator: 4, weight: .2, text: '0 of 4 classes are in dependency cycles', how_to_raise: [] } } };
const billing = { domain_name: 'Billing', readiness_score: 100, formula: 'x', component_details: { cycles: { ...orders.component_details.cycles, weight: .5 } },
  not_measured: [{ input: 'database', label: 'Data independence', reason: 'no repository class or data-access reference was found; absence does not prove independence' }] };

it('states the question, then each input with its value, weight, counts and the named action to raise it', () => {
  render(<ReadinessBreakdown assessment={orders} />);
  expect(screen.getByText(/how ready is Orders to be modernized or extracted/)).toBeTruthy();
  const row = screen.getByText('Data independence').closest('tr')!;
  expect(within(row).getByText('16%')).toBeTruthy();
  expect(within(row).getByText('1 of 2 repositories used by the domain are also used by another domain')).toBeTruthy();
  expect(within(row).getByText('1 / 2')).toBeTruthy();
  expect(within(row).getByText('Give one domain ownership of r1 with Billing.')).toBeTruthy();
  expect(within(screen.getByText('Cycle freedom').closest('tr')!).getByText('no action needed')).toBeTruthy();
  expect(screen.getByText('Readiness 67.2/100')).toBeTruthy();
});

it('lists an input that was not measured with its reason, and does not show it as a scored row', () => {
  render(<ReadinessBreakdown assessment={billing} />);
  const note = screen.getByRole('note');
  expect(within(note).getByText(/Not measured, excluded from the formula/)).toBeTruthy();
  expect(within(note).getByText(/no repository class or data-access reference was found/)).toBeTruthy();
  expect(within(screen.getByRole('table')).queryByText('Data independence')).toBeNull();
});

it('confidence shows measured evidence inputs and says behavioral validation was not measured instead of scoring it 0', () => {
  render(<ConfidenceBreakdown assessment={{ domain_name: 'Orders', confidence_score: 70,
    confidence_inputs: { review_status: { label: 'Domain review recorded', value: 0, numerator: null, denominator: null, weight: .25, text: 'no domain review is recorded for this version', how_to_raise: ['Review the membership of Orders in Evidence & digital twin and save the review.'] } },
    confidence_not_measured: [{ input: 'behavioral_validation', label: 'Behavioral validation', reason: 'no behavioral contract tests are recorded for this version', how_to_measure: 'Add reviewed behavioral contracts to a source task for this domain (Source tasks > Contracts).' }] }} />);
  expect(screen.getByText(/how much evidence supports the readiness number for Orders/)).toBeTruthy();
  expect(screen.getByText('Review the membership of Orders in Evidence & digital twin and save the review.')).toBeTruthy();
  expect(screen.getByText(/Behavioral validation/, { selector: 'strong' })).toBeTruthy();
  expect(screen.getByText(/no behavioral contract tests are recorded for this version/)).toBeTruthy();
});

it('tells the user when an older assessment has no input details instead of inventing them', () => {
  render(<ReadinessBreakdown assessment={{ domain_name: 'Old', readiness_score: 50, formula: 'f' }} />);
  expect(screen.getByText(/created before input details were recorded/)).toBeTruthy();
});
