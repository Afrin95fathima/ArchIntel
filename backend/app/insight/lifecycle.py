"""WP1: aging / end-of-life technology detection from a versioned, dated rules file."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from functools import lru_cache
from pathlib import Path
import re

import yaml

from .roles import method_label, short

RULES_PATH = Path(__file__).resolve().parent / 'rules' / 'lifecycle-rules.yaml'
STATUS_ORDER = {'end-of-life': 0, 'aging': 1, 'current': 2}
EFFORT_WEIGHT = {'low': 1, 'medium': 2, 'high': 3}


@lru_cache(maxsize=4)
def load_rules(path: str = str(RULES_PATH)) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not isinstance(data.get('rules'), list):
        raise ValueError('Unsupported lifecycle rules file.')
    ids = [r['id'] for r in data['rules']]
    if len(ids) != len(set(ids)):
        raise ValueError('Lifecycle rule ids must be unique.')
    for rule in data['rules']:
        if rule.get('status', 'aging') not in STATUS_ORDER or any(v['status'] not in STATUS_ORDER for v in rule.get('versions', [])):
            raise ValueError(f"Rule {rule['id']} has an unknown status.")
    return data


def freshness(rules: dict, today: date | None = None, max_age_days: int | None = None) -> dict:
    reviewed = rules['reviewed'] if isinstance(rules['reviewed'], date) else date.fromisoformat(str(rules['reviewed']))
    today = today or date.today()
    limit = max_age_days or rules.get('max_age_days', 180)
    age = (today - reviewed).days
    stale = age > limit
    return dict(rules_version=rules['rules_version'], reviewed=reviewed.isoformat(), age_days=age, max_age_days=limit, stale=stale,
        warning=(f'Lifecycle rules were last reviewed {age} days ago (limit {limit}). End-of-life dates may have changed; '
                 'update app/insight/rules/lifecycle-rules.yaml from the linked sources.') if stale else None)


def _version_tuple(value: str) -> tuple[int, ...] | None:
    match = re.match(r'^\s*v?(\d+(?:\.\d+)*)', str(value))
    return tuple(int(p) for p in match.group(1).split('.')) if match else None


def in_range(version: str, expression: str) -> bool:
    found = _version_tuple(version)
    if found is None:
        return False
    for clause in expression.split(','):
        match = re.fullmatch(r'\s*(<=|>=|==|<|>)\s*([\d.]+)\s*', clause)
        if not match:
            raise ValueError(f'Bad version range {expression!r}')
        op, bound = match.group(1), _version_tuple(match.group(2))
        width = max(len(found), len(bound))
        a, b = found + (0,) * (width - len(found)), bound + (0,) * (width - len(bound))
        if op == '==':
            # "==8" matches 8 and any 8.x.y: compare only as many components as the bound names.
            padded = found + (0,) * max(0, len(bound) - len(found))
            a, b = padded[:len(bound)], bound
        if not {'<': a < b, '<=': a <= b, '>': a > b, '>=': a >= b, '==': a == b}[op]:
            return False
    return True


def _versioned_status(rule: dict, version: str | None) -> dict:
    if version:
        for row in rule.get('versions', []):
            if in_range(version, row['range']):
                return dict(status=row['status'], note=row.get('note'), matched_range=row['range'])
    return dict(status=rule.get('status', 'aging'), note=None if not rule.get('versions') else
        'Version not determinable from the artifact; status shown is the rule default for any version.', matched_range=None)


def _dependency_rows(inventory: dict) -> list[dict]:
    rows = [dict(group_id=d.get('group_id'), artifact_id=d.get('artifact_id'), version=d.get('version'),
        version_status=d.get('version_status'), source='MAVEN_METADATA') for d in inventory.get('dependencies', [])]
    rows += [dict(group_id=None, artifact_id=d['artifact_id'], version=d.get('version'), version_status='FROM_FILENAME',
        source='BUNDLED_JAR_FILENAME') for d in inventory.get('bundled_libraries', [])]
    for framework in inventory.get('frameworks', []):
        if framework.get('name') == 'Spring Boot':
            for version in framework.get('versions', []):
                rows.append(dict(group_id='org.springframework.boot', artifact_id='spring-boot', version=version,
                    version_status='MANIFEST_OR_METADATA', source='SPRING_BOOT_MANIFEST'))
    return rows


def _matches_artifact(row: dict, patterns: list[str]) -> bool:
    for pattern in patterns:
        if ':' in pattern:
            group, artifact = pattern.split(':', 1)
            if row.get('group_id') == group and row.get('artifact_id') == artifact:
                return True
        elif row.get('artifact_id') == pattern:
            return True
    return False


def package_usage(model, prefixes: list[str], limit_classes: int = 200, limit_sites: int = 25, excluded: list[str] | None = None) -> dict:
    """Which application classes use APIs under the prefixes (minus excluded sub-packages), with call sites (class, method, line)."""
    def hit(name: str) -> bool:
        return any(name == p.rstrip('.') or name.startswith(p) for p in prefixes) and not any(name == p.rstrip('.') or name.startswith(p) for p in excluded or [])
    classes: dict[str, dict] = defaultdict(lambda: dict(types=set(), sites=[], edge_types=set()))
    for edge in model.external_edges:
        if hit(edge['target']):
            owner = model.owners.get(edge['source'], edge['source'])
            classes[owner]['types'].add(edge['target'])
            classes[owner]['edge_types'].add(edge['dependency_type'])
    for fqn, info in model.facts.items():
        owner = model.owners.get(fqn, fqn)
        for annotation in info.get('annotations', []):
            if hit(annotation['type']):
                classes[owner]['types'].add(annotation['type'])
                classes[owner]['sites'].append(dict(where=short(fqn), text=f"{short(fqn)} is annotated @{short(annotation['type'])}", line=None))
        for method in info.get('methods', []):
            for site in method.get('invokes', []):
                if hit(site['owner']):
                    classes[owner]['types'].add(site['owner'])
                    callee = 'new ' + short(site['owner']) + '()' if site['name'] == '<init>' else f"{short(site['owner'])}.{site['name']}()"
                    classes[owner]['sites'].append(dict(where=f"{short(fqn)}.{method['name']}", text=f"{method_label(fqn, method['name'])} calls {callee}",
                        line=site.get('line'), api=f"{site['owner']}.{site['name']}"))
            for annotation in method.get('annotations', []):
                if hit(annotation['type']):
                    classes[owner]['types'].add(annotation['type'])
                    classes[owner]['sites'].append(dict(where=f"{short(fqn)}.{method['name']}", text=f"{short(fqn)}.{method['name']}() is annotated @{short(annotation['type'])}", line=None))
        if info.get('super_name') and hit(info['super_name']):
            classes[owner]['types'].add(info['super_name'])
            classes[owner]['sites'].append(dict(where=short(fqn), text=f"{short(fqn)} extends {info['super_name']}", line=None))
        for field in info.get('fields', []):
            for annotation in field.get('annotations', []):
                if hit(annotation['type']):
                    classes[owner]['types'].add(annotation['type'])
                    classes[owner]['sites'].append(dict(where=f"{short(fqn)}.{field['name']}", text=f"field {short(fqn)}.{field['name']} is annotated @{short(annotation['type'])}", line=None))
    rows = []
    for fqn in sorted(classes, key=lambda n: (-len(classes[n]['sites']), n)):
        item = classes[fqn]
        unique_sites = list({s['text'] + str(s['line']): s for s in item['sites']}.values())
        rows.append(dict(class_name=fqn, package=model.package(fqn) if fqn in model.classes else fqn.rpartition('.')[0],
            apis=sorted(item['types'])[:20], api_count=len(item['types']), call_site_count=len(unique_sites),
            call_sites=unique_sites[:limit_sites], edge_types=sorted(item['edge_types'])))
    return dict(classes=rows[:limit_classes], class_count=len(rows), call_site_count=sum(r['call_site_count'] for r in rows),
        truncated=len(rows) > limit_classes)


def evaluate(model, inventory: dict | None, rules: dict | None = None, today: date | None = None, max_age_days: int | None = None) -> dict:
    rules = rules or load_rules()
    inventory = inventory or {}
    dependencies = _dependency_rows(inventory)
    findings = []
    for rule in rules['rules']:
        match = rule.get('match', {})
        if match.get('java_target'):
            by_target = defaultdict(list)
            for fqn, info in model.facts.items():
                by_target[info['java_target']].append(model.owners.get(fqn, fqn))
            targets = {t: sorted(set(v)) for t, v in by_target.items()}
            if not targets:
                for major, count in (inventory.get('bytecode', {}).get('major_versions') or {}).items():
                    targets[max(1, int(major) - 44)] = []
            for target, names in sorted(targets.items()):
                verdict = _versioned_status(rule, str(target))
                findings.append(_finding(rule, verdict, f'Java {target}', [dict(kind='BYTECODE', text=f'class-file major version {target + 44} (Java {target}) in {len(names) or "some"} classes')],
                    dict(classes=[dict(class_name=n, package=n.rpartition('.')[0], apis=[], call_sites=[], call_site_count=0, api_count=0) for n in names[:200]],
                         class_count=len(names), call_site_count=0, truncated=len(names) > 200), suffix=str(target)))
            continue
        deps = [d for d in dependencies if _matches_artifact(d, match.get('artifacts', []))]
        usage = package_usage(model, match.get('packages', []), excluded=match.get('exclude_packages')) if match.get('packages') else dict(classes=[], class_count=0, call_site_count=0, truncated=False)
        if not deps and not usage['class_count']:
            continue
        versions = sorted({d['version'] for d in deps if d.get('version') and _version_tuple(d['version'])}, key=_version_tuple)
        evidence = [dict(kind=d['source'], text=f"{d.get('group_id') + ':' if d.get('group_id') else ''}{d['artifact_id']} {d.get('version') or '(version not recorded)'}") for d in deps[:10]]
        if usage['class_count']:
            evidence.append(dict(kind='BYTECODE', text=f"{usage['class_count']} application classes reference {', '.join(match['packages'][:4])}* with {usage['call_site_count']} code references"))
        if versions:
            for version in versions:
                findings.append(_finding(rule, _versioned_status(rule, version), version, evidence, usage, suffix=version))
        else:
            reason = ('found by package usage in bytecode; no dependency version is recorded in the artifact metadata'
                if usage['class_count'] else 'dependency present but its version is inherited or unresolved in the artifact metadata')
            findings.append(_finding(rule, _versioned_status(rule, None), None, evidence, usage, version_reason=reason))
    findings.sort(key=lambda f: (STATUS_ORDER[f['status']], -f['affected_class_count'], f['technology']))
    summary = defaultdict(int)
    for item in findings:
        summary[item['status']] += 1
    return dict(rules=freshness(rules, today, max_age_days), findings=findings, summary=dict(summary),
        inputs=dict(dependency_rows=len(dependencies), bytecode_facts=model.facts_available,
            dependency_inventory_status=inventory.get('dependency_inventory_status', 'NOT_AVAILABLE')),
        label='Lifecycle status (end-of-life / aging / current) from lifecycle-rules.yaml; it is not a vulnerability assessment.',
        limitations=([] if model.facts_available else ['Bytecode facts are unavailable for this analysis, so call sites cannot be listed; '
            'package usage comes from class-level external dependencies only.']) + (inventory.get('limitations') or [])[:2])


def _finding(rule, verdict, version, evidence, usage, suffix='', version_reason=None):
    count = usage['class_count']
    weight = EFFORT_WEIGHT.get(rule.get('effort', 'medium'), 2)
    replacement = rule.get('replacement')
    plain = {'end-of-life': f"{rule['technology']} is no longer supported by its maintainers.",
        'aging': f"{rule['technology']} still works but has been superseded and will become harder to support.",
        'current': f"{rule['technology']} is a supported version."}[verdict['status']]
    if count:
        plain += f" {count} class{'es' if count != 1 else ''} in this application use it."
    return dict(id=rule['id'] + (':' + suffix if suffix else ''), rule_id=rule['id'], technology=rule['technology'], category=rule.get('category'),
        version_found=version, version_reason=version_reason if version is None else None, status=verdict['status'],
        status_note=verdict['note'], matched_range=verdict['matched_range'], source_url=rule['source'],
        recommended_alternative=rule.get('alternative'), replacement=replacement, migration_notes=rule.get('migration_notes'),
        effort_hint=rule.get('effort', 'medium'),
        effort_index=dict(value=weight * max(count, 1), formula='effort weight (low=1, medium=2, high=3) x max(affected classes, 1)',
            inputs=dict(effort_weight=weight, affected_classes=count), label='Effort index = effort weight × affected classes, a heuristic for ordering work, not a time or cost estimate.'),
        evidence=evidence, affected_class_count=count, call_site_count=usage['call_site_count'], affected_classes=usage['classes'],
        affected_truncated=usage['truncated'],
        explanation=dict(technical=f"Rule {rule['id']}: {rule['technology']}" + (f' {version}' if version else '') +
            f" -> {verdict['status']}" + (f" (range {verdict['matched_range']})" if verdict['matched_range'] else '') +
            (f". {verdict['note']}" if verdict['note'] else '.'), plain=plain))


def compatibility_summary(evaluation: dict) -> dict:
    """Replaces the former NOT_CHECKED placeholders in tech_inventory.compatibility."""
    def worst(category_filter):
        rows = [f for f in evaluation['findings'] if category_filter(f)]
        if not rows:
            return 'NO_MATCHING_RULE'
        return min(rows, key=lambda f: STATUS_ORDER[f['status']])['status'].upper().replace('-', '_')
    return dict(java_lifecycle=worst(lambda f: f['rule_id'] == 'java-class-target'),
        framework_lifecycle=worst(lambda f: f['category'] in ('framework', 'library', 'namespace')),
        deprecated_apis='SEE_TECHNICAL_DEBT_RULE_DEPRECATED_API',
        vulnerability_advisories='OUT_OF_SCOPE',
        reason=f"Evaluated with lifecycle rules {evaluation['rules']['rules_version']} reviewed {evaluation['rules']['reviewed']}. "
               'Vulnerability advisories are out of scope for lifecycle rules and are not assessed.')
