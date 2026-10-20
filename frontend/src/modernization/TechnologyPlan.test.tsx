import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { TechnologyPlan, type TechnologyPlanData } from './TechnologyPlan';
import fixture from './fixtures/edgecases.technology-plan.json';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const plan = fixture as unknown as TechnologyPlanData;
const mount = (active = false) => render(<TechnologyPlan plan={plan} active={active} activeNote="No review is recorded." explainPath="/x/technology-plan/explain" />);

it('shows the plan as a proposal until a reviewer approves it', () => {
  mount();
  expect(screen.getByRole('status').textContent).toContain('PROPOSAL');
  expect(screen.getByRole('status').textContent).toContain('No review is recorded.');
  cleanup(); mount(true);
  expect(screen.getByRole('status').textContent).toContain('ACTIVE PLAN');
});

it('states the language and runtime recommendations with the reasons', () => {
  mount();
  expect(screen.getByText(/NO LANGUAGE CHANGE\./)).toBeTruthy();
  expect(screen.getByText(/language change is not supported by the evidence/)).toBeTruthy();
  expect(screen.getByText(/JAVA UPGRADE\./)).toBeTruthy();
  expect(screen.getByText(/Java 21 \(LTS\) is the smallest LTS that satisfies every chosen candidate/)).toBeTruthy();
});

it('orders libraries, then Java, then framework moves, naming each affected class and the alternatives not chosen', () => {
  mount();
  const titles = screen.getAllByRole('heading', { level: 3 }).map(h => h.textContent).filter(t => t!.startsWith('Phase'));
  expect(titles).toEqual(['Phase 1: Replace libraries that run on the current Java level', 'Phase 2: Raise Java to 21', 'Phase 3: Move frameworks and namespaces on the new Java level']);
  const servlet = screen.getByRole('article', { name: 'Technology Servlet API on the javax.servlet namespace' });
  expect(within(servlet).getByText('Affected classes (2):').parentElement!.textContent).toContain('AuditFilter, LegacyServlet');
  expect(within(servlet).getByText('NAMESPACE').parentElement!.textContent).toBe('NAMESPACE COUPLED: javax.servlet -> jakarta.servlet: 2 classes use the old namespace (AuditFilter, LegacyServlet).');
  const log4j = screen.getByRole('article', { name: /Technology Apache Log4j 1.x/ });
  expect(within(log4j).getByText('SLF4J 2 with Logback 1.5')).toBeTruthy();
  expect(within(log4j).getByText(/not chosen because it needs Java 11 against Java 8/)).toBeTruthy();
  expect(within(log4j).getByText('Confidence MEDIUM').parentElement!.textContent).toBe('Confidence MEDIUM (3 of 4 inputs): no - Version of the technology is known; yes - Code references are listed from bytecode; yes - Runtime evidence is attached; yes - All feasibility checks pass.');
});

it('labels the optional AI wording, marks a choice outside the curated list as unverified, and works without it', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ ai: { status: 'AI_GENERATED', label: 'AI-written wording. Each recommendation cites the rule it rephrases.', dropped: [{ reason: 'UNCITED_OR_UNKNOWN_CITATION' }],
    recommendations: [{ rule_id: 'log4j-1', choice: 'log4j-2', rationale: 'It keeps the logging API.', citations: ['rule:log4j-1'], verification: 'CURATED' }, { rule_id: 'log4j-1', choice: 'Reload4j', rationale: 'A maintained fork.', citations: ['rule:log4j-1'], verification: 'UNVERIFIED_CONFIRM_BEFORE_USE' }] } }) })));
  mount();
  fireEvent.click(screen.getByRole('button', { name: 'Add AI wording (optional)' }));
  const region = await screen.findByRole('region', { name: 'AI wording' });
  await waitFor(() => expect(within(region).getByText('AI-WRITTEN')).toBeTruthy());
  expect(within(region).getByText('unverified, confirm before use')).toBeTruthy();
  expect(within(region).getByText(/1 recommendation\(s\) were removed by the evidence check/)).toBeTruthy();
});

it('says why no plan is shown when the analysis has no bytecode facts', () => {
  render(<TechnologyPlan plan={{ status: 'NOT_AVAILABLE', reason: 'This analysis has no bytecode facts, so aging technology cannot be assessed; run a new analysis.' }} active={false} activeNote="" explainPath="" />);
  expect(screen.getByRole('note').textContent).toMatch(/no bytecode facts/);
});
