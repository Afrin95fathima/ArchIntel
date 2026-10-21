"""Non-functional constraints for the modernization plan, taken from the responsibility analysis.

The plan's scores are not changed. What this adds is evidence the plan did not have: findings and soft blockers per domain
(security controls, shared data models, transactions across domains, shared components, technical domains), recommendations
that name what to decide, and a document section that states what was not examined. Every item keeps the detection status of
the responsibility analysis: an indicator found in bytecode is DETECTED, its consequence is always INFERRED.
"""
from __future__ import annotations

from collections import defaultdict

from app.insight.model import InsightModel

# risk rule -> (plan finding kind, blocker code or None)
MAPPING = {
    'RISK-SEC-NO-CONTROL': ('SECURITY_CONTROL_NOT_DETECTED', 'SECURITY_CONTROL_REVIEW'),
    'RISK-SEC-PARTIAL': ('SECURITY_CONTROL_NOT_DETECTED', 'SECURITY_CONTROL_REVIEW'),
    'RISK-DATA-SHARED-MODEL': ('SHARED_DATA_MODEL', 'SHARED_DATA_MODEL_REVIEW'),
    'RISK-DATA-TX-SPAN': ('TRANSACTION_SPANS_DOMAINS', 'TRANSACTION_BOUNDARY_REVIEW'),
    'RISK-PERF-EAGER-FETCH': ('PERFORMANCE_INDICATOR', None),
    'RISK-PERF-UNBOUNDED-QUERY': ('PERFORMANCE_INDICATOR', None),
    'RISK-OBS-NO-INSTRUMENTATION': ('NO_INSTRUMENTATION_DETECTED', None),
    'RISK-REL-NO-RESILIENCE': ('RELIABILITY_PROTECTION_NOT_DETECTED', None),
    'RISK-SCAL-STATIC-STATE': ('SHARED_MUTABLE_STATE', None),
    'RISK-MAINT-RESPONSIBILITIES': ('CLASS_WITH_MANY_RESPONSIBILITIES', None),
    'RISK-MAINT-SHARED-COMPONENT': ('CROSS_CUTTING_DEPENDENCY', 'CROSS_CUTTING_REVIEW'),
}
SEVERITY_RANK = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
UNAVAILABLE = ('Bytecode facts are not available for this analysis, so non-functional constraints cannot be derived. '
               'The ArchIntel plan below does not account for security, performance, reliability or data-integrity concerns; run a new analysis to include them.')


def analyse(static: dict, domains: list[dict]) -> dict:
    """Run the responsibility analysis with the plan's domain membership (which may be a reviewed one)."""
    patched = dict(static, domains=[dict(id=d['id'], name=d['name'], classes=list(d['classes']), confidence=d.get('confidence'), confidence_note=d.get('confidence_note')) for d in domains])
    return InsightModel('plan-responsibility', patched).responsibility


def build(static: dict, domains: list[dict]) -> dict:
    """Return `by_domain` (what the plan engine adds per domain) and `document` (the section stored with the proposal)."""
    analysis = analyse(static, domains)
    if analysis['status'] != 'AVAILABLE':
        return dict(by_domain={}, document=dict(status='NOT_AVAILABLE', reason=analysis.get('reason') or UNAVAILABLE, limitation=UNAVAILABLE))
    membership = {c: d['id'] for d in domains for c in d['classes']}
    names = {d['id']: d['name'] for d in domains}
    caps = analysis['capabilities']
    by_domain = {d['id']: dict(findings=[], blockers=[], recommendations=[], concerns=[], kind=caps.get(d['id'], {}).get('kind'), implications=caps.get(d['id'], {}).get('implications', [])) for d in domains}
    risk_domains = {}
    for risk in analysis['risks']:
        touched = sorted({membership[c] for c in risk['affected_components'] if c in membership})
        risk_domains[risk['id']] = touched
        kind, blocker = MAPPING.get(risk['rule_id'], (None, None))
        if not kind:
            continue
        for did in touched:
            entry = by_domain[did]
            subjects = [c.rsplit('.', 1)[-1] for c in risk['affected_components']][:10]
            entry['findings'].append(dict(kind=kind, severity=risk['severity'], text=f'{risk["description"]}. {risk["consequence"]}', subjects=subjects, risk_id=risk['id'], rule_id=risk['rule_id'], evidence_ids=risk['evidence_ids'],
                                          measured=dict(affected_components=risk['affected_count'], detection_status=risk['detection_status'], runtime_validation_required=risk['runtime_validation_required']),
                                          threshold={'rule': risk['rule_id'], 'consequence_status': risk['consequence_status']}))
            if blocker and caps.get(did, {}).get('kind') != 'TECHNICAL' and blocker not in entry['blockers']:
                entry['blockers'].append(blocker)
    for item in analysis['cross_cutting']:
        if item['kind'] in ('SHARED_INFRASTRUCTURE', 'SHARED_FUNCTIONAL_COMPONENT', 'SHARED_DATA_ACCESS'):
            for did in sorted({membership[c] for c in [item['component']] + item['dependents'] if c in membership}):
                if 'CROSS_CUTTING_REVIEW' not in by_domain[did]['blockers'] and caps.get(did, {}).get('kind') != 'TECHNICAL':
                    by_domain[did]['blockers'].append('CROSS_CUTTING_REVIEW')
    for did, entry in by_domain.items():
        cap = caps.get(did)
        if cap and cap['kind'] == 'TECHNICAL':
            entry['findings'].append(dict(kind='TECHNICAL_DOMAIN', severity='MEDIUM', subjects=[names[did]], risk_id=None, rule_id='CAPABILITY-KIND', evidence_ids=[],
                                          text=f'{names[did]} holds technical concerns rather than a business capability ({cap["basis"]}). It is not a candidate for extraction as a service.',
                                          measured=dict(classes=cap['class_count'], kind=cap['kind']), threshold={'technical_share': 0.5}))
            entry['blockers'].append('TECHNICAL_DOMAIN_REVIEW')
        if cap:
            entry['concerns'] = cap['nonfunctional_concerns']
            actionable = [i for i in cap['implications'] if i['kind'] != 'NO_BLOCKING_CONSTRAINT_DETECTED' and i['severity'] != 'LOW']
            if actionable:
                affected = sorted({c for r in analysis['risks'] if did in risk_domains[r['id']] for c in r['affected_components']})
                entry['recommendations'].append(dict(kind='ADDRESS_NONFUNCTIONAL_CONSTRAINT', text=' '.join(i['text'] for i in actionable[:3]), affected_classes=affected[:20], dependency_pairs=[],
                                                     proposed_interface=None, target_domains=[], missing_evidence=['runtime validation (Performance tab or a load test) of every risk flagged runtime_validation_required', 'application.properties and gateway controls, which a compiled artifact does not show']))
        entry['findings'].sort(key=lambda f: (SEVERITY_RANK[f['severity']], f['kind'], f['text']))
    document = dict(status='AVAILABLE', engine_version=analysis['analysis_metadata']['engine_version'], rules_version=analysis['analysis_metadata']['rules_version'],
                    capabilities=[dict(domain_id=c['id'], name=c['name'], kind=c['kind'], basis=c['basis'], primary_counts=c['primary_counts'], nonfunctional_concerns=c['nonfunctional_concerns'],
                                       implications=c['implications'], risk_ids=c['risk_ids'], boundary_notes=c['boundary_notes'], boundary_confidence=c['boundary_confidence']) for c in sorted(caps.values(), key=lambda c: c['name'])],
                    cross_cutting=[dict(id=i['id'], name=i['name'], kind=i['kind'], capabilities=[c['name'] for c in i['capabilities']], dependent_count=i['dependent_count'], deployment_form=i['deployment_form'],
                                        guidance=i['guidance'], concerns=i['concerns']) for i in analysis['cross_cutting']],
                    risks=[dict(id=r['id'], rule_id=r['rule_id'], category=r['category'], severity=r['severity'], title=r['title'], description=r['description'], affected_components=r['affected_components'][:10],
                                affected_count=r['affected_count'], domains=[dict(id=d, name=names[d]) for d in risk_domains[r['id']]], detection_status=r['detection_status'], consequence_status=r['consequence_status'],
                                runtime_validation_required=r['runtime_validation_required'], investigate=r['investigate'], confidence=r['confidence']) for r in analysis['risks']],
                    summary=analysis['summary'], limitations=analysis['limitations'],
                    not_examined=['configuration files and values', 'runtime behavior, load and failure handling', 'gateway, platform and network controls', 'source code of the shared components'])
    return dict(by_domain=by_domain, document=document)
