"""Retrieval-grounded explanations. No unsupported generative facts."""
from typing import Protocol
from app.schemas import AssistantResponse


class LLMProvider(Protocol):
    def select_facts(self, question: str, facts: list[dict]) -> list[str]: ...


class LocalEvidenceProvider:
    def select_facts(self, question: str, facts: list[dict]) -> list[str]:
        return [f['id'] for f in facts]


class OllamaProvider:
    """Reserved adapter; direct model access is disabled pending the AI gateway."""
    def __init__(self, url: str, model: str):
        self.url, self.model = url, model

    def select_facts(self, question: str, facts: list[dict]) -> list[str]:
        raise RuntimeError('Model dispatch requires the Phase 2 AI gateway.')


class ArchitectureContextBuilder:
    def build(self, result: dict, question: str, domain_id: str | None) -> tuple[list[dict], list[str]]:
        text = question.lower()
        domains = [d for d in result['domains'] if d['id']==domain_id] if domain_id else [d for d in result['domains'] if d['name'].lower() in text]
        facts, recommendations = [], []
        if domain_id and not domains:
            return [], []
        relevant = any(w in text for w in ('architect','domain','risk','modern','extract','start','readiness','coupl','depend','cycle','metric','issue','class','database','summary','overview','why','sequence','first'))
        if not domains and not relevant:
            return [], []
        if domains:
            for domain in domains[:2]:
                assessment = next(a for a in result['modernization'] if a['domain_id']==domain['id'])
                facts += [
                    dict(id=domain['id'], kind='domain', text=f"{domain['name']} contains {domain['class_count']} classes in {domain['package_count']} packages; candidate confidence {domain['confidence']:.0%}."),
                    dict(id='assessment:'+domain['id'], kind='modernization', text=f"Readiness is {assessment['readiness_score']}/100; difficulty {assessment['extraction_difficulty']}. Components: {assessment['component_scores']}."),
                    dict(id='coupling:'+domain['id'], kind='domain', text=f"Cross-domain outgoing ratio is {domain['metrics']['cross_domain_ratio']:.1%}, based on {domain['metrics']['outgoing_edges']} distinct outgoing cross-domain edges."),
                    dict(id='database:'+domain['id'], kind='domain', text=f"Database evidence: {domain['database']['status']}. {len(domain['database']['shared_repositories'])} shared repository candidates. Runtime SQL remains unknown.")
                ]
                for issue in [i for i in result['issues'] if domain['id'] in i['domain_ids']][:4]:
                    facts.append(dict(id=issue['id'], kind='issue', text=issue['severity'] + ': ' + issue['title'] + '. ' + issue['why_it_matters']))
                    recommendations.append(issue['recommendation'])
                recommendations.extend(assessment['risks'][:2])
        elif any(w in text for w in ('first','start','sequence','modern','extract','readiness')):
            for assessment in result['modernization'][:6]:
                facts.append(dict(id='assessment:'+assessment['domain_id'],kind='modernization',
                    text=f"#{assessment['recommended_order']} {assessment['domain_name']}: {assessment['readiness_score']}/100, wave {assessment['wave']}. {assessment['sequence_reason']}"))
            recommendations.append('Validate runtime transactions and business ownership before accepting this extraction sequence.')
        elif 'cycle' in text:
            for cycle in result['cycles'][:8]:
                facts.append(dict(id=cycle['id'],kind='cycle',text=f"{cycle['level']} cyclic cluster: {cycle['node_count']} nodes, {cycle['internal_edge_count']} edges; severity {cycle['severity']}. Members: {', '.join(cycle['members'][:8])}."))
            if not facts:
                facts.append(dict(id='summary',kind='summary',text='No multi-node class or package SCCs were detected in the filtered static graph.'))
            recommendations.append('Treat the domains of a dependency cycle as one remediation group before attempting independent extraction.')
        else:
            summary = result['summary']
            facts.append(dict(id='summary',kind='summary',text=f"Analysis found {summary['class_count']} classes, {summary['package_count']} packages, {summary['dependency_count']} distinct internal dependencies and {summary['domain_count']} candidate domains."))
            for issue in result['issues'][:6]:
                facts.append(dict(id=issue['id'],kind='issue',text=issue['severity']+': '+issue['title']))
                recommendations.append(issue['recommendation'])
        return facts[:12], list(dict.fromkeys(recommendations))[:5]


def answer(result: dict, question: str, domain_id: str | None, settings, request=None, db=None, analysis_id=None) -> AssistantResponse:
    facts, recommendations = ArchitectureContextBuilder().build(result, question, domain_id)
    mode, limits = 'LOCAL_EVIDENCE', list(result['limitations'][:2])
    if not facts:
        return AssistantResponse(answer='I do not have analysis evidence for that question in the selected analysis. Ask about a candidate domain, its dependencies, cycles, issues, readiness or modernization order.',
            facts=[], recommendations=[], sources=[], mode=mode, limitations=limits)
    if request is not None:
        from app.ai.gateway import select_facts
        facts, gateway = select_facts(request, db, facts, question, 'analysis:'+analysis_id)
        mode = gateway['mode']
        limits.append('AI gateway: '+gateway['reason']+'. Request: '+gateway['request_id'])
        if gateway['redaction_categories']:
            limits.append('Sensitive categories redacted: '+', '.join(gateway['redaction_categories']))
    elif settings.llm_url and settings.llm_model:
        limits.append('Legacy model settings in config.py do not authorize dispatch. Register a provider and enable the workspace policy (MODEL_USE_LOCAL).')
    return AssistantResponse(answer='These findings come from this analysis. Recommendations below require architectural review.',
        facts=facts, recommendations=recommendations, sources=[{'id':f['id'],'kind':f['kind']} for f in facts],
        mode=mode, limitations=limits)
