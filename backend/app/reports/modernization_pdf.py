"""Small dependency-free PDF renderer for a consolidated modernization report."""
from datetime import datetime, timezone
import textwrap
import unicodedata
import zlib


def _plain(value):
    value = str(value if value is not None else 'Unavailable')
    value = value.replace('\u2192', '->').replace('\u2013', '-').replace('\u2014', '-').replace('\u2022', '*')
    return unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')


def _coverage_line(label, record):
    if not isinstance(record, dict):
        return f'{label}: Unavailable'
    if record.get('percentage') is not None:
        return f"{label}: {record.get('observed', '?')} / {record.get('total', '?')} ({record['percentage']}%)"
    return f"{label}: {record.get('status', 'UNAVAILABLE')} - {record.get('reason', 'No percentage available')}"


def _humanize(value):
    labels={
        'EVIDENCE_SUPPORTS_REVIEW':'Evidence supports a review',
        'INVENTORY_AVAILABLE_REVIEW_REQUIRED':'Inventory available; compatibility review required',
        'INSUFFICIENT_EVIDENCE':'Not enough evidence to assess',
        'CONDITIONAL':'Conditional on listed checks',
        'READY_TO_PLAN':'Ready to plan', 'NEEDS_EVIDENCE':'Needs more evidence', 'BLOCKED':'Blocked by a hard risk',
        'UNKNOWN':'Unknown', 'UNCONFIRMED':'Not confirmed', 'NOT_CHECKED':'Not checked',
        'OBSERVED':'Observed in selected sessions', 'UNOBSERVED':'Not observed in selected sessions',
        'METHOD_CALL':'Method call', 'FIELD_TYPE':'Field or type reference', 'EXTENDS':'Inheritance',
        'IMPLEMENTS':'Interface implementation', 'ANNOTATION':'Annotation reference',
        'STATIC_ONLY':'Found in code structure only', 'STATIC_AND_DYNAMIC':'Found in code and runtime',
        'DYNAMIC_ONLY':'Observed at runtime only',
    }
    text=str(value if value is not None else 'Unavailable')
    return labels.get(text,text.replace('_',' ').title())


def _report_lines(application, run, version, assessment, sessions, projection):
    static = run.result or {}
    summary = static.get('summary') or {}
    twin = version.document or {}
    plan = assessment.document or {}
    brief = plan.get('decision_brief') or {}
    coverage = twin.get('coverage') or {}
    yield ('cover', 'ArchIntel Modernization Intelligence Report')
    yield ('subtitle', application.name)
    yield ('meta', f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | Evidence baseline {run.id}")
    yield ('meta', f"Architecture version {version.id} | Proposal {assessment.id}")
    yield ('notice', 'Confidential working report. Candidate boundaries and modernization recommendations require engineering review.')

    yield ('page', '')
    yield ('h1', 'Executive overview')
    fit = brief.get('strategy_fit') or {}
    yield ('p', fit.get('rationale') or brief.get('summary') or f"The saved proposal contains {len(plan.get('assessments', []))} domain assessments and {len(plan.get('waves', []))} planning waves.")
    yield ('kv', 'Strategy fit\x00' + _plain(fit.get('recommendation','REVIEW_REQUIRED')).replace('_',' ').title())
    yield ('kv', 'Overall evidence confidence\x00' + _plain(brief.get('overall_confidence','Unavailable')))
    yield ('kv', 'Effort estimate\x00' + _plain(brief.get('effort_range','Heuristic bands unavailable; no duration forecast')))
    for action in brief.get('top_actions', [])[:3]: yield ('bullet', 'Priority action: ' + action)
    if brief.get('top_risks'):
        for risk in brief['top_risks'][:3]: yield ('bullet', 'Top risk: ' + risk)
    yield ('kv', 'Requested strategy\x00' + _humanize(brief.get('selected_strategy') or plan.get('target', {}).get('strategy')))
    yield ('kv', 'Planning objective\x00' + _plain(brief.get('objective') or plan.get('target', {}).get('objective')))
    validation_state = (plan.get('validation') or {}).get('status')
    yield ('kv', 'Proposal schema check\x00' + ('Passed' if validation_state == 'VALIDATED' else _plain(validation_state or 'Not detected')))
    yield ('kv', 'Architecture observation scope\x00' + f"{len(version.manifest.get('runtime_session_ids', []))} runtime session(s)")
    yield ('notice', 'Plain-language note: this is a decision aid. It describes possible modernization steps; it has not changed the application or proved that a proposed move is safe.')
    blocker_meanings = {
        'PINNED_SOURCE_AND_PASSING_BUILD': ('Pin the exact source revision and confirm a clean build.', 'Record the repository commit and run the normal build pipeline.'),
        'BEHAVIORAL_CONTRACTS': ('Expected user-visible behavior has not been protected by contracts.', 'Add representative API and workflow tests before changing boundaries.'),
        'DATA_OWNERSHIP_REVIEW': ('Business ownership and write authority for data are not confirmed.', 'Review entities, repositories, transactions and database permissions with owners.'),
        'HUMAN_CHANGE_APPROVAL': ('A reviewer has not approved this proposal for implementation.', 'Obtain explicit architecture and product-owner review.'),
        'RUNTIME_OBSERVATION_GAP': ('Selected sessions cover only part of the domain.', 'Exercise the missing entry points and retain method-level telemetry.'),
        'DOMAIN_REVIEW_REQUIRED': ('Candidate domain membership remains heuristic.', 'Review and save class membership with an architect.'),
        'UNRESOLVED_MAPPING': ('Some runtime observations do not map to known classes.', 'Resolve class/method identities and capture a new version.'),
        'RUNTIME_QUALITY_REVIEW': ('Telemetry loss or mapping uncertainty weakens conclusions.', 'Resolve dropped, conflicting or unverified spans before relying on absence.'),
        'EVIDENCE_CONFLICT': ('Evidence sources disagree.', 'Inspect cited traces and static references, then resolve the conflict.'),
        'CROSS_DOMAIN_CYCLE': ('Candidate domains depend on each other in a cycle.', 'Plan a joint cycle-remediation step before independent extraction.'),
        'SHARED_PERSISTENCE_REVIEW': ('Multiple domains access a common observed data resource.', 'Confirm table/entity ownership and transaction boundaries.'),
        'COMPATIBILITY_INVENTORY_REQUIRED': ('Upgrade compatibility has not been fully checked.', 'Review target versions against authoritative compatibility and security data.'),
    }
    all_blockers = list(dict.fromkeys(blocker for row in plan.get('assessments', []) for blocker in row.get('blockers', [])))
    blockers = all_blockers[:3]
    if blockers:
        yield ('h2', 'Top blockers to resolve')
        for blocker in blockers: yield ('bullet', blocker_meanings.get(blocker,('Review the cited evidence and record a resolution.',))[0])
    if all_blockers:
        yield ('h2', 'Blocker guide')
        domain_names_by_id = {row.get('domain_id'): row.get('domain_name', row.get('domain_id')) for row in plan.get('assessments', [])}
        for blocker in all_blockers:
            meaning, remediation = blocker_meanings.get(blocker, ('This condition needs review before relying on the proposal.', 'Review the cited evidence and record a resolution.'))
            affected = ', '.join(domain_names_by_id.get(row.get('domain_id'), row.get('domain_id')) for row in plan.get('assessments', []) if blocker in row.get('blockers', []))
            yield ('row', f'{blocker.replace("_"," ").title()} | {meaning} | Affected: {affected or "System-wide"} | Resolve: {remediation}')

    yield ('page', '')
    yield ('h1', '1. Static analysis: what the code scan found')
    yield ('p', 'In everyday terms: this section counts and examines the structure present in the submitted application files. It does not show what users actually do at runtime.')
    artifact = summary.get('artifact') or {}
    yield ('kv', 'Source artifact\x00' + _plain(artifact.get('filename', 'Unavailable')))
    yield ('kv', 'Artifact SHA-256\x00' + _plain(artifact.get('sha256', version.manifest.get('artifact_sha256', 'Unavailable'))))
    yield ('kv', 'Discovered structure\x00' + f"{summary.get('class_count', len(static.get('classes', [])))} classes | {summary.get('package_count', '?')} packages | {summary.get('dependency_count', '?')} dependencies | {summary.get('domain_count', len(static.get('domains', [])))} candidate domains")
    scale = [(label, summary.get(key)) for label, key in (('Classes', 'class_count'), ('Packages', 'package_count'), ('Dependencies', 'dependency_count'), ('Candidate domains', 'domain_count')) if isinstance(summary.get(key), (int, float))]
    if scale: yield ('chart', ('Architecture scale', 'The submitted artifact contains the counts shown below.', 'Source: static analysis summary.', scale))
    counts = summary.get('issue_counts') or {}
    if counts:
        yield ('kv', 'Static findings by severity/type\x00' + ', '.join(f'{k}: {v}' for k, v in sorted(counts.items())))
        severity = [(str(k).title(), v) for k, v in sorted(counts.items(), key=lambda item: ({'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}.get(item[0], 4))) if isinstance(v, (int, float))]
        if severity: yield ('chart', ('Findings by severity', 'Severity counts are reported as returned by the static analyzer.', 'Source: static analysis summary.', severity))
    yield ('p', 'Scope: this layer reflects structures discovered in the submitted compiled artifact.')
    baseline_by_domain = {a.get('domain_id'): a for a in static.get('modernization', []) if isinstance(a, dict)}
    domain_sizes = [(d.get('name', d.get('id', 'Domain')), d.get('class_count', len(d.get('classes', [])))) for d in static.get('domains', []) if isinstance(d.get('class_count', len(d.get('classes', []))), (int, float))]
    if static.get('domains'):
        yield ('page', '')
        yield ('h1', 'Candidate domains')
    if domain_sizes: yield ('chart', ('Candidate domain size', 'Class counts show how the current structural candidates are distributed.', 'Source: static domain discovery.', domain_sizes))
    for domain in static.get('domains', []):
        baseline = baseline_by_domain.get(domain.get('id'), {})
        yield ('row', f"{domain.get('name', domain.get('id', 'Domain'))} | {domain.get('class_count', len(domain.get('classes', [])))} classes | readiness {baseline.get('readiness_score', domain.get('readiness_score', domain.get('score', 'Unavailable')))} | evidence confidence {domain.get('confidence', 'Unavailable')} | difficulty {baseline.get('extraction_difficulty', 'Unavailable')}")
    issues = sorted(static.get('issues', []), key=lambda x: ({'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}.get(x.get('severity'), 4), x.get('title', '')))
    if issues:
        yield ('page', '')
        yield ('h2', f'All static findings ({len(issues)} total)')
        for issue in issues:
            yield ('finding', issue)
    else:
        yield ('p', 'No static findings were returned for this baseline.')

    yield ('page', '')
    yield ('h1', '2. Dynamic analysis: what was observed while running')
    yield ('p', 'In everyday terms: these measurements show which parts were seen during the selected test sessions. A low percentage means more testing may be needed; an unobserved part is not proof that it is unused.')
    if sessions:
        for session in sessions:
            yield ('row', f"{session.name} | {session.environment} | {session.status} | {session.trace_count} traces / {session.span_count} spans | session {session.id}")
        for key, label in (('classes', 'Classes'), ('entry_points', 'Entry points'), ('methods', 'Methods'), ('dependencies', 'Dependencies'), ('domains', 'Domains')):
            yield ('kv', label + '\x00' + _coverage_line(label, coverage.get(key)))
        coverage_values = [(label, record.get('percentage')) for key, label in (('classes', 'Classes'), ('entry_points', 'Entry points'), ('methods', 'Methods'), ('dependencies', 'Dependencies'), ('domains', 'Domains')) if isinstance((record := coverage.get(key)), dict) and isinstance(record.get('percentage'), (int, float))]
        if coverage_values: yield ('chart', ('Observed runtime coverage', 'These values describe only the selected sessions and exercised workloads.', 'Source: selected runtime session coverage.', coverage_values))
        quality = twin.get('quality') or {}
        yield ('kv', 'Telemetry quality\x00' + (', '.join(f'{k}: {v}' for k, v in sorted(quality.items())) or 'No quality summary available'))
        yield ('p', 'Coverage is limited to telemetry received from the listed sessions and workloads. Unobserved means not seen in these sessions.')
    else:
        yield ('p', 'No completed runtime sessions are bound to this architecture version. Runtime coverage is not observed for this snapshot.')

    yield ('page', '')
    yield ('h1', '3. Saved architecture picture (Digital twin)')
    yield ('p', 'This is ArchIntel’s saved picture of the application and its evidence at one point in time. It is a snapshot, not a live model.')
    yield ('kv', 'Version name and ID\x00' + f'{version.name} | {version.id}')
    yield ('kv', 'Snapshot fingerprint\x00' + version.fingerprint)
    yield ('kv', 'Canonical graph\x00' + f"{len(twin.get('graph', {}).get('nodes', []))} nodes | {len(twin.get('graph', {}).get('edges', []))} relationships")
    yield ('kv', 'Evidence records / architecture facts\x00' + f"{twin.get('evidence_count', 0)} evidence records | {twin.get('facts_count', 0)} facts")
    yield ('kv', 'Knowledge graph projection\x00' + projection.get('state', 'Unavailable'))
    twin_counts = [(label, value) for label, value in (('Graph nodes', len(twin.get('graph', {}).get('nodes', []))), ('Relationships', len(twin.get('graph', {}).get('edges', []))), ('Evidence records', twin.get('evidence_count')), ('Architecture facts', twin.get('facts_count'))) if isinstance(value, (int, float))]
    if twin_counts: yield ('chart', ('Digital twin evidence', 'Canonical graph and evidence counts describe this saved architecture version.', 'Source: architecture version snapshot.', twin_counts))
    tech = twin.get('tech_inventory') or static.get('tech_inventory') or {}
    if tech:
        yield ('h2','Technology and upgrade inventory')
        yield ('kv','Inventory state\x00'+_plain(tech.get('status','UNAVAILABLE')))
        bytecode=tech.get('bytecode',{})
        yield ('kv','Java bytecode target(s)\x00'+(', '.join(map(str,bytecode.get('java_targets',[]))) or 'Not detected'))
        yield ('kv','Build tools\x00'+(', '.join(x.get('name','Unknown') for x in tech.get('build_tools',[])) or 'Not detected'))
        yield ('kv','Frameworks\x00'+('; '.join(x.get('name','Unknown')+' '+','.join(x.get('versions',[])) for x in tech.get('frameworks',[])) or 'Not detected'))
        yield ('kv','Dependency records\x00'+str(len(tech.get('dependencies',[])))+' versioned metadata record(s); bundled libraries: '+str(len(tech.get('bundled_libraries',[]))))
        for dep in tech.get('dependencies',[]):
            yield ('bullet',f"Dependency: {dep.get('group_id')}:{dep.get('artifact_id')} {dep.get('version') or 'version unknown'} ({_humanize(dep.get('version_status','UNKNOWN'))})")
        for dep in tech.get('bundled_libraries',[]):
            yield ('bullet',f"Bundled library: {dep.get('artifact_id')} {dep.get('version') or 'version not encoded in filename'}")
        compat=tech.get('compatibility',{})
        yield ('kv','Lifecycle / vulnerability checks\x00'+f"Java {compat.get('java_lifecycle','NOT_CHECKED')} | framework {compat.get('framework_lifecycle','NOT_CHECKED')} | vulnerabilities {compat.get('vulnerability_advisories','NOT_CHECKED')}")
        for limitation in tech.get('limitations',[]): yield ('sub',limitation)
    if projection.get('state') not in ('APPLIED', 'CURRENT'):
        yield ('notice', 'The graph projection is not available. Canonical evidence remains in the saved version and can still be reviewed or exported.')
    unknowns = twin.get('unknowns') or []
    if unknowns:
        yield ('h2', 'Known unknowns')
        for item in unknowns:
            yield ('bullet', item)

    quality = plan.get('data_quality') or {}
    yield ('page','')
    yield ('h1','Data quality and failure remediation')
    yield ('kv','Source artifact\x00'+str(quality.get('artifact_state','UNAVAILABLE'))+' - '+str(quality.get('artifact_impact','Artifact availability was not recorded.')))
    if quality.get('artifact_remediation'): yield ('sub','Remediation: '+quality['artifact_remediation'])
    projection_state=projection.get('state',quality.get('graph_projection_state','UNAVAILABLE'))
    yield ('kv','Knowledge graph projection\x00'+str(projection_state))
    if projection_state not in ('APPLIED','CURRENT'):
        yield ('sub','Impact: graph exploration may be incomplete; the canonical architecture version and evidence store remain the source of truth.')
        yield ('sub','Remediation: inspect the projection error and attempts in Local setup, fix the graph connection or schema issue, then use Projection rebuild for this version.')
    yield ('kv','Method mapping\x00'+str(quality.get('method_mapping_state','UNKNOWN')))
    if quality.get('method_mapping_impact'): yield ('sub','Impact: '+quality['method_mapping_impact'])
    if quality.get('method_mapping_remediation'): yield ('sub','Remediation: '+quality['method_mapping_remediation'])

    yield ('page', '')
    yield ('h1', '4. Modernization proposal: possible plan')
    yield ('p', 'The steps below are proposals to review with the people who own the application. Scores help compare areas; they are not guarantees of effort, safety, or business fit.')
    yield ('kv', 'Planning rule / calibration\x00' + f"{plan.get('rule_version', 'Unavailable')} / {plan.get('calibration_version', 'Unavailable')}")
    yield ('kv', 'Currentness\x00Saved against the selected immutable architecture version')
    if brief.get('headline'):
        yield ('p', brief['headline'])
    for assessment_row in plan.get('assessments', []):
        yield ('row', f"{assessment_row.get('domain_name', assessment_row.get('domain_id'))} | structural {assessment_row.get('structural_score', '?')} | runtime observation {assessment_row.get('runtime_score', 'Unavailable')} | combined {assessment_row.get('combined_score', '?')} | confidence {assessment_row.get('confidence_score', '?')}% | adjusted readiness {assessment_row.get('confidence_adjusted_score', '?')} ({_humanize(assessment_row.get('readiness_label','NEEDS_EVIDENCE'))}) | effort {assessment_row.get('effort_band','Unknown')} | risk {assessment_row.get('risk_band','Unknown')}")
        if assessment_row.get('cost_drivers'):
            yield ('sub', 'Heuristic estimate drivers: ' + '; '.join(assessment_row['cost_drivers']))
        for recommendation in assessment_row.get('recommendations', []):
            yield ('bullet', f"Recommended for {assessment_row.get('domain_name', assessment_row.get('domain_id'))}: {recommendation.get('text')}")
            if recommendation.get('affected_classes'):
                yield ('sub', 'Affected classes: ' + ', '.join(recommendation['affected_classes'][:20]))
            if recommendation.get('proposed_interface'):
                yield ('sub', 'Candidate interface: ' + recommendation['proposed_interface'])
            if recommendation.get('finding_ids'):
                yield ('sub', 'Supporting finding IDs: ' + ', '.join(recommendation['finding_ids']))
            if recommendation.get('missing_evidence'):
                yield ('sub', 'Still needed: ' + '; '.join(recommendation['missing_evidence']))
    paired = [(str(row.get('domain_name', row.get('domain_id', 'Domain'))), row.get('confidence_adjusted_score', row.get('combined_score')), row.get('confidence_score'), row.get('readiness_label','NEEDS REVIEW')) for row in plan.get('assessments', [])]
    if paired: yield ('paired', ('Readiness and confidence by domain', 'Paired bars expose high scores with weak evidence; readiness is confidence-adjusted.', 'Source: saved modernization proposal.', paired))
    matrix = plan.get('domain_dependency_matrix') or {}
    if matrix.get('domain_ids'):
        yield ('page','')
        yield ('h2','Cross-domain dependency map')
        yield ('p','Each cell counts static class-level dependency edges from the row domain to the column domain. Blank or zero means no edge was found in this scan, not proof of no runtime interaction.')
        yield ('matrix', matrix)
        yield ('domain_graph', matrix)
        for row in matrix.get('rows', []):
            kinds=', '.join(f"{_humanize(kind)} {count}" for kind,count in sorted(row.get('edge_types',{}).items()))
            yield ('row', f"{row.get('source_domain')} -> {row.get('target_domain')}: {row.get('edge_count')} class-level edges; {row.get('distinct_source_classes')} source classes and {row.get('distinct_target_classes')} target classes. Types: {kinds or 'not classified'}")
        for item in matrix.get('top_boundary_classes', [])[:10]:
            yield ('bullet', f"Boundary class: {item.get('class_name')} | {item.get('boundary_edges')} edge(s) | {item.get('domain')}")
    ownership = plan.get('data_ownership') or {}
    if ownership:
        yield ('h2','Data ownership evidence')
        for item in ownership.get('per_domain', {}).values():
            yield ('bullet', f"{item.get('domain','Domain')}: {len(item.get('entities',[]))} entity candidate(s), {len(item.get('repositories',[]))} repository reference(s); ownership {_humanize(item.get('ownership','UNKNOWN'))}.")
            if item.get('leakage_candidates'):
                for leak in item['leakage_candidates']:
                    yield ('sub',f"Possible concept leakage: {leak.get('class_name')} is in {leak.get('current_domain')} but its name matches {leak.get('likely_concept_domain')} ({_humanize(leak.get('confidence'))}).")
        for item in ownership.get('duplicated_models', []): yield ('bullet', f"Possible duplicated model {item.get('concept')}: {', '.join(item.get('classes',[]))} ({item.get('confidence')}).")
        for item in ownership.get('limitations', []): yield ('sub', item)
    entry_inventory = plan.get('entry_points') or {}
    if entry_inventory.get('items'):
        yield ('h2','Entry points and domain observation')
        for assessment_row in plan.get('assessments', []):
            per_domain=assessment_row.get('runtime_coverage',{})
            for measure,record in per_domain.items():
                if record.get('total') is not None:
                    yield ('row',f"{assessment_row.get('domain_name')}: observed {measure.replace('_',' ')} {record.get('observed')} / {record.get('total')} ({record.get('percentage')}%)")
        for item in entry_inventory['items'][:100]:
            yield ('row', f"{item.get('domain')}: {_humanize(item.get('kind'))} | {item.get('http_method')} {item.get('path')} | {item.get('handler_class')}.{item.get('handler_signature')} | {_humanize(item.get('observation_state'))}")
        yield ('p', entry_inventory.get('limitation','Route annotation values may be unavailable.'))
    if plan.get('dead_code_candidates'):
        yield ('h2','Unobserved and unreferenced candidates')
        yield ('p','These are investigation candidates only; reflection, configuration wiring and unselected workloads can create false negatives.')
        for item in plan['dead_code_candidates'][:50]: yield ('bullet', f"{item.get('class_name')} ({item.get('domain_id')}): {item.get('reason')}")
    baseline_metrics=brief.get('baseline_metrics') or {}
    targets=brief.get('proposed_targets') or {}
    if baseline_metrics:
        yield ('h2','Before-and-after measures')
        yield ('p','The baseline values come from this static scan. Target values are proposed planning targets, not forecasts.')
        for key,label in (('cycle_count','Dependency cycle count'),('god_class_count','God-class candidates'),('cross_domain_edge_count','Cross-domain class edges'),('shared_entity_count','Duplicated model candidates'),('average_cross_domain_coupling','Average cross-domain coupling')):
            target=targets.get(key,{})
            yield ('row',f"{label}: baseline {baseline_metrics.get(key,'Unavailable')} | proposed target {target.get('target','Not set')} | {target.get('basis','No target basis recorded.')}")
    decisions = plan.get('decisions', [])
    if decisions:
        yield ('h2', 'Proposed actions and blockers')
        for decision in decisions:
            domain = next((a.get('domain_name') for a in plan.get('assessments', []) if a.get('domain_id') == decision.get('domain_id')), decision.get('domain_id', 'Domain'))
            yield ('bullet', f"{domain}: {decision.get('action', 'Review proposal')}")
    if plan.get('waves'):
        yield ('page', '')
        yield ('h2', 'Proposed roadmap')
    for wave in plan.get('waves', []):
        yield ('h2', f"Planning wave {wave.get('number', '?')}")
        wave_domain_names = {domain.get('id'): domain.get('name', domain.get('id')) for domain in static.get('domains', [])}
        yield ('p', f"Domains: {', '.join(wave_domain_names.get(domain, domain) for domain in wave.get('domains', [])) or 'None listed'}. {wave.get('reason', '')}")
        if wave.get('blockers'):
            yield ('sub', 'Blocker codes are explained once in the Blocker guide above.')
        yield ('sub', 'Entry criteria: ' + '; '.join(wave.get('entry_criteria',[])))
        yield ('sub', 'Exit criteria: ' + '; '.join(wave.get('exit_criteria',[])))
    domain_names = {domain.get('id'): domain.get('name', domain.get('id')) for domain in static.get('domains', [])}
    wave_sizes = [(f"Wave {wave.get('number', '?')}: {', '.join(domain_names.get(d, d) for d in wave.get('domains', [])) or 'No domains'}", len(wave.get('domains', []))) for wave in plan.get('waves', [])]
    if wave_sizes: yield ('chart', ('Proposed modernization waves', 'Wave sizes reflect the saved proposal; sequence and boundaries remain reviewable proposals.', 'Source: saved modernization proposal.', wave_sizes))
    decomposition = plan.get('microservice_decomposition') or {}
    candidates = decomposition.get('service_candidates') or []
    if candidates:
        yield ('h2', f'Candidate service boundaries ({len(candidates)} proposed)')
        yield ('p', 'These are architecture-derived candidates for review, not confirmed business capabilities or generated standalone services.')
        for candidate in candidates:
            yield ('bullet', f"{candidate.get('name', candidate.get('id'))}: {_humanize(candidate.get('proposal_state', candidate.get('decision', 'REVIEW')))}; {len(candidate.get('class_ids', []))} classes; readiness {candidate.get('readiness', 'Unavailable')}; confidence {candidate.get('evidence_confidence', 'Unavailable')}; blockers listed in proposal export.")
        execution = decomposition.get('execution') or {}
        yield ('kv', 'Code-generation/execution state\x00' + _humanize(execution.get('state', 'Not reported')))
        for setup in decomposition.get('shared_setup', [])[:20]:
            yield ('bullet', 'Shared setup: ' + setup)
    comparison = brief.get('strategy_comparison') or []
    if comparison:
        yield ('page', '')
        yield ('h2', 'Strategy comparison')
        for candidate in comparison:
            yield ('bullet', f"{_humanize(candidate.get('strategy'))}: {_humanize(candidate.get('status'))} - {candidate.get('rationale', '')} Unknowns: {' '.join(candidate.get('unknowns', []))}")
    questions = brief.get('unresolved_questions') or []
    if questions:
        yield ('page', '')
        yield ('h2', 'Questions requiring customer or engineering input')
        for question in questions:
            yield ('bullet', question)
    if brief.get('next_step'):
        yield ('kv', 'Suggested next step\x00' + brief['next_step'])
    reviews = getattr(assessment, 'reviews', [])
    yield ('kv', 'Human review state\x00' + (', '.join(_humanize(r.get('state', 'UNKNOWN')) for r in reviews) if reviews else 'No human review recorded'))
    yield ('p', 'The saved proposal records planning intent and review state; it does not authorize code changes, extraction, data migration or deployment.')
    limitations = list(dict.fromkeys((plan.get('limitations') or []) + (version.document.get('unknowns') or [])))
    if limitations:
        yield ('page', '')
        yield ('h1', 'Appendix - scope and limitations')
        yield ('h2', 'Limitations')
        for item in limitations:
            yield ('bullet', item)
    yield ('footer_note', 'Report provenance: ArchIntel analysis, architecture version, runtime session IDs, evidence fingerprint, and saved modernization proposal are identified above. Use the workspace exports for full machine-readable evidence and all findings.')


def _escape(text):
    raw = _plain(text).encode('ascii', 'replace')
    out = bytearray()
    for byte in raw:
        if byte in (40, 41, 92):
            out.append(92)
        if byte < 32 or byte > 126:
            out.extend(f'\\{byte:03o}'.encode('ascii'))
        else:
            out.append(byte)
    return bytes(out)


def render_modernization_report(application, run, version, assessment, sessions, projection):
    """Render an accessible, visual PDF with a plain-language layer and full evidence detail."""
    page_width, page_height = 612, 792
    margin, bottom = 48, 52
    pages, commands = [], []
    y = page_height - 58
    palette = {
        'navy': '0.06 0.16 0.30', 'navy2': '0.10 0.24 0.39',
        'teal': '0.00 0.62 0.57', 'blue': '0.20 0.48 0.76',
        'gold': '0.94 0.62 0.18', 'coral': '0.86 0.31 0.27',
        'ink': '0.12 0.18 0.25', 'muted': '0.34 0.40 0.48',
        'pale': '0.94 0.97 0.99', 'pale_teal': '0.88 0.97 0.95',
        'pale_gold': '1 0.96 0.86', 'line': '0.82 0.87 0.91', 'white': '1 1 1',
    }
    cover_page = False

    def rect(x, y0, width, height, color):
        commands.append(f'{color} rg {x:.1f} {y0:.1f} {width:.1f} {height:.1f} re f'.encode('ascii'))

    def text_at(text, x, y0, size=9, font='F1', color=None):
        color = color or palette['ink']
        commands.append(f'{color} rg'.encode('ascii'))
        commands.append(b'BT /' + font.encode('ascii') + b' ' + str(size).encode('ascii') + b' Tf ' + f'{x:.1f} {y0:.1f} Td ('.encode('ascii') + _escape(text) + b') Tj ET')

    def new_page():
        nonlocal commands, y, cover_page
        if commands:
            pages.append(commands)
        commands = []
        cover_page = False
        y = page_height - 66
        commands.extend([
            f'{palette["navy"]} rg'.encode('ascii'), b'0 748 612 44 re f',
            f'{palette["white"]} rg'.encode('ascii'), b'BT /F2 9 Tf 48 764 Td (ARCHINTEL  |  ARCHITECTURE INTELLIGENCE) Tj ET',
            f'{palette["teal"]} rg'.encode('ascii'), b'0 744 612 4 re f',
        ])

    def line(text, size=10, font='F1', color='0.12 0.18 0.15', gap=14, indent=0):
        nonlocal y
        if y < bottom + gap:
            new_page()
        commands.append(f'{color} rg'.encode('ascii'))
        commands.append(b'BT /' + font.encode('ascii') + b' ' + str(size).encode('ascii') + b' Tf ' + str(margin + indent).encode('ascii') + b' ' + str(y).encode('ascii') + b' Td (' + _escape(text) + b') Tj ET')
        y -= gap

    def wrapped(text, width=94, **options):
        normalized = _plain(text)
        for paragraph in normalized.splitlines() or ['']:
            pieces = textwrap.wrap(paragraph, width=width, break_long_words=True, break_on_hyphens=True) or ['']
            for piece in pieces:
                line(piece, **options)

    def chart(spec):
        nonlocal y
        title, takeaway, source, raw_items = spec
        items = [(str(label), max(0, float(value))) for label, value in raw_items if isinstance(value, (int, float))]
        if not items:
            return
        if y < bottom + min(330, 68 + len(items) * 25):
            new_page()
        line(title, size=12, font='F2', color=palette['navy'], gap=19)
        wrapped(takeaway, width=100, size=8, color=palette['muted'], gap=12)
        max_value = max((value for _, value in items), default=1) or 1
        colors = (palette['teal'], palette['blue'], palette['gold'], palette['coral'])
        for index, (label, value) in enumerate(items):
            if y < bottom + 18:
                new_page()
            row_y = y
            short = label if len(label) <= 27 else label[:24] + '...'
            text_at(short, margin + 3, row_y - 4, 8, 'F1', palette['ink'])
            rect(222, row_y - 8, 277, 8, palette['pale'])
            rect(222, row_y - 8, 277 * value / max_value, 8, colors[index % len(colors)])
            text_at(f'{value:g}', 510, row_y - 4, 8, 'F2', palette['navy'])
            y -= 24
        wrapped('Source: ' + source, width=100, size=7, color=palette['muted'], gap=10)
        y -= 6

    def paired_chart(spec):
        nonlocal y
        title, takeaway, source, raw_items = spec
        items = [(str(name), float(readiness), float(confidence), str(label)) for name, readiness, confidence, label in raw_items
                 if isinstance(readiness, (int,float)) and isinstance(confidence, (int,float))]
        if not items: return
        if y < bottom + min(360, 90 + len(items)*35): new_page()
        line(title,size=12,font='F2',color=palette['navy'],gap=19)
        wrapped(takeaway,width=100,size=8,color=palette['muted'],gap=12)
        for name, readiness, confidence, label in items:
            if y < bottom+35: new_page()
            text_at(name[:27],margin+3,y-4,8,'F1',palette['ink'])
            rect(222,y-8,235,7,palette['pale']); rect(222,y-8,235*max(0,min(100,readiness))/100,7,palette['teal'])
            rect(222,y-19,235,7,palette['pale']); rect(222,y-19,235*max(0,min(100,confidence))/100,7,palette['blue'])
            text_at(f'R {readiness:g} | C {confidence:g}',462,y-4,7,'F2',palette['navy'])
            text_at(label.replace('_',' ')[:18],462,y-16,6,'F1',palette['muted'])
            y-=34
        wrapped('Green = confidence-adjusted readiness; blue = evidence confidence. Source: '+source,width=100,size=7,color=palette['muted'],gap=10)
        y-=5

    def dependency_matrix(matrix):
        nonlocal y
        ids=matrix.get('domain_ids',[]); rows=matrix.get('rows',[])
        if not ids:return
        if y < bottom+210:new_page()
        names={d['id']:d['name'] for d in ids}; order=[d['id'] for d in ids]; values={(r['source_domain_id'],r['target_domain_id']):r['edge_count'] for r in rows}
        maximum=max(values.values(),default=1) or 1; cell=min(40,420/max(1,len(order)))
        line('Domain dependency matrix (source row -> target column)',size=10,font='F2',color=palette['navy'],gap=18)
        start_x=margin+126; start_y=y
        for j,did in enumerate(order):
            text_at(names[did][:10],start_x+j*cell,start_y-7,6,'F1',palette['muted'])
        y-=13
        for i,s in enumerate(order):
            text_at(names[s][:20],margin+2,y-9,7,'F1',palette['ink'])
            for j,t in enumerate(order):
                value=values.get((s,t),0); intensity=value/maximum
                color=f'{0.94-0.58*intensity:.2f} {0.97-0.40*intensity:.2f} {0.99-0.12*intensity:.2f}'
                rect(start_x+j*cell,y-14,cell-2,15,color)
                text_at(str(value),start_x+j*cell+cell/2-3,y-9,7,'F2',palette['navy'])
            y-=18
        y-=5
        wrapped('Cell values are class-level dependency edge counts. Absent domain pairs equal zero in the captured static graph.',width=100,size=7,color=palette['muted'],gap=10)
        y-=8

    def dependency_graph(matrix):
        nonlocal y
        ids=matrix.get('domain_ids',[]); rows=matrix.get('rows',[])
        if not ids:return
        if y < bottom+245:new_page()
        names={d['id']:d['name'] for d in ids}; cx=306; cy=y-112; radius=76
        line('Directed domain graph (edge labels show class-pair counts)',size=10,font='F2',color=palette['navy'],gap=18)
        order=[d['id'] for d in ids]
        positions={did:(cx+radius*__import__('math').cos(2*__import__('math').pi*i/len(order)),cy+radius*__import__('math').sin(2*__import__('math').pi*i/len(order))) for i,did in enumerate(order)}
        maximum=max((r['edge_count'] for r in rows),default=1)
        for row in rows:
            x1,y1=positions[row['source_domain_id']]; x2,y2=positions[row['target_domain_id']]
            commands.append(f'{palette["blue"]} RG {0.6+1.4*row["edge_count"]/maximum:.1f} w {x1:.1f} {y1:.1f} m {x2:.1f} {y2:.1f} l S'.encode('ascii'))
            text_at(str(row['edge_count']),(x1+x2)/2,(y1+y2)/2,7,'F2',palette['coral'])
        for did,(x,y0) in positions.items():
            rect(x-29,y0-10,58,20,palette['pale_teal']); text_at(names[did][:12],x-25,y0-3,6,'F2',palette['navy'])
        if not rows:
            text_at('No cross-domain edges were found in the static graph.',margin,cy-radius-17,7,'F1',palette['muted'])
        y=cy-radius-20

    new_page()
    # The report opens with a designed cover, then uses a consistent high-contrast
    # page header, color-coded section bars, and clear evidence source labels.
    pages.clear()
    commands = []
    y = 700
    for kind, text in _report_lines(application, run, version, assessment, sessions, projection):
        if kind == 'page':
            if len(commands) > 4:
                new_page()
        elif kind == 'chart':
            chart(text)
        elif kind == 'paired':
            paired_chart(text)
        elif kind == 'matrix':
            dependency_matrix(text)
        elif kind == 'domain_graph':
            dependency_graph(text)
        elif kind == 'cover':
            cover_page = True
            rect(0, 0, page_width, page_height, palette['navy'])
            rect(0, 0, 14, page_height, palette['teal'])
            rect(398, 492, 214, 300, palette['navy2'])
            rect(440, 542, 132, 132, palette['teal'])
            rect(468, 570, 76, 76, palette['navy'])
            rect(506, 608, 42, 42, palette['gold'])
            text_at('ARCHINTEL  |  ARCHITECTURE INTELLIGENCE', 48, 718, 10, 'F2', palette['teal'])
            y = 625
            wrapped(text, width=37, size=27, font='F2', color=palette['white'], gap=34)
        elif kind == 'subtitle':
            wrapped(text, width=55, size=18, font='F2', color=palette['teal'], gap=24)
        elif kind == 'meta':
            wrapped(text, width=90, size=8, color='0.83 0.88 0.94' if cover_page else palette['muted'], gap=13)
        elif kind == 'notice':
            if cover_page:
                rect(42, y - 44, 522, 43, palette['navy2'])
                wrapped(text, width=93, size=9, color=palette['white'], gap=13, indent=10)
                y -= 8
            else:
                rect(42, y - 30, 522, 30, palette['pale_gold'])
                rect(42, y - 30, 4, 30, palette['gold'])
                wrapped(text, width=92, size=8, color=palette['ink'], gap=12, indent=10)
                y -= 10
        elif kind == 'h1':
            if y < bottom + 50:
                new_page()
            rect(42, y - 22, 522, 30, palette['pale_teal'])
            rect(42, y - 22, 5, 30, palette['teal'])
            wrapped(text, width=74, size=14, font='F2', color=palette['navy'], gap=18, indent=10)
            y -= 12
        elif kind == 'h2':
            y -= 3
            wrapped(text, width=82, size=11, font='F2', color=palette['blue'], gap=15)
        elif kind == 'kv':
            key, value = text.split('\x00', 1)
            wrapped(key.upper(), width=92, size=7, font='F2', color=palette['blue'], gap=10, indent=4)
            wrapped(value, width=92, size=9, color=palette['ink'], gap=13, indent=4)
        elif kind == 'row':
            rect(46, y - 11, 510, 18, palette['pale'])
            rect(46, y - 11, 3, 18, palette['blue'])
            wrapped(text, width=92, size=8, color=palette['ink'], gap=12, indent=8)
        elif kind == 'bullet':
            wrapped('- ' + text, width=90, size=8, color=palette['ink'], gap=12, indent=8)
        elif kind == 'finding':
            issue = text
            severity = str(issue.get('severity', 'UNRANKED')).upper()
            severity_color = palette['coral'] if severity in ('CRITICAL', 'HIGH') else palette['gold'] if severity == 'MEDIUM' else palette['blue']
            wrapped(f'{severity}  |  {issue.get("title") or issue.get("issue_type") or issue.get("id")}', width=88, size=10, font='F2', color=severity_color, gap=14)
            wrapped('Plain meaning: ' + str(issue.get('why_it_matters') or issue.get('description') or 'No plain-language explanation was supplied.'), width=93, size=8, color=palette['ink'], gap=12, indent=8)
            wrapped('Technical target: ' + str(issue.get('entity_type', 'entity')) + ' / ' + str(issue.get('entity_id', 'not specified')) + '  |  Type: ' + str(issue.get('issue_type', 'not specified')), width=93, size=7, color=palette['muted'], gap=11, indent=8)
            evidence = issue.get('evidence')
            if evidence:
                wrapped('Evidence: ' + str(evidence), width=93, size=7, color=palette['muted'], gap=11, indent=8)
            wrapped('Suggested investigation: ' + str(issue.get('recommendation') or 'No recommendation was supplied.'), width=93, size=8, color=palette['ink'], gap=12, indent=8)
            y -= 7
        elif kind == 'sub':
            wrapped(text, width=88, size=8, color=palette['muted'], gap=12, indent=15)
        elif kind == 'footer_note':
            y -= 6
            wrapped(text, width=95, size=8, color=palette['muted'], gap=12)
        elif kind == 'p':
            wrapped(text, width=95, size=8, color=palette['ink'], gap=12)
            y -= 2
    if commands:
        pages.append(commands)

    total = len(pages)
    objects = [None, b'<< /Type /Catalog /Pages 2 0 R >>', None,
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>']
    page_ids = []
    for index, page_commands in enumerate(pages, start=1):
        footer_color = palette['white'] if index == 1 else palette['muted']
        footer = f'{footer_color} rg BT /F1 8 Tf 48 30 Td (Confidential working report  |  Page {index} of {total}) Tj ET'.encode('ascii')
        stream = b'\n'.join(page_commands + [footer])
        compressed = zlib.compress(stream)
        content_id = len(objects)
        objects.append(b'<< /Length ' + str(len(compressed)).encode('ascii') + b' /Filter /FlateDecode >>\nstream\n' + compressed + b'\nendstream')
        page_id = len(objects)
        page_ids.append(page_id)
        objects.append(b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents ' + str(content_id).encode('ascii') + b' 0 R >>')
    kids = b' '.join(str(page_id).encode('ascii') + b' 0 R' for page_id in page_ids)
    objects[2] = b'<< /Type /Pages /Kids [' + kids + b'] /Count ' + str(total).encode('ascii') + b' >>'
    output = bytearray(b'%PDF-1.4\n%ArchIntel\n')
    offsets = [0]
    for object_id, obj in enumerate(objects[1:], start=1):
        offsets.append(len(output))
        output.extend(str(object_id).encode('ascii') + b' 0 obj\n' + obj + b'\nendobj\n')
    xref = len(output)
    output.extend(b'xref\n0 ' + str(len(objects)).encode('ascii') + b'\n0000000000 65535 f \n')
    for offset in offsets[1:]:
        output.extend(f'{offset:010d} 00000 n \n'.encode('ascii'))
    output.extend(b'trailer\n<< /Size ' + str(len(objects)).encode('ascii') + b' /Root 1 0 R >>\nstartxref\n' + str(xref).encode('ascii') + b'\n%%EOF\n')
    return bytes(output)

