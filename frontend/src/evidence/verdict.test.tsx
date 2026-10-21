import { expect, it } from 'vitest';
import { readVersion } from './verdict';

const base = { classes: 25, domains: 4, sessions: 2, reviewed: false, facts: { both: 6, staticOnly: 20, runtimeOnly: 3 }, openSuggestions: 0 };
const cov = (observed: number, total: number) => ({ classes: { observed, total, percentage: Math.round(observed / total * 1000) / 10, status: 'AVAILABLE' }, entry_points: { observed: 12, total: 17, percentage: 70.59, status: 'AVAILABLE' } });

it('reports a static-only version as showing nothing about what runs', () => {
  const v = readVersion({ ...base, sessions: 0, coverage: {}, openSuggestions: 3 });
  expect(v.strength).toBe('NONE');
  expect(v.headline).toContain('code structure only');
  expect(v.lines[0]).toMatch(/nothing here shows which code actually runs/);
  expect(v.next).toMatch(/Create and exercise a runtime session/);
});

it('states the real numbers and compares them with the plan rule, not a made-up grade', () => {
  const v = readVersion({ ...base, coverage: cov(12, 25), openSuggestions: 5, topSuggestion: 'Exercise PetController.processUpdateForm' });
  expect(v.strength).toBe('THIN');                                        // 48% is below 50%
  expect(v.lines[0]).toBe('The selected sessions reached 12 of 25 classes (48%) and 12 of 17 entry points.');
  expect(v.lines[1]).toMatch(/well below the 80% share/);
  expect(v.lines.join(' ')).toMatch(/Of 29 dependencies, 6 are confirmed by code and runtime, 20 appear in code only and 3 only at runtime/);
  expect(v.lines.join(' ')).toMatch(/5 open suggestions would add runtime evidence; the highest priority is: Exercise PetController/);
  expect(v.next).toMatch(/Exercise the top suggestion/);
});

it('separates partial from sufficient coverage and says when the rule is met', () => {
  expect(readVersion({ ...base, coverage: cov(15, 25), openSuggestions: 1 }).strength).toBe('PARTIAL');
  const enough = readVersion({ ...base, coverage: cov(21, 25), reviewed: true });
  expect(enough.strength).toBe('ENOUGH');
  expect(enough.headline).toContain('a reviewed set of domain boundaries');
  expect(enough.next).toMatch(/meets the runtime rule/);
});

it('uses singular wording and tolerates a missing percentage', () => {
  const v = readVersion({ ...base, classes: 1, domains: 1, sessions: 1, coverage: { classes: { observed: 1, total: 1, percentage: null } }, facts: { both: 0, staticOnly: 0, runtimeOnly: 0 } });
  expect(v.headline).toBe('This version describes 1 class in 1 domain, built from 1 runtime session.');
  expect(v.strength).toBe('THIN');
  expect(v.lines.some(l => l.includes('dependenc'))).toBe(false);
});

it('tells apart a session that recorded nothing from a low coverage and drops a trailing full stop from the suggestion', () => {
  const v = readVersion({ ...base, coverage: cov(0, 25), openSuggestions: 2, topSuggestion: 'Exercise Pet.save and capture evidence.' });
  expect(v.lines[0]).toMatch(/recorded no calls, so no class was reached/);
  expect(v.lines.join(' ')).toMatch(/evidence\.$/);
  expect(v.lines.join(' ')).not.toMatch(/\.\./);
});
