"""The decision brief, written from the plan document and the static analysis.

Every number in the brief text is inserted through `Facts.num`, which also records it (with its source) in the fact
table that heads the brief. `unregistered_numbers` re-reads the finished text and reports any number that is not in
that table, so a hand-typed or stale figure cannot get in unnoticed.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter

from app.insight.model import InsightModel
from app.insight import debt as debt_module, lifecycle
from .blockers import BLOCKERS, explain as explain_blocker

NUMBER = re.compile(r'(?<![\w.])\d+(?:\.\d+)?(?![\w])')
HARD = ('CROSS_DOMAIN_CYCLE', 'SHARED_PERSISTENCE_REVIEW', 'EVIDENCE_CONFLICT')


def _format(value):
    """Integers as integers, decimals as Python prints them (20.0, 66.67), the same text the debt-rate API returns."""
    return str(value) if isinstance(value, int) else str(round(value, 2))


class Facts:
    def __init__(self):
        self.rows, self.names = {}, set()

    def num(self, key, label, value, source, unit=''):
        text = _format(value)
        value = float(text) if '.' in text else int(text)
        existing = self.rows.get(key)
        if existing and existing['value'] != value:
            raise ValueError(f'fact {key} registered with two values: {existing["value"]} and {value}')
        self.rows[key] = dict(id=key, label=label, value=value, text=text, unit=unit, source=source)
        return text + ('%' if unit == '%' else '')

    def name(self, text):
        self.names.add(text)
        return text

    def table(self):
        return sorted(self.rows.values(), key=lambda r: r['id'])


def _list(F, items, limit=4):
    items = [F.name(i) for i in items]
    if len(items) <= limit:
        return ', '.join(items)
    key = 'more_' + hashlib.sha256('|'.join(items).encode()).hexdigest()[:8]
    return ', '.join(items[:limit]) + f" and {F.num(key, 'Further items not listed by name', len(items) - limit, 'brief: length of the listed set')} more"


def _plural(count, one, many=None):
    return one if count == 1 else (many or one + 's')


def _texts(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _texts(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _texts(item)


def unregistered_numbers(brief: dict) -> list[str]:
    """Numbers that appear in the brief text but are not in its fact table."""
    allowed = {r.get('text') or _format(r['value']) for r in brief['facts']}
    names = sorted(brief['names'], key=len, reverse=True)
    problems = []
    for section in brief['sections']:
        for text in _texts(dict(title=section['title'], paragraphs=section['paragraphs'])):
            for name in names:
                text = text.replace(name, ' ')
            problems += [n for n in NUMBER.findall(text) if n not in allowed]
    return sorted(set(problems))


def build(result: dict, static: dict, domains: list[dict], options: dict, evidence_by_id: dict, shared: dict | None = None) -> dict:
    F = Facts()
    assessments = result['assessments']
    D = len(assessments)
    summary = static.get('summary', {})
    artifact = (static.get('artifact') or {}).get('filename') or 'the analyzed artifact'
    strategy = options['strategy']
    domain_name = {a['domain_id']: a['domain_name'] for a in assessments}
    findings = result['findings']
    model = shared['model'] if shared else InsightModel('brief', static)
    try:
        debt = debt_module.detect(model)
    except Exception as error:      # the brief must not block plan creation; the gap is stated in the text
        debt = None
        debt_error = type(error).__name__
    lifecycle_findings = (shared['lifecycle']['findings'] if shared else lifecycle.evaluate(model, static.get('tech_inventory'))['findings']) if model.facts_available else None
    rows = result['domain_dependency_matrix'].get('rows', [])
    cross_edges = sum(r['edge_count'] for r in rows)
    domain_pairs = len(rows)
    in_cycle = sorted({d for w in result['waves'] for g in w['coupled_groups'] for d in g})
    blocked = [a for a in assessments if a.get('hard_blockers')]
    shared = sorted({s for f in findings if f['kind'] == 'SHARED_PERSISTENCE_CANDIDATE' for s in f['subjects']})
    ready = [a for a in assessments if not a.get('hard_blockers') and next(d for d in result['decisions'] if d['domain_id'] == a['domain_id'])['kind'] == 'PREPARE_FOR_EXTRACTION']
    classes = int(summary.get('class_count') or sum(len(d['classes']) for d in domains))
    packages = summary.get('package_count')
    cs = F.num('classes', 'Analyzed classes', classes, 'static summary: class_count')
    ps = F.num('packages', 'Packages', packages, 'static summary: package_count') if packages is not None else None
    ds = F.num('domains', 'Candidate domains', D, 'plan: assessments')
    es = F.num('cross_domain_edges', 'Cross-domain dependency edges', cross_edges, 'plan: domain_dependency_matrix rows, sum of edge_count')
    pairs = F.num('cross_domain_pairs', 'Domain pairs with a dependency', domain_pairs, 'plan: domain_dependency_matrix rows')
    all_names = [domain_name[a['domain_id']] for a in assessments]
    scale = F.num('score_scale', 'Score scale maximum', 100, 'score definitions (glossary: readiness, confidence)')

    # 1. The decision
    decision_text = (f"Decide how to modernize {F.name(artifact)} ({cs} classes{', ' + ps + ' packages' if ps else ''}, {ds} candidate domains: {_list(F, all_names, 5)}). "
                     f"You requested {F.name(strategy)} with the objective: {options['objective']}")

    # 2. Recommendation (deterministic rule, stated)
    bn = F.num('blocked_domains', 'Domains with a hard blocker', len(blocked), 'plan: assessments[].hard_blockers')
    if blocked:
        recommended = 'MODULAR_MONOLITH'
        rule = 'Recommend MODULAR_MONOLITH when any domain has a hard blocker (dependency cycle, shared data, evidence conflict).'
        why = (f"{bn} of {ds} domains have hard blockers ({_list(F, [a['domain_name'] for a in blocked])}). Separating them now would turn {es} cross-domain dependency edges between {pairs} domain pairs into remote calls. "
               f"Settle the boundaries in-process first.")
    elif ready:
        recommended = 'HYBRID'
        rule = 'Recommend HYBRID when no domain has a hard blocker and at least one domain has the decision PREPARE_FOR_EXTRACTION.'
        why = (f"{F.num('ready_domains', 'Domains ready to prepare for extraction', len(ready), 'plan: decisions')} of {ds} domains ({_list(F, [a['domain_name'] for a in ready])}) have no hard blocker and enough evidence. "
               f"Prepare those for extraction and keep the other {F.num('in_process_domains', 'Domains kept in-process', D - len(ready), 'plan: decisions')} in-process.")
    else:
        recommended = 'MODULAR_MONOLITH'
        scores = sorted(assessments, key=lambda a: a['confidence_score'])
        rule = 'Recommend MODULAR_MONOLITH when no domain has a hard blocker but none has the decision PREPARE_FOR_EXTRACTION.'
        why = (f"No domain has both full evidence and no blocker. Confidence ranges from {F.num('confidence_min', 'Lowest domain confidence', scores[0]['confidence_score'], 'plan: assessments[].confidence_score')} "
               f"({F.name(scores[0]['domain_name'])}) to {F.num('confidence_max', 'Highest domain confidence', scores[-1]['confidence_score'], 'plan: assessments[].confidence_score')} ({F.name(scores[-1]['domain_name'])}) out of {scale}. "
               f"Collect the missing evidence before choosing extraction.")
    recommendation = dict(option=recommended, rule=rule, rationale=why, matches_request=recommended == strategy,
        note=f"{F.name(recommended)} is the result of the rule for these {ds} domains; your requested option {F.name(strategy)} stays selected.")

    # 3. Options with measured trade-offs
    java = next((f for f in (lifecycle_findings or []) if f['rule_id'] == 'java-class-target'), None)
    aging = [f for f in (lifecycle_findings or []) if f['status'] in ('aging', 'end-of-life') and f['rule_id'] != 'java-class-target']
    namespace = next((f for f in (lifecycle_findings or []) if f['rule_id'].startswith('javax')), None)
    comparison = {r['strategy']: r for r in result['decision_brief']['strategy_comparison']}
    tradeoffs = {
        'MODULAR_MONOLITH': [f"Keeps one deployment unit: the {es} cross-domain dependency edges stay in-process and become module contracts.",
                             f"{bn} {_plural(len(blocked), 'domain')} with hard blockers ({_list(F, [a['domain_name'] for a in blocked]) or 'none'}) can be fixed without changing deployment." if blocked else "No domain has a hard blocker."],
        'MICROSERVICES': [f"Turns {es} cross-domain dependency edges between {pairs} domain pairs into remote calls.",
                          (f"{F.num('shared_resources', 'Shared database resources', len(shared), 'plan: SHARED_PERSISTENCE_CANDIDATE findings')} shared database {_plural(len(shared), 'resource')} ({_list(F, shared)}) need an ownership split first.") if shared else 'No database resource is called by more than one domain in the selected evidence.',
                          (f"{F.num('cycle_domains', 'Domains in dependency cycles', len(in_cycle), 'plan: waves[].coupled_groups')} {_plural(len(in_cycle), 'domain')} in cycles ({_list(F, [domain_name[d] for d in in_cycle])}) cannot be separated one by one.") if in_cycle else f'None of the {ds} domains is in a dependency cycle.'],
        'HYBRID': [(f"{F.num('ready_domains', 'Domains ready to prepare for extraction', len(ready), 'plan: decisions')} of {ds} domains ({_list(F, [a['domain_name'] for a in ready])}) can be prepared for extraction; the remaining {F.num('in_process_domains', 'Domains kept in-process', D - len(ready), 'plan: decisions')} stay in-process.")
                   if ready else f"No domain is ready for extraction now; all {ds} stay in-process until their blockers are resolved."],
        'CLOUD_REFACTOR': [f"No target platform, deployment constraint or cost objective was supplied for {F.name(artifact)}, so no cloud trade-off can be measured."],
        'JAVA_UPGRADE': [(f"Class files target {F.name(str(java['version_found']))} ({java['status']}) in {F.num('java_classes', 'Classes at the current Java target', java['affected_class_count'], 'lifecycle rules: java-class-target')} classes; the rules recommend {F.name(java.get('recommended_alternative') or 'a supported LTS')}.")
                         if java else "Java target levels are not measured because this analysis has no bytecode facts."],
        'FRAMEWORK_UPGRADE': [(f"{F.num('aging_technologies', 'Aging or end-of-life technologies', len(aging), 'lifecycle rules')} {_plural(len(aging), 'technology', 'technologies')} flagged: "
                              + '; '.join(F.name(f['technology']) + ' ' + f['status'] + ' (' + F.num('aging_' + f['rule_id'], f['technology'] + ' affected classes', f['affected_class_count'], 'lifecycle rules: ' + f['rule_id']) + ' ' + _plural(f['affected_class_count'], 'class', 'classes') + ')' for f in aging[:4]) + '.') if aging
                              else (f'The lifecycle rules flag no aging or end-of-life framework in {F.name(artifact)}.' if lifecycle_findings is not None else 'Framework age is not measured because this analysis has no bytecode facts.')]
                             + ([f"The javax namespace is used by {F.num('javax_classes', 'Classes using javax APIs', namespace['affected_class_count'], 'lifecycle rules: ' + namespace['rule_id'])} classes, which a Jakarta move would change."] if namespace and namespace['affected_class_count'] else []),
    }
    options_out = []
    for name in ('MODULAR_MONOLITH', 'MICROSERVICES', 'HYBRID', 'CLOUD_REFACTOR', 'JAVA_UPGRADE', 'FRAMEWORK_UPGRADE'):
        row = comparison[name]
        options_out.append(dict(strategy=name, status=row['status'], selected_by_user=name == strategy, recommended=name == recommended, tradeoffs=tradeoffs[name],
                                finding_ids=row['finding_ids'], blockers=sorted({b for a in blocked for b in a['hard_blockers']}) if name in ('MICROSERVICES', 'HYBRID') else []))

    # 4. Scope
    planned = sum(len(d['classes']) for d in domains)
    entries = model.entry_points['items']
    scope_text = (f"The plan covers {F.num('planned_classes', 'Classes assigned to plan components', planned, 'plan: target.components')} of {cs} classes in {ds} domains. "
                  f"{F.num('entry_points', 'Detected entry points', len(entries), 'insight: entry-point detection')} entry points were detected"
                  + (f" ({_list(F, [e['handler_class'].rsplit('.', 1)[-1] + '.' + e['handler_method'] + '()' for e in entries], 3)})." if entries else '.'))

    # 5. Blockers and prerequisites by name
    per_code = {}
    for a in assessments:
        for code in a['blockers']:
            per_code.setdefault(code, []).append(a['domain_name'])
    blockers = []
    for code, who in sorted(per_code.items(), key=lambda kv: (code_rank(kv[0]), kv[0])):
        meaning = BLOCKERS.get(code, ('Needs review.', 'Review the cited evidence.', None))
        detail = next((explain_blocker(code, a['domain_name'], [f for f in findings if f['domain_id'] == a['domain_id']]) for a in assessments if code in a['blockers']), None)
        blockers.append(dict(code=code, hard=code in HARD, meaning=meaning[0], resolve=meaning[1], domains=who, subjects=(detail or {}).get('subjects', [])))
    prerequisites = [dict(code=code, meaning=BLOCKERS[code][0], resolve=BLOCKERS[code][1]) for code in ('PINNED_SOURCE_AND_PASSING_BUILD', 'BEHAVIORAL_CONTRACTS', 'DATA_OWNERSHIP_REVIEW', 'HUMAN_CHANGE_APPROVAL')]
    block_text = [f"{F.name(b['code'])} ({'hard blocker' if b['hard'] else 'blocker'}) affects {F.num('blocker_' + b['code'], b['code'] + ' domains', len(b['domains']), 'plan: assessments[].blockers')} of {ds} domains ({_list(F, b['domains'])}): {b['meaning']} Resolve: {b['resolve']}" for b in blockers if b['code'] not in {p['code'] for p in prerequisites}]
    prerequisite_text = [f"{F.name(p['code'])}: {p['meaning']} Resolve: {p['resolve']}" for p in prerequisites]

    # 6. Risks with percentages where measured
    risks = []
    if debt:
        for rate in sorted((r for r in debt['rates']['rates'] if r['status'] == 'MEASURED' and r['numerator']), key=lambda r: (-r['percentage'], r['id']))[:5]:
            key = 'rate_' + rate['id']
            text = (f"{rate['label']}: {F.num(key + '_n', rate['label'] + ' count', rate['numerator'], 'technical debt rates: ' + rate['id'])} of {F.num(key + '_d', rate['label'] + ' population', rate['denominator'], 'technical debt rates: ' + rate['id'])} "
                    f"{rate['unit']} ({F.num(key + '_pct', rate['label'] + ' percentage', rate['percentage'], 'technical debt rates: ' + rate['id'], '%')}).")
            risks.append(dict(kind='technical-debt', id=rate['id'], text=text, percentage=rate['percentage'], numerator=rate['numerator'], denominator=rate['denominator']))
        unmeasured = [r['label'] for r in debt['rates']['rates'] if r['status'] == 'NOT_MEASURED']
    else:
        unmeasured = []
    if blocked:
        risks.append(dict(kind='plan', id='blocked-domains', text=f"{bn} of {ds} domains ({F.num('blocked_pct', 'Hard-blocked domain share', round(100 * len(blocked) / D, 1), 'plan: assessments', '%')}) have a hard blocker.",
                          percentage=round(100 * len(blocked) / D, 1), numerator=len(blocked), denominator=D))
    risk_note = ('Not measured: ' + '; '.join(F.name(u) for u in unmeasured) + '.') if unmeasured else (f'Technical-debt rates could not be computed ({debt_error}).' if debt is None else None)

    # 7. Confidence and what is unobserved
    ranked = sorted(assessments, key=lambda a: a['confidence_score'])
    coverage = [a['runtime_coverage']['classes'] for a in assessments]
    has_runtime = any(c.get('percentage') is not None for c in coverage)
    conf = [f"Domain confidence runs from {F.num('confidence_min', 'Lowest domain confidence', ranked[0]['confidence_score'], 'plan: assessments[].confidence_score')} ({F.name(ranked[0]['domain_name'])}) "
            f"to {F.num('confidence_max', 'Highest domain confidence', ranked[-1]['confidence_score'], 'plan: assessments[].confidence_score')} ({F.name(ranked[-1]['domain_name'])}) out of {scale}."]
    if has_runtime:
        seen, total = sum(c['observed'] for c in coverage), sum(c['total'] for c in coverage)
        conf.append(f"Runtime sessions observed {F.num('observed_classes', 'Observed classes', seen, 'plan: assessments[].runtime_coverage')} of {F.num('observed_total', 'Classes in domains', total, 'plan: assessments[].runtime_coverage')} classes "
                    f"({F.num('observed_pct', 'Observed class percentage', round(100 * seen / total, 1), 'plan: assessments[].runtime_coverage', '%')}).")
        low = [a['domain_name'] for a in assessments if (a['runtime_coverage']['classes'].get('percentage') or 0) < 80]
        if low:
            conf.append(f"{F.num('low_coverage_domains', 'Domains below the observation threshold', len(low), 'plan: assessments[].runtime_coverage')} {_plural(len(low), 'domain')} below {F.num('observation_threshold', 'Minimum observed class percentage per domain', 80, 'plan rule: LIMITED_OBSERVATION threshold', '%')} observed: {_list(F, low)}. Unobserved never means unused.")
        entry_rate = next((r for r in (debt['rates']['rates'] if debt else []) if r['id'] == 'entry-points-unobserved' and r['status'] == 'MEASURED'), None)
        if entry_rate:
            conf.append(f"{F.num('unobserved_entry_points', 'Entry points never observed', entry_rate['numerator'], 'technical debt rates: entry-points-unobserved')} of {F.num('entry_points', 'Detected entry points', entry_rate['denominator'], 'technical debt rates: entry-points-unobserved')} entry points were never observed ({F.num('unobserved_entry_pct', 'Entry points never observed percentage', entry_rate['percentage'], 'technical debt rates: entry-points-unobserved', '%')}).")
    else:
        conf.append(f"No runtime session is attached to {F.name(artifact)}, so no class, entry point or database call was observed; runtime coverage and data quality are excluded from confidence.")

    # 8. What is not known
    missing = {}
    for a in assessments:
        for e in a.get('confidence_not_measured', []) + a.get('structural_not_measured', []):
            entry = missing.setdefault(e['label'], dict(domains=set(), reasons=set()))
            entry['domains'].add(a['domain_name']); entry['reasons'].add(e['reason'])
    unknown = []
    for label, entry in sorted(missing.items()):
        key = 'unknown_' + re.sub(r'[^a-z0-9]+', '_', label.lower())
        n = F.num(key, label + ' domains', len(entry['domains']), 'plan: assessments[].confidence_not_measured')
        who = f" ({_list(F, sorted(entry['domains']))})" if len(entry['domains']) < D else ''
        unknown.append(f"{label} is not measured for {n} of {ds} domains{who}: {'; '.join(sorted(entry['reasons']))}.")
    questions = []
    if shared:
        questions.append(f"Which domain owns {_list(F, shared)}, and which transactions span the domains that call it?")
    if in_cycle:
        questions.append(f"Which direction of the cycle between {_list(F, [domain_name[d] for d in in_cycle])} is intended?")
    if not questions:
        questions.append(f"Which user-visible workflows of {F.name(artifact)} must stay unchanged? No behavioral contract tests are recorded.")

    # 9. Non-functional constraints (from the responsibility analysis; text uses registered numbers and names only)
    nf = result.get('nonfunctional') or {}
    if nf.get('status') == 'AVAILABLE':
        nf_risks = nf['risks']
        nf_text = [f"{F.num('nfr_risks', 'Non-functional risk indicators', len(nf_risks), 'responsibility analysis: risks')} non-functional risk {_plural(len(nf_risks), 'indicator')} "
                   f"{'was' if len(nf_risks) == 1 else 'were'} derived from the bytecode of {F.name(artifact)}: {F.num('nfr_high', 'High non-functional risks', sum(r['severity'] == 'HIGH' for r in nf_risks), 'responsibility analysis: risks')} high and "
                   f"{F.num('nfr_medium', 'Medium non-functional risks', sum(r['severity'] == 'MEDIUM' for r in nf_risks), 'responsibility analysis: risks')} medium. They are structural indicators, not measurements; "
                   f"{F.num('nfr_runtime', 'Risks needing runtime validation', sum(r['runtime_validation_required'] for r in nf_risks), 'responsibility analysis: risks')} of them need runtime validation before they are acted on."]
        grouped = {}
        for r in nf_risks:
            g = grouped.setdefault(r['rule_id'], dict(title=r['title'], severity=r['severity'], components=set(), domains=set(), detection=r['detection_status']))
            g['components'].update(r['affected_components']); g['domains'].update(d['name'] for d in r['domains'])
        for rule_id, g in sorted(grouped.items(), key=lambda kv: ({'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}[kv[1]['severity']], -len(kv[1]['components']), kv[0]))[:5]:
            key = 'nfr_aff_' + re.sub(r'[^a-z0-9]+', '_', rule_id.lower())
            nf_text.append(f"{F.name(g['title'])} ({g['severity'].lower()}, {g['detection'].lower()}): affects {F.num(key, g['title'] + ' affected components', len(g['components']), 'responsibility analysis: risks')} "
                           f"{_plural(len(g['components']), 'component')} in {_list(F, sorted(g['domains']), 3)}.")
        technical = [c['name'] for c in nf['capabilities'] if c['kind'] == 'TECHNICAL']
        if technical:
            nf_text.append(f"{F.num('nfr_technical', 'Domains holding technical concerns', len(technical), 'responsibility analysis: capabilities')} candidate {_plural(len(technical), 'domain')} "
                           f"({_list(F, technical)}) {'holds' if len(technical) == 1 else 'hold'} technical concerns rather than a business capability; keep {'it' if len(technical) == 1 else 'them'} as shared configuration or {'a library' if len(technical) == 1 else 'libraries'}, because {'it is not a service candidate' if len(technical) == 1 else 'they are not service candidates'}.")
        sharing = [i['name'] for i in nf['cross_cutting'] if i['kind'] != 'EXTERNAL_LIBRARY']
        libraries = [i['name'] for i in nf['cross_cutting'] if i['kind'] == 'EXTERNAL_LIBRARY']
        if sharing:
            nf_text.append(f"{F.num('nfr_shared', 'Components shared across domains', len(sharing), 'responsibility analysis: cross-cutting components')} {_plural(len(sharing), 'component')} "
                           f"({_list(F, sharing)}) {'is' if len(sharing) == 1 else 'are'} used by two or more domains; decide on a library, a module or an owner before separating those domains, because a service would add a network call to every user.")
        if libraries:
            nf_text.append(f"{F.num('nfr_libraries', 'Libraries used across domains', len(libraries), 'responsibility analysis: cross-cutting components')} {_plural(len(libraries), 'library', 'libraries')} "
                           f"({_list(F, libraries, 3)}) already cross domain boundaries as ordinary dependencies; each extracted service includes them and none is a service candidate.")
        nf_text.append('Not examined: ' + '; '.join(F.name(x) for x in nf['not_examined']) + '. A control that does not appear in the bytecode is not proven absent.')
    else:
        nf_text = [nf.get('reason') or 'Non-functional constraints were not derived for this plan.', f'The recommendation for {F.name(artifact)} therefore does not account for security, performance, reliability or data-integrity concerns.']

    # evidence ids
    used = []
    for f in sorted(findings, key=lambda f: (f['severity'] != 'HIGH', f['id'])):
        for eid in f['evidence_ids']:
            if eid not in used and eid in evidence_by_id:
                used.append(eid)
    evidence_list = [dict(id=eid, kind=evidence_by_id[eid]['kind'], source=evidence_by_id[eid].get('source'), target=evidence_by_id[eid].get('target')) for eid in used[:30]]

    actions = [f"{a['domain_name']}: {next(d for d in result['decisions'] if d['domain_id'] == a['domain_id'])['kind']} ({F.num('actions_' + a['domain_id'][:8], a['domain_name'] + ' blockers', len(a['blockers']), 'plan: assessments[].blockers')} blockers)"
               for a in sorted(assessments, key=lambda a: (a.get('cost_index') or 0, a['domain_id']))[:3]]
    sections = [
        dict(id='decision', title='The decision', paragraphs=[decision_text]),
        dict(id='recommendation', title='Recommended option and why', paragraphs=[f"Recommended: {F.name(recommended)}. {why}", f"Rule applied: {rule}", recommendation['note']]),
        dict(id='options', title='Options considered', paragraphs=[f"{F.name(o['strategy'])}{' (requested)' if o['selected_by_user'] else ''}{' (recommended)' if o['recommended'] else ''}: " + ' '.join(o['tradeoffs']) for o in options_out]),
        dict(id='scope', title='Scope', paragraphs=[scope_text]),
        dict(id='blockers', title='Blockers and prerequisites', paragraphs=block_text + prerequisite_text),
        dict(id='nonfunctional', title='Non-functional constraints', paragraphs=nf_text),
        dict(id='risks', title='Risks', paragraphs=[r['text'] for r in risks] + ([risk_note] if risk_note else [])),
        dict(id='confidence', title='Confidence and what was not observed', paragraphs=conf),
        dict(id='unknowns', title='What is not known', paragraphs=unknown + questions),
    ]
    brief = dict(facts=F.table(), names=sorted(F.names), sections=sections, decision=decision_text, recommendation=recommendation, options=options_out,
        scope=dict(text=scope_text, classes=classes, planned_classes=planned, domains=all_names, entry_points=len(entries)), blockers=blockers, prerequisites=prerequisites,
        risks=risks, confidence=conf, unknowns=unknown, questions=questions, evidence=evidence_list, top_actions=actions)
    brief['numbers_check'] = dict(unregistered=unregistered_numbers(brief))
    return brief


def code_rank(code):
    return (0 if code in HARD else 1 if code not in ('PINNED_SOURCE_AND_PASSING_BUILD', 'BEHAVIORAL_CONTRACTS', 'DATA_OWNERSHIP_REVIEW', 'HUMAN_CHANGE_APPROVAL') else 2)


def merge(legacy: dict, extra: dict, result: dict) -> None:
    """Replace the generic text of the earlier brief with the data-derived brief; keep every key existing readers use."""
    recommendation = extra['recommendation']
    findings = result['findings']
    legacy.update(headline=extra['decision'], summary=extra['sections'][1]['paragraphs'][0],
        strategy_fit=dict(recommendation=recommendation['option'], rationale=recommendation['rationale'], rule=recommendation['rule'], matches_request=recommendation['matches_request'],
                          metrics=legacy['baseline_metrics'], confidence='HEURISTIC_REVIEW_REQUIRED'),
        top_actions=extra['top_actions'], top_risks=[r['text'] for r in extra['risks'][:3]], unresolved_questions=extra['questions'] + extra['unknowns'],
        next_step='Start with ' + extra['top_actions'][0] + '; then resolve the blockers listed under "Blockers and prerequisites".' if extra['top_actions'] else legacy['next_step'])
    by_kind = {}
    for f in findings:
        by_kind.setdefault(f['kind'], []).append(f)
    for risk in legacy['material_risks']:
        kinds = {f['kind'] for f in findings if f['id'] in risk['finding_ids']}
        kind = sorted(kinds)[0] if kinds else None
        if kind:
            domains = sorted({next(a['domain_name'] for a in result['assessments'] if a['domain_id'] == f['domain_id']) for f in by_kind[kind]})
            risk['message'] = f"{kind} in {', '.join(domains)}: {by_kind[kind][0]['text']}"
    options = {o['strategy']: o for o in extra['options']}
    for row in legacy['strategy_comparison']:
        option = options[row['strategy']]
        row.update(rationale=' '.join(option['tradeoffs']), tradeoffs=option['tradeoffs'], recommended=option['recommended'])
        if row['strategy'] in ('CLOUD_REFACTOR', 'JAVA_UPGRADE', 'FRAMEWORK_UPGRADE'):
            row['unknowns'] = [t for t in option['tradeoffs']] + [f"No target version or platform is chosen for {row['strategy']}, and dependency compatibility is not checked."]
        else:
            row['unknowns'] = extra['questions'] + extra['unknowns'][:2]
    for key in ('decision', 'facts', 'names', 'sections', 'recommendation', 'options', 'scope', 'blockers', 'prerequisites', 'risks', 'confidence', 'unknowns', 'questions', 'evidence', 'numbers_check'):
        legacy[key] = extra[key]
