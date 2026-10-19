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


def views(name):
    m = model(name)
    from app.insight import cycles, metrics
    out = {'lifecycle': lifecycle.evaluate(m, {}, today=None), 'cycles': cycles.analyse(m), 'metrics': metrics.compute(m)}
    try:
        from app.insight import exports
        out.update(exports.all_views(m))
    except ImportError:
        pass
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ('petclinic', 'edgecases'):
        for view, data in views(name).items():
            (OUT / f'{name}.{view}.json').write_text(json.dumps(data, indent=1, sort_keys=True, default=str) + '\n', encoding='utf-8')
    print('wrote', sorted(p.name for p in OUT.glob('*.json')))


if __name__ == '__main__':
    main()
