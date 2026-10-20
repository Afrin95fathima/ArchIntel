"""Every term the UI scores or counts, defined once with its exact formula and inputs.
The UI glossary panel and the report appendix both read this module."""
from __future__ import annotations

from .debt_rates import BY_ID, RATE_DEFS, DERIVED


def entries() -> list[dict]:
    out = []
    for definition in RATE_DEFS + DERIVED:
        out.append(dict(id='rate:' + definition['id'], group='Technical problem rates', term=definition['label'],
            answers=f"What share of the {definition['unit']} have this problem?",
            formula=f"{definition['id']} = numerator / denominator × 100, rounded to one decimal",
            numerator=definition['numerator'], denominator=definition['denominator'],
            inputs=[f"rule(s) {', '.join(definition['rules'])}" if definition.get('rules') else 'derived from the dependency graph and entry-point inventory'],
            not_measured='Shown as "not measured" with the reason when the denominator is zero or the input (bytecode facts, runtime session) is missing.'))
    out.append(dict(id='debt-index', group='Technical debt', term='Debt index', answers='How heavy is the debt in this package, as an ordering aid?',
        formula='debt index = 3 × HIGH + 2 × MEDIUM + 1 × LOW (+4 × CRITICAL, INFO = 0); density = index / classes in the package',
        numerator='severity-weighted count of findings in the package', denominator='classes in the package (for density)', inputs=['findings of all rules'],
        not_measured='Not a time, cost or currency estimate.'))
    out.extend(EXTRA)
    return out


EXTRA: list[dict] = []
