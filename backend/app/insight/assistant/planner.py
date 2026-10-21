"""Deterministic question answering from the same tools the model would use (the no-model mode).

Questions are routed by intent keywords and the entities found in the text. Answers are composed from
tool results only; every sentence carries the evidence ids it was built from. If nothing in the analysis
supports an answer the result says so instead of guessing.
"""
from __future__ import annotations

import re

from app.insight.roles import short
from .tools import Tools

STOP = {'What', 'Which', 'Who', 'How', 'Does', 'Do', 'Is', 'Are', 'Show', 'List', 'Find', 'Tell', 'The', 'This', 'That', 'Explain', 'Why', 'Where', 'Can', 'Give', 'Please', 'POST', 'GET', 'PUT', 'DELETE', 'PATCH', 'HTTP', 'Java', 'Log4j', 'Spring', 'Boot'}
MUTATING = re.compile(r'\b(refactor|rewrite|change|modify|delete|remove|fix|apply|patch|implement|generate|rename|move|migrate|upgrade|replace|edit|write)\b.*', re.I)
ROLE_WORDS = {'controller': r'\bcontrollers?\b', 'repository': r'\brepositor(y|ies)\b', 'service': r'\bservices?\b', 'entity': r'\bentit(y|ies)\b', 'servlet': r'\bservlets?\b',
    'filter': r'\bfilters?\b', 'listener': r'\blisteners?\b', 'validator': r'\bvalidators?\b'}
RESP = re.compile(r'\b(security|secure|authenticat\w*|authoriz\w*|authoris\w*|logging|logs?|observab\w*|metrics|tracing|monitor\w*|cach(?:e|es|ing)|transactions?|retr(?:y|ies)|resilien\w*|reliab\w*|timeouts?|non[- ]functional|cross[- ]cutting|shared (?:across|by|between|component|infrastructure|librar\w*)|responsib\w*|mixed|business capabilit\w*|concerns?|scalab\w*|privacy|audit\w*|testab\w*|maintainab\w*|interoperab\w*|availab\w*)\b', re.I)
CROSS = re.compile(r'\b(cross[- ]cutting|shared)\b', re.I)
RISKY = re.compile(r'\b(risks?|risky)\b', re.I)
ROUTE = re.compile(r'\b(GET|POST|PUT|DELETE|PATCH)\s+(/[\w/{}.\-]*)|(/[\w/{}.\-]+)', re.I)


def entities(tools: Tools, question: str) -> list[dict]:
    found, seen = [], set()
    for token in re.findall(r"[A-Za-z_][\w$.]*", question):
        token = token.rstrip('.')
        if token in STOP or token.isupper() or not (any(c.isupper() for c in token[1:]) or '.' in token or (token[:1].isupper() and len(token) > 3)):
            continue
        resolved = tools.resolve(token)
        key = (resolved.get('kind'), resolved.get('id') or token)
        if resolved['kind'] in ('class', 'package') and key not in seen:
            seen.add(key)
            found.append(dict(token=token, **resolved))
        elif resolved['kind'] == 'unknown' and key not in seen and (any(c.isupper() for c in token[1:]) and token[0].isupper()):
            seen.add(key)
            found.append(dict(token=token, kind='unknown', id=token))
    return found


def _s(text, cites, **extra):
    return dict(text=text, cites=list(dict.fromkeys(cites)), **extra)


def _plural(n, word):
    if n == 1:
        return f'{n} {word}'
    return f'{n} {word}es' if word.endswith(('s', 'ch', 'x')) else f'{n} {word}s'


def _sentence_class(r):
    d = r['data']
    parts = [f"{short(d['name'])} is a {d['role'].lower().replace('_', ' ')} in package {d['package']} (evidence: {d['role_evidence']}); it has {_plural(d['methods'], 'method')}, depends on {_plural(d['dependencies'], 'class')} and {_plural(d['dependents'], 'class')} depend on it."]
    out = [_s(parts[0], r['evidence'][:1])]
    if d['entry_points']:
        out.append(_s(f"It declares {_plural(len(d['entry_points']), 'entry point')}: {'; '.join(d['entry_points'][:6])}.", [e for e in r['evidence'] if e.startswith('entry:')]))
    if d['debt']:
        out.append(_s(f"Technical debt: {'; '.join(x['severity'].lower() + ' — ' + x['text'] for x in d['debt'][:3])}", [e for e in r['evidence'] if e.startswith('finding:')]))
    if d['cycles']:
        out.append(_s(f"It belongs to {_plural(len(d['cycles']), 'cyclic group')} (sizes {', '.join(map(str, d['cycles']))}).", r['evidence'][:1]))
    if d['aging']:
        out.append(_s(f"It uses {', '.join(d['aging'])}.", r['evidence'][:1]))
    return out


def answer(tools: Tools, question: str, last_entity: str | None = None) -> dict:
    q = question.strip()
    low = q.lower()
    calls: list[dict] = []

    def use(tool, **args):
        result = tools.call(tool, args)
        calls.append(dict(tool=tool, args=args, ok=result['ok'], evidence=result.get('evidence', [])))
        return result

    if MUTATING.search(q) and re.search(r'\b(please|can you|could you|go ahead|now)\b|^(refactor|rewrite|change|modify|delete|remove|fix|apply|patch|implement|generate|rename|move|migrate|upgrade|replace|edit|write)\b', low):
        return dict(status='REFUSED', calls=calls, sentences=[_s('I can only read the analysis; I cannot change code. Proposed changes must be created as a Source task, which requires explicit human approval before anything is modified.', [], requires_citation=False, check_identifiers=False)],
            entities=[])
    found = entities(tools, q)
    if not found and last_entity and re.search(r'\b(it|its|this|that|them|those|these|there)\b', low):
        found = [dict(token=last_entity, **tools.resolve(last_entity))]
    unknown = [e for e in found if e['kind'] == 'unknown']
    known = [e for e in found if e['kind'] in ('class', 'package')]
    subject = known[0]['id'] if known else ''
    sentences: list[dict] = []

    def cannot(reason):
        return dict(status='CANNOT_DETERMINE', calls=calls, sentences=[_s(reason, [], requires_citation=False, check_identifiers=False)], entities=[e['id'] for e in known])

    if unknown and not known:
        r = use('search_classes', query=unknown[0]['token'], limit=5)
        if r['data']['total']:
            names = ', '.join(short(i['id']) for i in r['data']['items'])
            return dict(status='ANSWERED', calls=calls, entities=[], sentences=[_s(f"I found no class named exactly {unknown[0]['token']}, but these names contain it: {names}.", r['evidence'])])
        return cannot(f"I cannot determine that: {unknown[0]['token']} is not a class or package in this analysis.")

    route = ROUTE.search(q)
    if re.search(r'\b(circular|cycle|cycles|cyclic)\b', low):
        r = use('get_cycles', name=subject)
        total = r['data']['total']
        if not total:
            sentences.append(_s('No circular dependencies were found' + (f' involving {short(subject)}' if subject else '') + ': the class and package graphs contain no strongly connected group.', r['evidence']))
        else:
            sentences.append(_s(f"There {'is' if total == 1 else 'are'} {_plural(total, 'cyclic group')}" + (f' involving {short(subject)}' if subject else '') + '.', r['evidence'][:1]))
            for g in r['data']['groups'][:4]:
                sentences.append(_s(f"{g['level'].title()} group of {g['size']}: {', '.join(short(m) for m in g['members'][:6])}. {g['plain']}" + (f" Suggested first cut (needs human review): {short(g['cut_first'].split(' -> ')[0])} → {short(g['cut_first'].split(' -> ')[1])}." if g['cut_first'] else ''), ['cycle:' + g['id']]))
    elif re.search(r'\b(aging|ageing|outdated|end[- ]of[- ]life|eol|lifecycle|deprecated|log4j|javax|jakarta|java version|java \d+|jaxb|struts|legacy)\b', low):
        r = use('get_aging_findings', name=subject)
        wanted = [w for w in ('log4j', 'javax', 'jakarta', 'struts', 'jaxb', 'spring') if w in low]
        items = [i for i in r['data']['items'] if not wanted or any(w in (i['technology'] + i['id']).lower() for w in wanted)]
        if not items:
            sentences.append(_s('No matching end-of-life or aging technology was detected' + (f' for {wanted[0]}' if wanted else '') + f" (rules {r['data']['rules_version']}).", r['evidence']))
        for i in items[:6]:
            where = f" Used by {', '.join(short(c) for c in i['classes'][:5])}." if i['classes'] else ''
            sentences.append(_s(f"{i['technology']}{' ' + str(i['version']) if i['version'] else ''} is {i['status']}; recommended alternative: {i['alternative']}.{where}", ['aging:' + i['id']]))
        if r['data']['stale']:
            sentences.append(_s('The lifecycle rules file (lifecycle-rules.yaml) is stale, so these statuses may be out of date.', r['evidence'][:1]))
    elif RESP.search(low) and not route:
        from .tools import CONCERN_WORDS
        pretty = lambda text: text.lower().replace('_', ' ')
        concern = next((w for w in re.findall(r'[a-z]+', low) if w in CONCERN_WORDS), '')
        r = use('get_responsibilities', name=subject, concern=concern)
        if not r['ok']:
            return cannot('I cannot determine that: ' + str(r.get('detail') or 'the responsibility analysis is not available for this analysis') + '.')
        d = r['data']
        where = f' in {short(subject)}' if subject else ''
        if CROSS.search(low) and d['shared']:
            for c in d['shared']:
                sentences.append(_s(f"{c['name']} ({pretty(c['kind'])}) is used across {', '.join(c['domains'])}. {c['guidance']}", ['class:' + c['component']] if c['is_class'] else ['summary:analysis']))
        elif RISKY.search(low) and d['risks']:
            sentences.append(_s(f"{_plural(len(d['risks']), 'non-functional risk indicator')}{where}" + (f" for {pretty(d['concern'])}" if d['concern'] else '') + '; each is read from bytecode and its consequence is inferred.', r['evidence'][:1]))
            for k in d['risks']:
                sentences.append(_s(f"{k['severity'].title()}, {k['detection'].lower()}: {k['title']}. {k['description']}. Investigate: {k['investigate']}", ['risk:' + k['id']]))
        elif d['concern']:
            if not d['items']:
                sentences.append(_s(f"No class{where} shows {d['concern_word']} ({pretty(d['concern'])}) in the analyzed bytecode ({d['analyzed']} classes checked); that does not prove the control is absent.", r['evidence'][:1] or ['summary:analysis']))
            else:
                sentences.append(_s(f"{_plural(d['total'], 'class')}{where} {'shows' if d['total'] == 1 else 'show'} {d['concern_word']} ({pretty(d['concern'])}).", r['evidence'][:1]))
                for i in d['items'][:6]:
                    for label in i['non_functional']:
                        sentences.append(_s(f"{short(i['id'])} ({pretty(i['primary'])}): {label['description']}, {label['status'].lower()}, {label['confidence'].lower()} confidence.", label['evidence'] + ['class:' + i['id']]))
        elif subject and len(d['items']) == 1:
            i = d['items'][0]
            functional = ', '.join(f"{pretty(l['category'])} ({l['status'].lower()})" for l in i['functional']) or 'none detected'
            nonfunctional = ', '.join(f"{pretty(l['category'])} ({l['status'].lower()})" for l in i['non_functional']) or 'none detected'
            sentences.append(_s(f"{short(i['id'])} is classified {pretty(i['primary'])}. Functional responsibilities: {functional}. Non-functional concerns: {nonfunctional}.", ['class:' + i['id']] + [e for l in i['functional'] + i['non_functional'] for e in l['evidence']][:3]))
            for note in i['uncertainties'][:2]:
                sentences.append(_s(note, ['class:' + i['id']]))
        else:
            counts = ', '.join(f"{n} {pretty(k)}" for k, n in d['primary_counts'].items())
            sentences.append(_s(f"Of {_plural(d['analyzed'], 'class')}{where}: {counts}. Statuses are DETECTED when a bytecode fact establishes them and INFERRED when they are a reasoned reading.", r['evidence'][:1] or ['summary:analysis']))
            for k in d['risks'][:3]:
                sentences.append(_s(f"{k['severity'].title()} indicator: {k['title']}.", ['risk:' + k['id']]))
        if d['limits'] and (RISKY.search(low) or d['concern']):
            sentences.append(_s(d['limits'][0], ['summary:analysis']))
    elif route or re.search(r'\b(endpoint|endpoints|route|routes|entry point|entry points|url|urls|listener|scheduled|handles?|mapping)\b', low):
        text = ''
        if route:
            text = (route.group(1) + ' ' + route.group(2)) if route.group(1) else route.group(3)
        if not text and not subject:
            text = ' '.join(w for w in re.findall(r'[A-Za-z]+', q))
        r = use('get_entry_points', name=subject, text=text)
        if not r['data']['items'] and route and route.group(1):
            r = use('get_entry_points', name=subject, text=route.group(2))
        if not r['data']['items']:
            return cannot('I cannot determine that: no matching entry point was found' + (f' for {text}' if text else '') + '.')
        sentences.append(_s(f"{_plural(r['data']['total'], 'entry point')} match" + ('' if r['data']['total'] != 1 else 'es') + (f' in {short(subject)}' if subject else '') + '.', r['evidence'][:1]))
        for i in r['data']['items'][:12]:
            sentences.append(_s(f"{i['description']} is handled by {i['handler']}.", ['entry:' + i['id']]))
    elif re.search(r'\b(coverage|observed|unobserved|runtime|session|exercised)\b', low):
        r = use('get_runtime_coverage', name=subject)
        d = r['data']
        if not d['available']:
            return cannot('I cannot determine runtime coverage: ' + d['reason'])
        sentences.append(_s(f"{d['observed']} of {d['total']} classes{' in ' + short(subject) if subject else ''} were observed in the selected runtime sessions. {d['note']}", r['evidence'][:1]))
        if d['unobserved']:
            sentences.append(_s('Not observed: ' + ', '.join(short(c) for c in d['unobserved'][:10]) + '.', ['class:' + c for c in d['unobserved'][:10]]))
    elif re.search(r'\b(source|code of|show .*code|implementation)\b', low) and subject:
        r = use('get_class_source', name=subject)
        d = r['data']
        if not d['available']:
            return cannot(f"I cannot show source for {short(subject)}: {d.get('reason') or 'not available'}")
        label = 'original source' if d['kind'] == 'SOURCE' else 'a bytecode outline (no .java source was uploaded in the JAR)'
        return dict(status='ANSWERED', calls=calls, entities=[subject], sentences=[_s(f"Here is {label} of {short(subject)}.", r['evidence'], code=d['text'], code_kind=d['kind'])])
    elif re.search(r'\b(metric|metrics|instability|abstractness|distance|fan[- ]?in|fan[- ]?out|coupling|complexity|biggest|largest|most (dependents|connected|methods))\b', low) and not re.search(r'\b(debt|problem|smell)\b', low):
        keys = {'instability': 'package.I', 'abstractness': 'package.A', 'distance': 'package.D', 'fan-in': 'class.fan_in', 'fan in': 'class.fan_in', 'fan-out': 'class.fan_out', 'fan out': 'class.fan_out',
            'complexity': 'class.max_method_complexity', 'largest': 'class.bytecode_size', 'biggest': 'class.bytecode_size', 'most dependents': 'class.fan_in', 'most methods': 'class.method_count', 'most connected': 'class.fan_in'}
        key = next((v for k, v in keys.items() if k in low), '')
        if subject and not (key and not re.search(r'\bof\b|\bfor\b', low)):
            r = use('get_metrics', name=subject)
            if not r['ok']:
                return cannot('I cannot determine that metric.')
            values = r['data']['values']
            wanted = [key] if key and key in values else [k for k in values if k.split('.')[1] in ('fan_in', 'fan_out', 'method_count', 'I', 'A', 'D', 'Ca', 'Ce', 'class_count', 'bytecode_size')]
            for k in wanted[:8]:
                sentences.append(_s(f"{short(subject)} {k.split('.')[1]} = {values[k]} ({r['data']['formulas'][k]}).", [f'metric:{subject}:{k}']))
        else:
            r = use('get_metrics', top=key or 'class.fan_in', limit=5)
            if not r['ok']:
                return cannot('I cannot determine that metric.')
            d = r['data']
            sentences.append(_s(f"Highest {d['label']} ({d['formula']}): " + ', '.join(f"{short(x['id']) if x['id'] in tools.model.classes else x['id']} ({x['value']})" for x in d['ranking']) + '.', r['evidence']))
    elif re.search(r'\b(depends? on|depend upon|dependenc\w*|dependents?|uses?|used by|using|relies on|rely on|relying on|references?|callers?|calls?|needs?)\b', low) and subject:
        verb = re.search(r'\b(depends? on|depend upon|uses?|using|relies on|rely on|relying on|references?|calls?|needs?)\b', low)
        token = known[0]['token'].lower()
        # "who uses X" / "what depends on X": the subject follows the verb; "what does X depend on": it precedes it.
        dependents = bool(re.search(r'\b(dependents?|used by|callers?)\b', low)) or bool(verb and low.find(token) > verb.start() and not re.search(r'\bwhat does\b|\bdoes\b.*\b(depend|use|rely|call)', low.split(token)[0] + '|' + low) or (verb and re.match(r'(who|what|which|does anything|do any|is there anything)', low) and low.find(token) > verb.start()))
        r = use('get_dependents' if dependents else 'get_dependencies', name=subject, limit=15)
        d = r['data']
        if not d['items']:
            sentences.append(_s(f"No application class depends on {short(subject)}." if dependents else f"{short(subject)} depends on no other application class.", r['evidence'][:1]))
        else:
            noun = 'class' if known[0]['kind'] == 'class' else 'package'
            head = f"{_plural(d['total'], noun)} {'depend on' if dependents else ('is a dependency' if d['total'] == 1 else 'are dependencies') + ' of'} {short(subject)}:"
            sentences.append(_s(head + ' ' + ', '.join(short(i['id']) if i['id'] in tools.model.classes else i['id'] for i in d['items']) + '.', r['evidence'][:1]))
            for i in d['items'][:6]:
                a, b = (i['id'], subject) if dependents else (subject, i['id'])
                sentences.append(_s(f"{short(a)} → {short(b)}: {i['references']} reference{'s' if i['references'] != 1 else ''} ({', '.join(t.lower().replace('_', ' ') for t in i['edge_types'])}).", [f'edge:{a}->{b}']))
    elif re.search(r'\b(debt|problem|problems|smell|smells|god class|violation|violations|large method|issue|issues|wrong|bad|risky|risk)\b', low) or (re.search(r'\bentit(y|ies)\b', low) and 'controller' in low):
        rule = 'DEBT-ENTITY-IN-CONTROLLER' if re.search(r'entit', low) and 'controller' in low else 'DEBT-LAYER-VIOLATION' if 'layer' in low else 'DEBT-GOD-CLASS' if 'god' in low else 'DEBT-STATIC-STATE' if 'static' in low else 'DEBT-LARGE-METHOD' if 'large method' in low else ''
        r = use('get_debt_findings', name=subject, rule=rule, limit=10)
        d = r['data']
        if not d['total']:
            sentences.append(_s('No technical-debt finding matches' + (f' for {short(subject)}' if subject else '') + (f' (rule {rule})' if rule else '') + '.', r['evidence']))
        else:
            sentences.append(_s(f"{_plural(d['total'], 'finding')}" + (f' for {short(subject)}' if subject else '') + ': ' + ', '.join(f'{v} × {k}' for k, v in sorted(d['by_rule'].items())) + '.', r['evidence'][:1]))
            for f in d['items'][:8]:
                sentences.append(_s(f"{f['severity'].title()} — {f['plain']} Suggested: {f['action']}", ['finding:' + f['id']]))
    elif re.search(r'\b(find|search|list|named|name contains|containing|which classes|all classes)\b', low) or re.search(r'\bclasses (with|that)\b', low):
        m = re.search(r"(?:named|containing|contain|with|has|have)\s+['\"]?([A-Za-z0-9_$]+)['\"]?(?:\s+in (?:the )?name)?", q)
        role = next((name for name, pattern in ROLE_WORDS.items() if re.search(pattern, low)), '')
        query = m.group(1) if m and m.group(1).lower() not in ('name', 'the', role) else (role.capitalize() if role and not m else '')
        r = use('search_classes', query='' if role and not (m and m.group(1).lower() not in (role,)) else query, role=role, limit=25)
        d = r['data']
        if not d['items']:
            return cannot('I cannot determine that: no class matches.')
        sentences.append(_s(f"{_plural(d['total'], 'class')} match: " + ', '.join(short(i['id']) for i in d['items']) + '.', r['evidence']))
    elif subject:
        r = use('get_class' if known[0]['kind'] == 'class' else 'get_package', name=subject)
        if not r['ok']:
            return cannot('I cannot determine that.')
        if known[0]['kind'] == 'class':
            sentences += _sentence_class(r)
        else:
            d = r['data']
            sentences.append(_s(f"Package {d['name']} has {_plural(d['classes'], 'class')} with roles {', '.join(f'{v} {k.lower()}' for k, v in d['roles'].items())}; it depends on {_plural(len(d['depends_on']), 'package')} and {_plural(len(d['depended_on_by']), 'package')} depend on it. {d['cycles']} cyclic group(s), {d['entry_points']} entry point(s), {d['debt']} debt finding(s).", r['evidence']))
    elif re.search(r'\b(how many|how big|how large|count|number of|overview|summary|summari[sz]e|about|size|codebase|layers?|architecture|structure|what is this|packages)\b', low):
        r = use('get_package', name='')
        d = r['data']
        sentences.append(_s(f"The application has {_plural(d['classes'], 'top-level class')} in {_plural(d['packages'], 'package')} ({_plural(d['nested_classes'], 'nested class')} folded into owners).", r['evidence']))
        sentences.append(_s('Roles: ' + ', '.join(f'{v} {k.lower().replace("_", " ")}' for k, v in sorted(d['roles'].items(), key=lambda kv: -kv[1])) + '.', r['evidence']))
        sentences.append(_s(f"It declares {_plural(d['entry_points'], 'entry point')}, has {_plural(d['cycle_groups'], 'cyclic group')} and {_plural(d['debt_findings'], 'technical-debt finding')}. Packages: {', '.join(d['package_names'])}.", r['evidence']))
    else:
        return cannot('I cannot determine that from this analysis. I can answer questions about classes, packages, dependencies, cycles, technical debt, entry points, aging technology, metrics, source and (when a session is selected) runtime coverage.')
    if unknown:
        sentences.append(_s(f"I could not find {unknown[0]['token']} in this analysis, so nothing is said about it.", [], requires_citation=False, check_identifiers=False))
    return dict(status='ANSWERED', calls=calls, sentences=sentences, entities=[e['id'] for e in known])
