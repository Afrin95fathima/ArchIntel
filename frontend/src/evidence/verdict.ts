/** Plain-language reading of one architecture version, computed only from numbers the twin already reports. */
export type Metric = { observed?: number | null; total?: number | null; percentage?: number | null; status?: string };
export type VerdictInput = {
  classes: number; domains: number; sessions: number; reviewed: boolean;
  coverage: Record<string, unknown>;
  facts: { both: number; staticOnly: number; runtimeOnly: number };
  openSuggestions: number; topSuggestion?: string;
};
export type Verdict = { headline: string; strength: 'NONE' | 'THIN' | 'PARTIAL' | 'ENOUGH'; lines: string[]; next: string };

/** The plan's runtime rule asks for this share of a domain's classes to be observed; it is repeated here only to explain the reading. */
export const RUNTIME_TARGET = 80;

const metric = (coverage: Record<string, unknown>, key: string): Metric | null => {
  const value = coverage[key];
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Metric : null;
};
const plural = (n: number, one: string, many: string) => `${n.toLocaleString()} ${n === 1 ? one : many}`;

export function readVersion(input: VerdictInput, target: number = RUNTIME_TARGET): Verdict {
  const classCoverage = metric(input.coverage, 'classes');
  const entryCoverage = metric(input.coverage, 'entry_points');
  const percent = classCoverage?.percentage ?? null;
  const hasRuntime = input.sessions > 0 && classCoverage?.observed != null;
  const strength: Verdict['strength'] = !hasRuntime ? 'NONE' : percent == null ? 'THIN' : percent >= target ? 'ENOUGH' : percent >= 50 ? 'PARTIAL' : 'THIN';
  const headline = `This version describes ${plural(input.classes, 'class', 'classes')} in ${plural(input.domains, 'domain', 'domains')}, built from ${input.sessions ? plural(input.sessions, 'runtime session', 'runtime sessions') : 'code structure only'}${input.reviewed ? ' and a reviewed set of domain boundaries' : ''}.`;
  const lines: string[] = [];
  if (!hasRuntime) lines.push('No runtime session is included, so nothing here shows which code actually runs.');
  else {
    if (classCoverage!.observed === 0) lines.push('The selected runtime sessions recorded no calls, so no class was reached. Check that the agent was connected while the application was exercised.');
    else lines.push(`The selected sessions reached ${classCoverage!.observed!.toLocaleString()} of ${classCoverage!.total?.toLocaleString() ?? 'an unknown number of'} classes${percent == null ? '' : ` (${percent}%)`}${entryCoverage?.observed != null && entryCoverage.total ? ` and ${entryCoverage.observed.toLocaleString()} of ${entryCoverage.total.toLocaleString()} entry points` : ''}.`);
    lines.push(strength === 'ENOUGH' ? `That meets the ${target}% share the plan's runtime rule asks for.`
      : strength === 'PARTIAL' ? `That is below the ${target}% share the plan's runtime rule asks for, so plan decisions will carry a runtime gap.`
      : `That is well below the ${target}% share the plan's runtime rule asks for, so decisions rest mostly on code structure.`);
  }
  const total = input.facts.both + input.facts.staticOnly + input.facts.runtimeOnly;
  if (total) lines.push(`Of ${plural(total, 'dependency', 'dependencies')}, ${input.facts.both.toLocaleString()} are confirmed by code and runtime, ${input.facts.staticOnly.toLocaleString()} appear in code only and ${input.facts.runtimeOnly.toLocaleString()} only at runtime. A code-only dependency is not proof of unused code.`);
  if (input.openSuggestions) lines.push(`${plural(input.openSuggestions, 'open suggestion', 'open suggestions')} would add runtime evidence${input.topSuggestion ? `; the highest priority is: ${input.topSuggestion.replace(/[.\s]+$/, '')}` : ''}.`);
  const next = !input.sessions ? 'Create and exercise a runtime session in Dynamic analysis, then capture a new version with it.'
    : input.openSuggestions && strength !== 'ENOUGH' ? 'Exercise the top suggestion under "What is missing", wait for the telemetry, then capture a new version.'
    : 'The evidence meets the runtime rule for this version; continue to the modernization plan.';
  return { headline, strength, lines, next };
}

export const CLASSIFICATION_LABEL: Record<string, string> = {
  STATIC_AND_DYNAMIC: 'Confirmed by code and runtime',
  STATIC_ONLY: 'In code only',
  DYNAMIC_ONLY: 'Seen at runtime only',
};
export const CLASSIFICATION_MEANING: Record<string, string> = {
  STATIC_AND_DYNAMIC: 'The code analysis found this dependency and a runtime call matched it.',
  STATIC_ONLY: 'The code analysis found it but no selected session called it. This does not prove the code is unused.',
  DYNAMIC_ONLY: 'A runtime call was seen that the code analysis did not list, for example a call through a framework or a library.',
};
export const MEASURE_LABEL: Record<string, string> = {
  classes: 'Classes reached', dependencies: 'Dependencies seen', methods: 'Methods reached', entry_points: 'Entry points reached', domains: 'Domains reached',
};
export const humanize = (value: string) => value.toLowerCase().replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
