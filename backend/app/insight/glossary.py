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


EXTRA: list[dict] = [
    dict(id='readiness', group='Domain scores', term='Readiness', answers='How ready is this domain (or the system) to be modernized or extracted?',
        formula='readiness = sum(component x weight) over the measured structural inputs; weights = configured cohesion/decoupling/cycles/database weights x 0.8, plus boundary size 0.12 and class concentration 0.08; weights of inputs that are not measured are removed and the rest scaled to sum to 1',
        numerator='component values from 0 to 100, one per measured input', denominator='the sum of the weights of the measured inputs (scaled to 1)',
        inputs=['cohesion = internal edges / (internal + outgoing edges) x 100', 'decoupling = (1 - outgoing / (internal + outgoing)) x 100',
                'cycle freedom = (1 - classes in cycles / classes) x 100, minus 25 when a cycle spans other domains', 'data independence = (1 - shared repositories / repositories) x 100',
                'boundary size = 100 / (1 + crossing class pairs / max(1, sqrt(classes)))', 'class concentration = 100 - 15 x God-class candidates (floor 0)'],
        not_measured='An input without a denominator (no dependency edges, no repository, no God-class findings) is excluded and listed with its reason; it is never replaced by a default. Heuristic ordering aid, not a probability of success.'),
    dict(id='confidence', group='Domain scores', term='Confidence', answers='How much evidence supports the readiness number?',
        formula='confidence = sum(input x weight) over the measured evidence inputs; policy weights static 0.30, runtime coverage 0.30, review 0.15, resolved references 0.15, runtime data quality 0.10, rescaled to sum to 1 over the measured inputs',
        numerator='input values from 0 to 100', denominator='the sum of the weights of the measured inputs (scaled to 1)',
        inputs=['static boundary evidence = clustering confidence x 100 (stability, conductance, size)', 'runtime coverage = observed classes / classes of the domain x 100',
                'review status = 100 when a domain review is recorded, else 0', 'resolved references = dependency facts joining two classes with a domain / all dependency facts of the domain x 100',
                'runtime data quality = (1 - (counted quality issues, +1 when spans are unverified) / accepted spans) x 100'],
        not_measured='Behavioral validation and data-ownership review are listed as not measured until they are recorded; they are not scored as zero. Heuristic evidence index, not a calibrated probability.'),
    dict(id='runtime-readiness', group='Domain scores', term='Runtime readiness', answers='Do the observed calls support extracting this domain?',
        formula='runtime = sum(component x weight) over the measured components, weights renormalized; combined = structural weight x structural + (1 - structural weight) x runtime',
        numerator='component values from 0 to 100', denominator='the sum of the weights of the measured components (scaled to 1)',
        inputs=['cohesion = observed internal calls / observed calls from the domain x 100', 'cycles = 0 if the domain is in an observed domain cycle, else 100',
                'persistence = resources called by this domain alone / resources it calls x 100'],
        not_measured='A domain with no mapped outgoing or internal call has no runtime score; the structural score is kept.'),
]
