"""Evaluation harness: scripted questions with known answers + a hallucination check. Reports pass rate."""
from __future__ import annotations

import json
from pathlib import Path

from .evidence import FQN, CAMEL, Index, known_names
from .planner import answer
from .tools import Tools


def run(model, questions: list[dict], analysis_id: str = 'eval') -> dict:
    from app.config import Settings
    tools = Tools(model, Settings(_env_file=None, data_dir=Path('/nonexistent-eval')), analysis_id)
    index, known = Index(model), known_names(model)
    results, hallucinated = [], []
    for item in questions:
        out = answer(tools, item['q'])
        text = ' '.join(s['text'] for s in out['sentences'])
        cites = [c for s in out['sentences'] for c in s['cites']]
        failures = []
        for needle in item.get('contains', []):
            if needle.lower() not in text.lower():
                failures.append(f'missing {needle!r}')
        for needle in item.get('absent', []):
            if needle.lower() in text.lower():
                failures.append(f'unexpected {needle!r}')
        if 'status' in item and out['status'] != item['status']:
            failures.append(f"status {out['status']} != {item['status']}")
        for needle in item.get('cites', []):
            if needle not in cites:
                failures.append(f'missing citation {needle}')
        if item.get('cites_prefix') and not any(c.startswith(item['cites_prefix']) for c in cites):
            failures.append(f"no citation starting {item['cites_prefix']}")
        if item.get('has_code') and not any(s.get('code') for s in out['sentences']):
            failures.append('no code block')
        bad_cites = [c for c in cites if not index.exists(c)]
        if bad_cites:
            failures.append(f'citations do not exist: {bad_cites[:3]}')
        unknown = sorted({n for n in FQN.findall(text) if n not in known and not n.startswith(('java.', 'jakarta.', 'javax.', 'org.', 'com.'))} | {n for n in CAMEL.findall(text) if n not in known and n not in item['q']})
        if unknown:
            hallucinated.append(dict(q=item['q'], names=unknown))
            failures.append(f'unknown identifiers {unknown[:3]}')
        results.append(dict(q=item['q'], passed=not failures, failures=failures, status=out['status']))
    passed = sum(r['passed'] for r in results)
    return dict(total=len(results), passed=passed, pass_rate=round(passed / len(results), 4), hallucinated_answers=len(hallucinated), hallucinations=hallucinated, results=results)


def run_file(model, path: Path) -> dict:
    return run(model, json.loads(path.read_text(encoding='utf-8'))['questions'])
