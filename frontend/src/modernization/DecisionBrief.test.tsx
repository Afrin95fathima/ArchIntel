import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { DecisionBrief, type DecisionBriefData } from './DecisionBrief';
import fixture from './fixtures/petclinic.brief.json';

afterEach(cleanup);
const brief = fixture.decision_brief as unknown as DecisionBriefData;
const numbers = (text: string) => text.match(/(?<![\w.])\d+(?:\.\d+)?(?![\w])/g) || [];

it('puts the fact table first and shows each section of the PetClinic brief', () => {
  render(<DecisionBrief brief={brief} />);
  const root = screen.getByRole('region', { name: 'Decision brief' });
  expect(root.firstElementChild!.tagName).toBe('DETAILS');
  const facts = within(root).getByText(/Fact table: \d+ numbers used in this brief/);
  expect(facts.textContent).toBe(`Fact table: ${brief.facts!.length} numbers used in this brief`);
  expect(within(root).getByText('Cross-domain dependency edges').closest('tr')!.textContent).toContain('15');
  for (const title of ['The decision', 'Recommended option and why', 'Options considered', 'Scope', 'Blockers and prerequisites', 'Risks', 'Confidence and what was not observed', 'What is not known']) {
    expect(within(root).getByRole('heading', { name: title })).toBeTruthy();
  }
  expect(within(root).getByText(/Controller dependencies on entities: 8 of 15 dependency edges \(53\.3%\)\./)).toBeTruthy();
});

it('every number in the rendered section text is in the fact table shown above it', () => {
  render(<DecisionBrief brief={brief} />);
  const allowed = new Set(brief.facts!.map(f => f.text));
  const names = [...(fixture.decision_brief as unknown as { names: string[] }).names].sort((a, b) => b.length - a.length);
  for (const section of brief.sections!) {
    for (const paragraph of section.paragraphs) {
      let text = paragraph;
      for (const name of names) text = text.split(name).join(' ');
      for (const n of numbers(text)) expect(allowed.has(n), `${n} in "${paragraph}"`).toBe(true);
    }
  }
});

it('marks the requested and the recommended option and lists evidence ids', () => {
  render(<DecisionBrief brief={brief} />);
  const row = screen.getAllByRole('row').find(r => r.textContent!.startsWith('MODULAR_MONOLITH'))!;
  expect(row.textContent).toContain('requested, recommended');
  expect(screen.getAllByRole('row').find(r => r.textContent!.startsWith('MICROSERVICES'))!.textContent).toContain('none');
  expect(within(screen.getByRole('region', { name: 'Evidence ids' })).getAllByRole('listitem').length).toBeGreaterThan(0);
});

it('explains that a proposal saved before the fact table has no numbers with sources', () => {
  render(<DecisionBrief brief={{ headline: 'Evidence-backed planning proposal', summary: 'old' }} />);
  expect(screen.getByRole('note').textContent).toMatch(/saved before the brief carried a fact table/);
});
