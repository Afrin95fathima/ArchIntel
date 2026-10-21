"""One report model, rendered to HTML and PDF. Every figure is read from the same analysis, plan and evidence the app shows.

Each section has `plain` (2-4 sentences naming the application's own classes, domains and numbers) and `technical`
(tables, lists and diagrams with evidence ids). Numbers in the plain text go through `Facts`, so they appear in the fact
table with their source and `unregistered_plain_numbers` can prove no figure was typed by hand.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import AnalysisRun, Application, Artifact
from app.evidence.models import Evidence
from app.insight import cycles as cycles_module, debt as debt_module, diagrams
from app.insight.glossary import entries as glossary_entries
from app.modernization.brief import Facts, NUMBER, _format
from app.modernization.engine import analysis_context


def _plural(count, one, many=None):
    return one if count == 1 else (many or one + 's')


def _short(name):
    return name.rsplit('.', 1)[-1]


def _names(F, items, limit=4):
    items = [F.name(i) for i in items]
    if len(items) <= limit:
        return ', '.join(items)
    extra = F.num('more_' + str(abs(hash(tuple(items))) % 10 ** 8), 'Further items not listed by name', len(items) - limit, 'report: length of the listed set')
    return ', '.join(items[:limit]) + f' and {extra} more'


SHORT_ACTION = {'BREAK_CYCLE_FIRST': 'break the dependency cycle around {n}', 'ISOLATE_DATA_FIRST': 'settle who owns the shared data of {n}', 'REDUCE_COUPLING_FIRST': 'narrow the interface of {n}',
                'COLLECT_MORE_EVIDENCE': 'collect more evidence for {n}', 'RETAIN_MODULAR_MONOLITH': 'keep {n} in-process behind a module contract', 'PREPARE_FOR_EXTRACTION': 'prepare {n} for extraction',
                'MANUAL_REVIEW_REQUIRED': 'resolve the evidence conflict in {n}'}


KIND_LABEL = {'HTTP_ENDPOINT': ('HTTP endpoint', 'HTTP endpoints'), 'MAIN_METHOD': ('main method', 'main methods'), 'SCHEDULED_JOB': ('scheduled job', 'scheduled jobs'),
              'MESSAGE_LISTENER': ('message listener', 'message listeners'), 'EVENT_LISTENER': ('event listener', 'event listeners'), 'SERVLET': ('servlet', 'servlets'),
              'SERVLET_FILTER': ('servlet filter', 'servlet filters'), 'STRUTS_ACTION': ('Struts action', 'Struts actions'), 'LIFECYCLE_CALLBACK': ('lifecycle callback', 'lifecycle callbacks')}


def kind_label(kind, count):
    one, many = KIND_LABEL.get(kind, (kind.replace('_', ' ').lower(), kind.replace('_', ' ').lower() + 's'))
    return one if count == 1 else many


def short_item(text):
    """Class names without their package, for tables where the full name is in the appendix."""
    if ' -> ' in text:
        return ' -> '.join(short_item(part) for part in text.split(' -> '))
    if '#' in text:
        owner, member = text.split('#', 1)
        return _short(owner) + '#' + member
    if ' uses ' in text:
        owner, rest = text.split(' uses ', 1)
        return _short(owner) + ' uses ' + rest
    return _short(text) if '.' in text and ' ' not in text else text


def measured_text(measured):
    def value(v):
        return ', '.join(f'{k} {n}' for k, n in v.items()) if isinstance(v, dict) else str(v)
    return '; '.join(f"{k.replace('_', ' ')} {value(v)}" for k, v in measured.items())


def first_sentence(text):
    import re
    return re.split(r'(?<=[.!?])\s+(?=[A-Z0-9(])', text.strip())[0].rstrip('.')


def table(caption, columns, rows, note=None):
    return dict(type='table', caption=caption, columns=columns, rows=[[('' if c is None else str(c)) for c in row] for row in rows], note=note)


def listing(title, items):
    return dict(type='list', title=title, items=[str(i) for i in items])


def build(db, version, assessment, sessions, projection) -> dict:
    run = db.get(AnalysisRun, version.analysis_id)
    application = db.get(Application, version.application_id)
    artifact = db.get(Artifact, run.artifact_id)
    static, doc, manifest = run.result or {}, assessment.document, version.manifest
    domains = version.document['domains']
    ctx = analysis_context(version, static, domains, bool(manifest.get('runtime_session_ids')))
    model, life = ctx['model'], ctx['lifecycle']
    debt = debt_module.detect(model)
    cyc = cycles_module.analyse(model)
    hld = diagrams.hld(model)
    plan = doc.get('technology_plan') or {}
    brief = doc.get('decision_brief') or {}
    rates = {r['id']: r for r in debt['rates']['rates']}
    summary = static.get('summary', {})
    has_runtime = bool(sessions)
    F = Facts()
    S = {}
    artifact_name = (artifact.filename if artifact else None) or (static.get('artifact') or {}).get('filename') or application.name
    classes = int(summary.get('class_count') or len(static.get('classes', [])))
    packages = summary.get('package_count')
    cs = F.num('classes', 'Analyzed classes', classes, 'static summary: class_count')
    ps = F.num('packages', 'Packages', packages, 'static summary: package_count') if packages is not None else None
    ds = F.num('domains', 'Candidate domains', len(domains), 'version: domains')
    domain_names = [d['name'] for d in domains]
    inventory = static.get('tech_inventory') or {}
    frameworks = [f"{f['name']} {', '.join(f.get('versions', []))}".strip() for f in inventory.get('frameworks', [])]
    java = plan.get('runtime', {}).get('current_java') if plan and plan.get('status') != 'NOT_AVAILABLE' else None
    if java is None:
        targets = inventory.get('bytecode', {}).get('java_targets', [])
        java = max(targets) if targets else None
    entries = model.entry_points['items']
    entry_kinds = Counter(e['kind'] for e in entries)

    def rate_phrase(rate):
        key = 'rate_' + rate['id']
        return (f"{rate['label'].lower()} ({F.num(key + '_n', rate['label'] + ' count', rate['numerator'], 'technical debt rates: ' + rate['id'])} of "
                f"{F.num(key + '_d', rate['label'] + ' population', rate['denominator'], 'technical debt rates: ' + rate['id'])} {rate['unit']}, "
                f"{F.num(key + '_pct', rate['label'] + ' percentage', rate['percentage'], 'technical debt rates: ' + rate['id'], '%')})")

    measured = sorted((r for r in rates.values() if r['status'] == 'MEASURED' and r['numerator'] and r['id'] != 'any-class'), key=lambda r: (-r['percentage'], r['id']))
    top5 = measured[:5]
    phases = plan.get('phases', []) if plan.get('status') != 'NOT_AVAILABLE' else []
    items = {i['rule_id']: i for i in plan.get('items', [])} if phases else {}
    decisions = {d['domain_id']: d for d in doc['decisions']}
    by_cost = sorted(doc['assessments'], key=lambda a: (a.get('cost_index') or 0, a['domain_id']))
    actions = []
    if phases:
        first = phases[0]
        actions.append(f"{first['title'][0].lower() + first['title'][1:]} ({_names(F, [items[r]['technology'] for r in first['items']], 3)})")
    for a in by_cost[:3 - len(actions)]:
        actions.append(SHORT_ACTION[decisions[a['domain_id']]['kind']].format(n=F.name(a['domain_name'])))

    def adopt(sentence):
        """Register in this report's fact table every number of a reused sentence, taken from the brief's fact table (same value, same source)."""
        text = sentence
        for name in sorted(F.names | set(brief.get('names', [])), key=len, reverse=True):
            text = text.replace(name, ' ')
        for number in NUMBER.findall(text):
            if any(f.get('text') == number for f in F.rows.values()):
                continue
            fact = next((f for f in brief.get('facts', []) if f.get('text') == number), None)
            if fact and fact['id'] not in F.rows:
                F.rows[fact['id']] = dict(fact)
        return sentence
    # Non-functional constraints come from the plan document; the plain sentence is the brief's own paragraph, so its numbers stay registered.
    nfr = doc.get('nonfunctional') or {}
    nfr_section = next((x for x in brief.get('sections', []) if x['id'] == 'nonfunctional' and nfr.get('status') == 'AVAILABLE'), None)
    if nfr.get('status') == 'AVAILABLE':
        nfr_tables = [
            table('Non-functional risk indicators', ['Rule', 'Severity', 'Category', 'Detection', 'Domains', 'Needs runtime validation', 'What to investigate'],
                  [[r['rule_id'], r['severity'], r['category'], r['detection_status'], ', '.join(d['name'] for d in r['domains']), 'yes' if r['runtime_validation_required'] else 'no', r['investigate']] for r in nfr['risks']],
                  note='ArchIntel reads each indicator from bytecode (detected) and reasons its consequence (inferred); none is a measurement.'),
            table('Business capabilities and technical domains', ['Domain', 'Kind', 'Basis'], [[c['name'], c['kind'], c['basis']] for c in nfr['capabilities']]),
            table('Components shared across domains', ['Component', 'Kind', 'Domains', 'Users', 'Guidance'], [[c['name'], c['kind'], ', '.join(c['capabilities']), c['dependent_count'], c['guidance']] for c in nfr['cross_cutting']]),
            listing('Not examined for non-functional concerns', nfr['not_examined'] + nfr['limitations'])]
    else:
        nfr_tables = [listing('Non-functional constraints', [nfr.get('reason') or 'Non-functional constraints were not derived for this plan.'])]
    sections = []

    # 1. Summary
    stack = ', '.join(frameworks) if frameworks else None
    stack_clause = (f"uses {F.name(stack)}" if stack else 'its framework versions are not measured')
    sections.append(dict(id='summary', title='Summary', plain=[
        f"{F.name(artifact_name)} has {cs} classes{' in ' + ps + ' packages' if ps else ''}, grouped into {ds} candidate domains ({_names(F, domain_names, 5)})" + (f"; it is compiled for Java {F.num('java', 'Java class-file level', java, 'bytecode inventory')} and {stack_clause}." if java is not None else '; its Java level and framework versions are not measured for this analysis.'),
        ('The largest technical problems are ' + '; '.join(rate_phrase(r) for r in top5[:3]) + '.') if top5 else f'No measured technical-debt rate of {F.name(artifact_name)} is above zero.',
        (f"Recommended approach: {F.name(brief['recommendation']['option'])}; first actions: " + '; '.join(f"({n}) {a}" for n, a in enumerate(actions, 1)) + '.') if brief.get('recommendation') and actions
        else f'No approach or action is recommended for {F.name(artifact_name)} because no finding or plan item was produced.'],
        technical=[table('Application facts', ['Fact', 'Value', 'Source'], [
            ['Artifact', artifact_name, 'artifact record'], ['SHA-256', manifest.get('artifact_sha256') or (artifact.sha256 if artifact else 'not measured'), 'version manifest'],
            ['Classes', classes, 'static summary'], ['Packages', packages if packages is not None else 'not measured', 'static summary'], ['Candidate domains', len(domains), 'version'],
            ['Java class-file level', java if java is not None else 'not measured: no bytecode facts', 'bytecode'], ['Frameworks', stack or 'not measured', 'technology inventory']]),
            table('Top five technical problems', ['Problem', 'Counted', 'Out of', 'Share', 'Highest severity'], [[r['label'], r['numerator'], f"{r['denominator']} {r['unit']}", f"{r['percentage']}%", r['severity'] or 'not rated'] for r in top5]),
            listing('Recommended first actions', actions)]))

    # 2. Application profile
    layer_rows = [[l['label'], l['class_count'], l['package_count'], ', '.join(f'{k} {v}' for k, v in sorted(l['roles'].items()))] for l in hld.get('layers', [])]
    package_rows = sorted(((p, len(c)) for p, c in model.packages.items()), key=lambda r: (-r[1], r[0]))[:15]
    db_rows = defaultdict(lambda: dict(operations=Counter(), callers=set(), calls=0, evidence=[]))
    for ev in db.scalars(select(Evidence).where(Evidence.version_id == version.id, Evidence.kind == 'DATABASE')):
        o = ev.document.get('observation', {})
        for tname in (o.get('tables') or ([o['resource']] if o.get('resource') else [])):
            row = db_rows[tname]
            row['operations'][o.get('operation') or 'not recorded'] += o.get('call_count', 0)
            row['callers'].add(o.get('caller_class') or o.get('caller') or 'not resolved')
            row['calls'] += o.get('call_count', 0)
            row['evidence'].append(ev.id)
    largest = package_rows[0] if package_rows else None
    entry_phrases = [F.num('entry_' + k, k + ' entry points', n, 'insight: entry-point detection') + ' ' + kind_label(k, n) for k, n in sorted(entry_kinds.items())]
    sections.append(dict(id='profile', title='Application profile', plain=[
        (f"The code is spread over {len(model.packages)} packages; {F.name(largest[0])} is the largest with {F.num('largest_package', 'Classes in the largest package', largest[1], 'static analysis: packages')} classes." if largest else 'No package information is available.'),
        (f"{F.num('entry_points', 'Detected entry points', len(entries), 'insight: entry-point detection')} entry points were detected ({', '.join(entry_phrases)})." if entries else 'No entry point was detected.'),
        (f"At runtime {F.num('db_tables', 'Database tables seen at runtime', len(db_rows), 'runtime evidence: DATABASE')} database {_plural(len(db_rows), 'table')} ({_names(F, sorted(db_rows), 4)}) were called." if db_rows
         else ('No database table was seen at runtime in the selected sessions.' if has_runtime else 'Database tables seen at runtime are not measured: no runtime session is attached.'))],
        technical=[table('Layers', ['Layer', 'Classes', 'Packages', 'Roles'], layer_rows), table('Largest packages', ['Package', 'Classes'], package_rows),
                   table('Entry points', ['Kind', 'Handler', 'Route or trigger'], [[e['kind'], f"{_short(e['handler_class'])}.{e['handler_method']}()", ', '.join(f"{v} {p}" for v in (e['http_methods'] or ['']) for p in (e['paths'] or [e['trigger'] or '']))] for e in entries[:25]],
                         note=f'{len(entries) - 25} more entry points are in the appendix.' if len(entries) > 25 else None),
                   table('Database tables seen at runtime', ['Table', 'Operations', 'Callers', 'Calls', 'Evidence ids'], [[t, ', '.join(f'{o} {n}' for o, n in sorted(r['operations'].items())), ', '.join(sorted(r['callers'])[:3]), r['calls'], ', '.join(r['evidence'][:2])] for t, r in sorted(db_rows.items())]) if db_rows
                   else listing('Database tables seen at runtime', ['not measured: no runtime session is attached' if not has_runtime else 'none seen in the selected sessions'])]))

    # 3. Architecture
    matrix = doc.get('domain_dependency_matrix', {})
    cross = sum(r['edge_count'] for r in matrix.get('rows', []))
    layer_edges = hld.get('edges', [])
    against = [e for e in layer_edges if e.get('against_layering')]
    sections.append(dict(id='architecture', title='Architecture', plain=[
        f"The code falls into {F.num('layers', 'Architecture layers', len(hld.get('layers', [])), 'diagram: HLD layers')} layers: " + _names(F, [l['label'].split(' (')[0] + ' ' + str(l['class_count']) for l in hld.get('layers', [])], 6) + ' classes.',
        f"{F.num('layer_edges', 'Layer and external dependencies', len(layer_edges), 'diagram: HLD edges')} dependency groups connect them, and {F.num('against', 'Dependencies against the layering', len(against), 'diagram: HLD edges')} point against the intended layering.",
        f"Between the {ds} candidate domains, {F.num('cross_edges', 'Cross-domain dependency edges', cross, 'plan: domain_dependency_matrix')} dependency edges run across {F.num('domain_pairs', 'Domain pairs with a dependency', len(matrix.get('rows', [])), 'plan: domain_dependency_matrix')} domain pairs."],
        technical=[dict(type='hld', data={k: hld[k] for k in ('layers', 'edges', 'externals', 'entry_points') if k in hld}),
                   dict(type='domain_map', data=matrix),
                   table('Domain dependencies', ['From', 'To', 'Edges', 'Types'], [[r['source_domain'], r['target_domain'], r['edge_count'], ', '.join(f'{k} {v}' for k, v in sorted(r['edge_types'].items()))] for r in matrix.get('rows', [])]),
                   table('Layer dependencies', ['From', 'To', 'Class pairs', 'Runtime calls', 'Against layering'], [[e['source'].split(':')[1], e['target'].split(':')[1], e['class_pairs'], e['runtime_calls'], 'yes' if e.get('against_layering') else 'no'] for e in layer_edges])]))

    # 4. Technical problems
    by_rule = defaultdict(list)
    for f in debt['findings']:
        by_rule[f['rule_id']].append(f)
    problem_rows = []
    for r in measured:
        counted = r['classes'] if r['unit'] == 'classes' else r['subjects']
        shown = counted[:10]
        problem_rows.append([r['label'], f"{r['numerator']} of {r['denominator']} {r['unit']} ({r['percentage']}%)", ', '.join(short_item(c) for c in shown) + (f" and {len(counted) - len(shown)} more (appendix)" if len(counted) > len(shown) else '')])
    not_measured = [r for r in rates.values() if r['status'] == 'NOT_MEASURED']
    any_rate = rates['any-class']
    sections.append(dict(id='problems', title='Technical problems', plain=[
        (f"{F.num('problem_classes', 'Classes with a technical-debt finding', any_rate['numerator'], 'technical debt rates: any-class')} of {cs} classes ({F.num('problem_pct', 'Share of classes with a finding', any_rate['percentage'], 'technical debt rates: any-class', '%')}) have at least one finding.") if any_rate['status'] == 'MEASURED' else 'The share of classes with a finding is not measured.',
        ('The most common problem is ' + rate_phrase(top5[0]) + '.') if top5 else 'No problem rate is above zero.',
        (f"{F.num('not_measured_rates', 'Unmeasured problem rates', len(not_measured), 'technical debt rates: status')} {_plural(len(not_measured), 'rate')} could not be measured: {_names(F, [r['label'] for r in not_measured], 3)}." if not_measured else 'Every rate was measured.')],
        technical=[table('Problems by share of the application', ['Problem', 'Share', 'Top 10 named'], problem_rows, note='The full list of counted items is in section 10 (Appendix).'),
                   table('Highest-severity findings', ['Severity', 'Rule', 'Subject', 'Measured'], [[f['severity'], f['rule_id'], short_item(f['entity_id']), measured_text(f['measured'])] for f in debt['findings'][:10]]),
                   listing('Not measured', [f"{r['label']}: {r['reason']}" for r in not_measured])]))

    # 5. Aging technology
    plan_items = plan.get('items', []) if phases else []
    if phases and plan.get('runtime'):
        for key, label in (('current_java', 'Java level of the code'), ('target_java', 'Java level of the plan')):
            if plan['runtime'].get(key) is not None:
                F.num('java_' + key, label, plan['runtime'][key], 'technology plan: runtime')
    sections.append(dict(id='aging', title='Aging technology', plain=[
        (f"{F.num('aging_items', 'Aging or end-of-life technologies', len(plan_items), 'technology plan: items')} {_plural(len(plan_items), 'technology', 'technologies')} need replacing: {_names(F, [i['technology'] for i in plan_items], 4)}.") if plan_items else
        (f'The lifecycle rules flag no aging or end-of-life technology in {F.name(artifact_name)}.' if life is not None else 'Aging technology is not measured: this analysis has no bytecode facts.'),
        (adopt(plan['runtime']['reason']) if phases and plan.get('runtime') else 'No Java upgrade is planned.'),
        (f"No language change is recommended because the {len(plan_items)} flagged {_plural(len(plan_items), 'item')} are library, framework, namespace or platform versions, not properties of the Java language." if phases and plan.get('language') else 'No language recommendation was produced.')],
        technical=[table('Replacement recommendations', ['Technology', 'Status', 'Classes', 'Replace with', 'Needs Java', 'Phase', 'Confidence'],
                         [[i['technology'], i['status'], len(i['affected_classes']), i['recommended']['name'], i['recommended']['requires_java'], i['phase'], i['confidence']['label']] for i in plan_items]),
                   table('Phases', ['Phase', 'Title', 'Items', 'Classes'], [[p['number'], p['title'], ', '.join(p['items']), p['class_count']] for p in phases]),
                   listing('Evidence ids', [c for i in plan_items for c in i['citations'][:2]])]))

    # 6. Circular dependencies
    groups = [g for g in cyc['groups'] if g['level'] == 'CLASS']
    cycle_rows = []
    for g in groups:
        for cy in g['cycles'][:2]:
            cycle_rows.append([g['size'], ' -> '.join(_short(m) for m in cy['members'] + cy['members'][:1]), '; '.join(f"{_short(e['source'])} -> {_short(e['target'])} ({e['dominant_type']})" for e in cy['edges'])])
    sections.append(dict(id='cycles', title='Circular dependencies', plain=[
        (f"{F.num('cycle_groups', 'Class-level cycle groups', len(groups), 'cycle analysis: groups')} groups of classes depend on each other in a loop, and {F.num('cycle_classes', 'Classes in dependency cycles', rates['cycle-member']['numerator'], 'technical debt rates: cycle-member')} classes belong to one ({rates['cycle-member']['percentage']}%)." if groups and rates['cycle-member']['status'] == 'MEASURED' else 'No class-level dependency cycle was found.'),
        (f"The largest group has {F.num('cycle_largest', 'Classes in the largest cycle group', max(g['size'] for g in groups), 'cycle analysis: groups')} classes: {_names(F, [_short(m) for m in max(groups, key=lambda g: g['size'])['members']], 5)}." if groups else f"All {cs} classes can be changed without first breaking a loop.")],
        technical=[table('Cycle groups', ['Group', 'Classes', 'Internal edges', 'Severity', 'Members'], [[g['id'][-8:], g['size'], g['internal_edge_count'], g['severity'], ', '.join(_short(m) for m in g['members'][:8])] for g in groups]),
                   table('Example loops with their edges', ['Size', 'Loop', 'Edges'], cycle_rows)]))

    # 7. Runtime coverage
    cov = version.document.get('coverage') or {}
    cov_rows = [[label, (f"{cov[k]['observed']} of {cov[k]['total']} ({cov[k]['percentage']}%)" if cov.get(k, {}).get('percentage') is not None else f"not measured: {cov.get(k, {}).get('reason') or 'no data'}")] for k, label in (('classes', 'Classes'), ('entry_points', 'Entry points'), ('methods', 'Methods'), ('dependencies', 'Dependencies'), ('domains', 'Domains'))] if has_runtime else []
    unobserved_domains = [d for d in cov.get('domain_observations', []) if d['observed'] < d['total']]
    entry_rate = rates['entry-points-unobserved']
    sections.append(dict(id='runtime', title='Runtime coverage', plain=[
        (f"{F.num('sessions', 'Runtime sessions included', len(sessions), 'version manifest: runtime_session_ids')} runtime {_plural(len(sessions), 'session')} observed {F.num('obs_classes', 'Observed classes', cov['classes']['observed'], 'version coverage: classes')} of {F.num('obs_total', 'Classes', cov['classes']['total'], 'version coverage: classes')} classes ({F.num('obs_pct', 'Observed class percentage', cov['classes']['percentage'], 'version coverage: classes', '%')})." if has_runtime and cov.get('classes', {}).get('percentage') is not None
         else 'No runtime session is attached, so nothing was observed; every runtime figure is not measured.'),
        (f"{F.num('unobs_entries', 'Entry points never observed', entry_rate['numerator'], 'technical debt rates: entry-points-unobserved')} of {F.num('entries_all', 'Detected entry points', entry_rate['denominator'], 'technical debt rates: entry-points-unobserved')} entry points were never observed ({entry_rate['percentage']}%)." if entry_rate['status'] == 'MEASURED' else 'Entry-point coverage is not measured.'),
        (f"{F.num('unobs_domains', 'Domains not fully observed', len(unobserved_domains), 'version coverage: domain_observations')} of {ds} domains are not fully observed ({_names(F, [d['name'] for d in unobserved_domains], 4)}). Unobserved never means unused." if has_runtime else 'Unobserved never means unused.')],
        technical=[table('Sessions', ['Session', 'Environment', 'Status', 'Traces', 'Spans', 'Id'], [[s.name, s.environment, s.status, s.trace_count, s.span_count, s.id] for s in sessions]) if has_runtime else listing('Sessions', ['not measured: no runtime session is attached']),
                   table('Coverage', ['Measure', 'Observed'], cov_rows) if cov_rows else listing('Coverage', ['not measured: no runtime session is attached']),
                   table('Domains not fully observed', ['Domain', 'Observed', 'Total', 'Unobserved classes (first 8)'], [[d['name'], d['observed'], d['total'], ', '.join(_short(c) for c in d['unobserved_classes'][:8])] for d in unobserved_domains]),
                   table('Entry points never observed', ['Handler'], [[s] for s in rates['entry-points-unobserved']['subjects'][:25]]) if entry_rate['status'] == 'MEASURED' and entry_rate['numerator'] else listing('Entry points never observed', ['none, or not measured'])]))

    # 8. Modernization plan
    waves = doc['waves']
    names = {a['domain_id']: a['domain_name'] for a in doc['assessments']}
    sections.append(dict(id='plan', title='Modernization plan', plain=[
        f"The plan has {F.num('waves', 'Dependency waves', len(waves), 'plan: waves')} {_plural(len(waves), 'wave')} over {ds} domains, and the first is {_names(F, [names[d] for d in waves[0]['domains']], 3)}." if waves else 'The plan has no wave.',
        (f"Recommended approach: {F.name(brief['recommendation']['option'])} (" + (lambda t: t[0].lower() + t[1:])(adopt(first_sentence(brief['recommendation']['rationale']))) + ")." if brief.get('recommendation') else 'No approach is recommended.'),
        (f"The technology work runs in {F.num('tech_phases', 'Technology phases', len(phases), 'technology plan: phases')} {_plural(len(phases), 'phase')}: " + '; '.join(f"({p['number']}) {p['title']}" for p in phases) + '.') if phases else 'No technology phase is planned.',
        *([adopt(first_sentence(nfr_section['paragraphs'][0]))] if nfr_section else [])],
        technical=[table('Domain waves', ['Wave', 'Domains', 'Depends on', 'Why this order'], [[w['number'], ', '.join(names[d] for d in w['domains']), ', '.join(names[d] for d in w['dependencies']) or 'nothing', w['reason']] for w in waves]),
                   table('Readiness, confidence and blockers', ['Domain', 'Readiness', 'Confidence', 'Adjusted', 'Status', 'Blockers'], [[a['domain_name'], a['structural_score'], a['confidence_score'], a['confidence_adjusted_score'], a['readiness_label'], ', '.join(a['blockers'])] for a in doc['assessments']]),
                   table('Decisions', ['Domain', 'Decision', 'Action'], [[names[d['domain_id']], d['kind'], d['action']] for d in doc['decisions']]),
                   listing('Evidence ids', [f"{f['rule_id']}: {', '.join(f['evidence_ids'][:2])}" for f in doc['findings'][:10]])]))

    # 9. Risks and unknowns
    sections.append(dict(id='risks', title='Risks and unknowns', plain=[
        (adopt(brief['risks'][0]['text']) if brief.get('risks') else f'No measured risk rate of {F.name(artifact_name)} is above zero.'),
        (f"{F.num('unknown_groups', 'Inputs that are not measured', len(brief.get('unknowns', [])), 'decision brief: unknowns')} inputs are not measured, for example: {adopt(brief['unknowns'][0])}" if brief.get('unknowns') else f'Every input of the {ds} domain scores was measured.'),
        (adopt(brief['questions'][0]) if brief.get('questions') else 'No open question was raised.')],
        technical=[listing('Risks', [r['text'] for r in brief.get('risks', [])])] + nfr_tables + [listing('Blockers', [f"{b['code']}: {b['meaning']} Affects {', '.join(b['domains'])}. Resolve: {b['resolve']}" for b in brief.get('blockers', [])]),
                   listing('What is not known', brief.get('unknowns', []) + brief.get('questions', []))]))

    # 10. Appendix
    sections.append(dict(id='appendix', title='Appendix', plain=[
        f"This appendix lists every counted item, the formulas behind each score and the scan metadata of {F.name(artifact_name)}.",
        f"It contains {F.num('appendix_findings', 'Technical-debt findings', len(debt['findings']), 'technical debt: findings')} findings and {F.num('appendix_facts', 'Numbers in the fact table', 0, 'report')} numbers with their sources."],
        technical=[table('All technical-debt findings', ['Severity', 'Rule', 'Subject', 'Measured', 'Threshold'], [[f['severity'], f['rule_id'], f['entity_id'], measured_text(f['measured']), measured_text(f['threshold']) if isinstance(f['threshold'], dict) else str(f['threshold'])] for f in debt['findings']]),
                   table('Items counted by each problem rate', ['Problem', 'Items'], [[r['label'], ', '.join(r['subjects'])] for r in measured]),
                   table('Entry points', ['Kind', 'Handler', 'Route or trigger'], [[e['kind'], f"{e['handler_class']}.{e['handler_method']}()", ', '.join(f"{v} {p}" for v in (e['http_methods'] or ['']) for p in (e['paths'] or [e['trigger'] or '']))] for e in entries]),
                   table('Formulas', ['Term', 'Formula'], [[g['term'], g['formula']] for g in glossary_entries() if g['id'] in ('readiness', 'confidence', 'runtime-readiness', 'debt-index') or g['id'].startswith('rate:')]),
                   table('Scan metadata', ['Item', 'Value'], [['Application', application.name], ['Analysis', run.id], ['Architecture version', version.id], ['Version fingerprint', version.fingerprint], ['Proposal', assessment.id], ['Proposal fingerprint', doc.get('fingerprint', 'not recorded')],
                         ['Planning rule version', doc.get('rule_version')], ['Lifecycle rules version', (plan or {}).get('rules_version') or 'not recorded'], ['Debt rules version', debt['rules_version']],
                         ['Knowledge-graph projection', projection.get('state', 'UNAVAILABLE')], ['Runtime sessions', ', '.join(manifest.get('runtime_session_ids', [])) or 'none']])]))
    # the appendix fact count needs the final table size
    appendix = sections[-1]
    appendix['plain'][1] = f"It contains {F.num('appendix_findings', 'Technical-debt findings', len(debt['findings']), 'technical debt: findings')} findings and {F.num('fact_count', 'Numbers in the fact table', len(F.rows), 'report: fact table')} numbers with their sources."
    model_out = dict(meta=dict(application=application.name, artifact=artifact_name, generated_at=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), analysis_id=run.id, version_id=version.id,
                               proposal_id=assessment.id, fingerprint=version.fingerprint, notice=f'Confidential working report. Candidate boundaries and recommendations for {artifact_name} need engineering review.'),
                     sections=[dict(s, number=n) for n, s in enumerate(sections, 1)], facts=F.table(), names=sorted(F.names))
    model_out['numbers_check'] = dict(unregistered=unregistered_plain_numbers(model_out))
    return model_out


def unregistered_plain_numbers(report: dict) -> list[str]:
    allowed = {r.get('text') or _format(r['value']) for r in report['facts']}
    names = sorted(report['names'], key=len, reverse=True)
    problems = []
    for section in report['sections']:
        for text in section['plain']:
            for name in names:
                text = text.replace(name, ' ')
            problems += [n for n in NUMBER.findall(text) if n not in allowed]
    return sorted(set(problems))
