"""Write real insight API outputs for the compiled fixtures to frontend test fixtures.

Run from the repository root: python scripts/export_insight_fixtures.py
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'backend' / 'tests')]

from insight_fixtures import model  # noqa: E402
from app.insight import lifecycle  # noqa: E402

OUT = ROOT / 'frontend' / 'src' / 'insight' / 'fixtures'


def views(name):  # noqa: C901
    m = model(name)
    from app.insight import cycles, metrics, debt, graphview, details, test_suggestions, diagrams
    out = {'lifecycle': lifecycle.evaluate(m, {}, today=None), 'cycles': cycles.analyse(m), 'metrics': metrics.compute(m), 'debt': debt.detect(m), 'tests': test_suggestions.build(m), 'hld': diagrams.hld(m),
        'lld': diagrams.lld(m, 'org.springframework.samples.petclinic.owner' if name == 'petclinic' else 'com.fixture.edge.cycle.a'),
        'sequence': diagrams.sequence_static(m, next(e['id'] for e in m.entry_points['items'] if e['handler_method'] in ('processNewVisitForm', 'create'))), 'graph': graphview.view(m, 'package', debt=debt.detect(m)),
        'node': details.node(m, 'org.springframework.samples.petclinic.owner.OwnerController' if 'org.springframework.samples.petclinic.owner.OwnerController' in m.classes else 'system', debt.detect(m))}
    try:
        from app.insight import exports
        out.update(exports.all_views(m))
    except ImportError:
        pass
    return out


def brief_fixture():
    """The decision brief of a PetClinic plan with half the classes observed and the domains reviewed."""
    from test_modernization import pure  # noqa: E402
    from insight_fixtures import snapshot  # noqa: E402
    document = pure(snapshot('petclinic'), observations=.5, reviewed=True)[0]
    return {'decision_brief': document['decision_brief'], 'assessments': [{k: a[k] for k in ('domain_id', 'domain_name')} for a in document['assessments']]}


def technology_plan_fixture():
    """The technology plan for the edge-case fixture, which has deliberately aging dependencies."""
    from test_modernization import pure  # noqa: E402
    from insight_fixtures import snapshot  # noqa: E402
    return pure(snapshot('edgecases'), observations=.5, reviewed=True)[0]['technology_plan']


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'frontend' / 'src' / 'modernization' / 'fixtures').mkdir(exist_ok=True)
    (ROOT / 'frontend' / 'src' / 'modernization' / 'fixtures' / 'edgecases.technology-plan.json').write_text(json.dumps(technology_plan_fixture(), indent=1, sort_keys=True, default=str) + '\n', encoding='utf-8')
    (ROOT / 'frontend' / 'src' / 'modernization' / 'fixtures' / 'petclinic.brief.json').write_text(json.dumps(brief_fixture(), indent=1, sort_keys=True, default=str) + '\n', encoding='utf-8')
    for name in ('petclinic', 'edgecases'):
        for view, data in views(name).items():
            (OUT / f'{name}.{view}.json').write_text(json.dumps(data, indent=1, sort_keys=True, default=str) + '\n', encoding='utf-8')
    print('wrote', sorted(p.name for p in OUT.glob('*.json')))


if __name__ == '__main__':
    main()
