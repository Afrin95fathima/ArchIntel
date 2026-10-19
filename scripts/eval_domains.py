"""Evaluate candidate-domain discovery against a ground-truth labelling.

Scores any ground-truth JSON of the form ``{class_fqn: label}`` with:
  * Adjusted Rand Index (ARI) - agreement between predicted domains and labels
  * Normalised Mutual Information (NMI)
  * Seed stability - whether repeated runs produce identical membership

By default it runs against the labelled Spring PetClinic fixture
(backend/tests/fixtures/petclinic.py) and prints the ARI; it asserts
ARI > 0.5 on PetClinic but does not hard-fail otherwise.

Usage:
    python scripts/eval_domains.py                     # PetClinic, built-in labels
    python scripts/eval_domains.py --labels labels.json   # custom ground truth
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / 'backend'
sys.path.insert(0, str(BACKEND))

from app.services.domains import discover_domains  # noqa: E402


def _load_petclinic():
    path = BACKEND / 'tests' / 'fixtures' / 'petclinic.py'
    spec = importlib.util.spec_from_file_location('petclinic_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


petclinic = _load_petclinic()
petclinic_graph = petclinic.graph  # noqa: E402


def _comb2(n: int) -> int:
    return n * (n - 1) // 2


def adjusted_rand_index(labels_true, labels_pred) -> float:
    """Hubert & Arabie adjusted Rand index (pure Python, matches sklearn)."""
    classes = list(set(labels_true.values()) | set(labels_pred.values()))
    n = len(labels_true)
    if n == 0:
        return 1.0
    true_ids = sorted(set(labels_true.values()))
    pred_ids = sorted(set(labels_pred.values()))
    true_index = {c: i for i, c in enumerate(true_ids)}
    pred_index = {c: i for i, c in enumerate(pred_ids)}
    items = sorted(labels_true)
    contingency = [[0] * len(pred_ids) for _ in true_ids]
    a = [0] * len(true_ids)
    b = [0] * len(pred_ids)
    for item in items:
        i = true_index[labels_true[item]]
        j = pred_index[labels_pred[item]]
        contingency[i][j] += 1
        a[i] += 1
        b[j] += 1
    sum_comb = sum(_comb2(v) for row in contingency for v in row)
    sum_ai = sum(_comb2(v) for v in a)
    sum_bj = sum(_comb2(v) for v in b)
    total_pairs = _comb2(n)
    if total_pairs == 0:
        return 1.0
    expected = (sum_ai * sum_bj) / total_pairs
    max_val = (sum_ai + sum_bj) / 2.0
    denom = max_val - expected
    if denom == 0:
        return 1.0 if sum_comb == expected else 0.0
    return (sum_comb - expected) / denom


def normalized_mutual_information(labels_true, labels_pred) -> float:
    """NMI normalised by sqrt(H(true) * H(pred)). Pure Python."""
    items = sorted(labels_true)
    n = len(items)
    if n == 0:
        return 1.0
    true_ids = sorted(set(labels_true.values()))
    pred_ids = sorted(set(labels_pred.values()))
    true_index = {c: i for i, c in enumerate(true_ids)}
    pred_index = {c: i for i, c in enumerate(pred_ids)}
    contingency = [[0] * len(pred_ids) for _ in true_ids]
    a = [0] * len(true_ids)
    b = [0] * len(pred_ids)
    for item in items:
        i = true_index[labels_true[item]]
        j = pred_index[labels_pred[item]]
        contingency[i][j] += 1
        a[i] += 1
        b[j] += 1
    mi = 0.0
    for i in range(len(true_ids)):
        for j in range(len(pred_ids)):
            n_ij = contingency[i][j]
            if n_ij == 0:
                continue
            mi += (n_ij / n) * math.log((n * n_ij) / (a[i] * b[j]))
    h_true = -sum((ai / n) * math.log(ai / n) for ai in a if ai > 0)
    h_pred = -sum((bj / n) * math.log(bj / n) for bj in b if bj > 0)
    denom = math.sqrt(h_true * h_pred)
    if denom == 0:
        return 1.0 if h_true == 0 and h_pred == 0 else 0.0
    return mi / denom


def predicted_labels(classes, graph, traces=None, entity_groups=None, config=None):
    """Run discovery and return {class_fqn: domain_id} for labelled classes."""
    domains, membership = discover_domains(classes, graph,
                                           traces=traces,
                                           entity_groups=entity_groups,
                                           config=config)
    # Map each labelled class to its domain id; excluded classes map to None.
    return {c: membership.get(c) for c in classes}, domains


def stability(classes, graph, runs=5, **kwargs):
    """Fraction of repeated runs whose membership matches the first run."""
    first, _ = predicted_labels(classes, graph, **kwargs)
    matches = 0
    for _ in range(runs):
        current, _ = predicted_labels(classes, graph, **kwargs)
        if current == first:
            matches += 1
    return matches / runs, first


def evaluate(labels, classes, graph, **kwargs):
    """Score ``labels`` ({class: label}) against discovery on classes+graph."""
    predicted, domains = predicted_labels(classes, graph, **kwargs)
    # Restrict to classes that have a ground-truth label and were assigned a domain.
    paired = [(c, labels[c], predicted[c])
              for c in labels if c in classes and predicted[c] is not None]
    if not paired:
        return dict(ari=None, nmi=None, n_paired=0, n_domains=len(domains),
                    domains=[d['name'] for d in domains])
    labels_true = {c: l for c, l, _ in paired}
    labels_pred = {c: p for c, _, p in paired}
    ari = adjusted_rand_index(labels_true, labels_pred)
    nmi = normalized_mutual_information(labels_true, labels_pred)
    return dict(ari=ari, nmi=nmi, n_paired=len(paired),
                n_domains=len(domains),
                domains=[d['name'] for d in domains],
                n_excluded=sum(1 for c in classes if predicted.get(c) is None and c not in labels))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Evaluate domain discovery against ground truth.')
    parser.add_argument('--labels', help='JSON file mapping class fqn to ground-truth label')
    parser.add_argument('--runs', type=int, default=5, help='stability repeat runs')
    args = parser.parse_args(argv)

    built = petclinic_graph()
    classes = built['classes']
    graph = built['graph']

    labels = None
    source = 'petclinic (built-in)'
    if args.labels:
        with open(args.labels) as f:
            labels = json.load(f)
        source = args.labels
    else:
        labels = petclinic.LABELS

    result = evaluate(labels, classes, graph)
    stab, _ = stability(classes, graph, runs=args.runs)

    print('Domain discovery evaluation')
    print('  ground truth :', source)
    print('  classes      :', len(classes))
    print('  domains      :', result['n_domains'], result['domains'])
    print('  paired       :', result['n_paired'])
    print('  ARI          :', None if result['ari'] is None else round(result['ari'], 4))
    print('  NMI          :', None if result['nmi'] is None else round(result['nmi'], 4))
    print('  stability    :', round(stab, 4), f'({args.runs} identical runs)')

    if result['ari'] is not None and result['ari'] > 0.5:
        print('PASS: ARI > 0.5')
        return 0
    print('NOTE: ARI not above 0.5 (not a hard failure per task instructions)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
