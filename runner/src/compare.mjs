// Replay the same recorded scenarios against the original application and a candidate service, then compare what each returned.
import { routeShape } from './html.mjs';
import { runScenario } from './rea.mjs';

/** Visible text of a page: scripts, styles and tags removed, whitespace collapsed, session ids dropped. */
export function visibleText(html) {
  if (!html) return '';
  return html
    .replace(/<script\b[\s\S]*?<\/script>/gi, ' ').replace(/<style\b[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&')
    .replace(/;jsessionid=[A-Za-z0-9]+/gi, '').replace(/\s+/g, ' ').trim();
}

function tokens(text) { return new Set(text.toLowerCase().split(/[^a-z0-9]+/).filter((t) => t.length > 1)); }

export function similarity(a, b) {
  const x = tokens(a); const y = tokens(b);
  if (!x.size && !y.size) return 1;
  let common = 0;
  for (const t of x) if (y.has(t)) common += 1;
  return Math.round((common / (x.size + y.size - common)) * 1000) / 1000;
}

function rebase(scenario, origin) {
  const move = (u) => { const url = new URL(u); const target = new URL(origin); url.protocol = target.protocol; url.host = target.host; return url.toString(); };
  return { ...scenario, start_url: { ...scenario.start_url, url: move(scenario.start_url.url) },
    actions: scenario.actions.map((a) => (a.action === 'goto' ? { ...a, destination: { ...a.destination, url: move(a.destination.url) } } : a)),
    capture: { ...(scenario.capture || {}), at_end: [...new Set([...(scenario.capture?.at_end || []), 'dom', 'url'])], events: ['network'] } };
}

function outcome(result) {
  const last = result.steps[result.steps.length - 1];
  return {
    completed: result.steps.every((s) => s.status === 'completed'),
    requests: result.transactions.filter((t) => t.url).map((t) => `${t.method} ${routeShape(t.url)} ${t.status ?? 'none'}`),
    final_shape: last?.url ? routeShape(last.url) : null,
    text: visibleText(last?.dom),
    evidence_id: result.evidence_id,
  };
}

/**
 * Each scenario runs once against the baseline and once against the candidate.
 * Equal means the same request sequence (method, route shape, status) and the same final route; the page text is compared for similarity.
 */
export async function compareRuns({ baseline, candidate, scenarios = [], text_threshold = 0.9 }, run = runScenario) {
  if (!Array.isArray(scenarios) || !scenarios.length || scenarios.length > 100) throw Object.assign(new Error('SCENARIOS_INVALID'), { code: 'SCENARIOS_INVALID' });
  const results = [];
  for (const item of scenarios) {
    const name = String(item.name || 'scenario').slice(0, 120);
    try {
      const left = outcome(await run(rebase(item.scenario, baseline), [baseline]));
      const right = outcome(await run(rebase(item.scenario, candidate), [candidate]));
      const textScore = similarity(left.text, right.text);
      const sameRequests = JSON.stringify(left.requests) === JSON.stringify(right.requests);
      const differences = [];
      if (!left.completed) differences.push('The scenario did not complete against the original application.');
      if (!right.completed) differences.push('The scenario did not complete against the candidate service.');
      if (!sameRequests) differences.push(`Requests differ: original [${left.requests.join(', ')}], candidate [${right.requests.join(', ')}].`);
      if (left.final_shape !== right.final_shape) differences.push(`Final page differs: original ${left.final_shape}, candidate ${right.final_shape}.`);
      if (textScore < text_threshold) differences.push(`Page text similarity ${textScore} is below ${text_threshold}.`);
      results.push({ name, status: differences.length ? 'DIFFERENT' : 'EQUIVALENT', differences, text_similarity: textScore,
        baseline: { ...left, text: left.text.slice(0, 2000) }, candidate: { ...right, text: right.text.slice(0, 2000) } });
    } catch (error) {
      results.push({ name, status: 'ERROR', differences: [error.code || String(error)], text_similarity: null });
    }
  }
  const counts = results.reduce((a, r) => ({ ...a, [r.status]: (a[r.status] || 0) + 1 }), {});
  return { baseline, candidate, total: results.length, counts, results, method: 'Same scenario replayed with REA against both origins; requests compared by method, route shape and status; page text by token overlap.' };
}
