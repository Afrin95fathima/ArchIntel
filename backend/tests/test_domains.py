"""Tests for the rewritten candidate-domain discovery algorithm in app.services.domains.

Covers the separately testable pipeline stages and the public contract:
discover_domains(classes, graph) -> (domains, membership).
"""
import importlib
import importlib.util
import networkx as nx
import pytest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

from app.services.domains import (
    DomainDiscoveryConfig,
    EXCLUDED_FRAMEWORK_ID,
    GENERIC,
    build_affinity_graph,
    cluster_consensus,
    discover_domains,
    scope_classes,
)


# --------------------------------------------------------------------------- helpers


def _mk_classes(names_ann):
    """names_ann: iterable of (fqn, annotations) -> classes dict."""
    classes = {}
    for fqn, ann in names_ann:
        classes[fqn] = dict(
            fqn=fqn,
            simple_name=fqn.rsplit('.', 1)[-1],
            package_name=fqn.rpartition('.')[0] or '(default)',
            annotations=list(ann),
        )
    return classes


def _mk_graph(classes, edges):
    g = nx.DiGraph()
    for fqn, cls in classes.items():
        g.add_node(fqn, **cls)
    for s, t, w in edges:
        if s in classes and t in classes:
            g.add_edge(s, t, weight=w)
    return g


def _domain_by_name(domains, name):
    return next(d for d in domains if d['name'] == name)


# --------------------------------------------------------------------------- stage 1: scoping


def test_scope_excludes_framework_loader_and_test_classes():
    classes = _mk_classes([
        ('com.app.Service', []),
        ('org.springframework.boot.loader.Launcher', []),
        ('org.springframework.boot.autoconfigure.Foo', []),
        ('com.app.PaymentServiceTest', []),
        ('com.app.internal.Generated', []),
    ])
    graph = _mk_graph(classes, [])
    scoped = scope_classes(classes, graph)
    assert scoped.excluded_count == 4
    assert 'com.app.Service' in scoped.classes
    assert 'org.springframework.boot.loader.Launcher' in scoped.excluded
    assert 'org.springframework.boot.autoconfigure.Foo' in scoped.excluded
    assert 'com.app.PaymentServiceTest' in scoped.excluded
    assert 'com.app.internal.Generated' in scoped.excluded


def test_scope_excluded_keep_reserved_membership_id():
    classes = _mk_classes([
        ('com.app.Service', []),
        ('org.springframework.boot.loader.Launcher', []),
    ])
    graph = _mk_graph(classes, [('org.springframework.boot.loader.Launcher', 'com.app.Service', 1)])
    domains, membership = discover_domains(classes, graph)
    assert membership['org.springframework.boot.loader.Launcher'] == EXCLUDED_FRAMEWORK_ID
    assert EXCLUDED_FRAMEWORK_ID not in {d['id'] for d in domains}
    assert all(EXCLUDED_FRAMEWORK_ID not in d['classes'] for d in domains)


def test_scope_detects_spring_boot_application_root():
    classes = _mk_classes([
        ('com.app.Application', ['org.springframework.boot.autoconfigure.SpringBootApplication']),
        ('com.app.payment.PaymentService', []),
        ('com.app.vet.VetService', []),
    ])
    graph = _mk_graph(classes, [])
    scoped = scope_classes(classes, graph)
    assert scoped.app_root == 'com.app'


def test_scope_falls_back_to_longest_common_prefix():
    classes = _mk_classes([
        ('com.app.payment.PaymentService', []),
        ('com.app.vet.VetService', []),
    ])
    graph = _mk_graph(classes, [])
    scoped = scope_classes(classes, graph)
    assert scoped.app_root == 'com.app'


def test_scope_inner_classes_fold_onto_outer():
    classes = _mk_classes([
        ('com.app.Outer', []),
        ('com.app.Outer$Inner', []),
        ('com.app.Outer$Inner$Nested', []),
        ('com.app.Other', []),
    ])
    graph = _mk_graph(classes, [
        ('com.app.Outer$Inner', 'com.app.Other', 2),
        ('com.app.Outer', 'com.app.Other', 1),
    ])
    scoped = scope_classes(classes, graph)
    assert 'com.app.Outer$Inner' not in scoped.classes
    assert 'com.app.Outer$Inner$Nested' not in scoped.classes
    assert 'com.app.Outer' in scoped.classes
    # self-loops dropped, edges aggregated onto outer, weight summed (1 + 2)
    assert scoped.graph['com.app.Outer']['com.app.Other']['weight'] == 3


# --------------------------------------------------------------------------- stage 2: affinity graph bidirectional sum fix


def test_build_affinity_sums_bidirectional_weights():
    classes = _mk_classes([
        ('com.app.A', []),
        ('net.other.B', []),
    ])
    graph = _mk_graph(classes, [
        ('com.app.A', 'net.other.B', 3),
        ('net.other.B', 'com.app.A', 5),
    ])
    affinity = build_affinity_graph(classes, graph)
    # undirected edge weight must be the SUM (8), damped by in_degree(target)=1 -> /log2(3)
    expected = (3 + 5) / __import__('math').log2(3)
    assert abs(affinity['com.app.A']['net.other.B']['weight'] - expected) < 1e-9


def test_build_affinity_package_prior_applies():
    classes = _mk_classes([
        ('com.app.owner.Owner', []),
        ('com.app.owner.Pet', []),
        ('com.other.vet.Vet', []),
    ])
    graph = _mk_graph(classes, [])
    affinity = build_affinity_graph(classes, graph)
    # same package +0.3
    assert abs(affinity['com.app.owner.Owner']['com.app.owner.Pet']['weight'] - 0.3) < 1e-9
    # different parent package -> no prior edge
    assert not affinity.has_edge('com.app.owner.Owner', 'com.other.vet.Vet')


# --------------------------------------------------------------------------- public contract / determinism


def test_discover_domains_returns_all_required_keys():
    classes = _mk_classes([
        ('com.app.payment.PaymentService', []),
        ('com.app.payment.PaymentRepository', ['org.springframework.stereotype.Repository']),
        ('com.app.payment.PaymentEntity', ['jakarta.persistence.Entity']),
        ('com.app.vet.VetService', []),
    ])
    graph = _mk_graph(classes, [
        ('com.app.payment.PaymentService', 'com.app.payment.PaymentRepository', 1),
        ('com.app.payment.PaymentRepository', 'com.app.payment.PaymentEntity', 1),
        ('com.app.vet.VetService', 'com.app.vet.VetService', 1),
    ])
    domains, membership = discover_domains(classes, graph)
    assert domains
    for d in domains:
        for key in ('id', 'name', 'domain_source', 'confidence', 'class_count',
                    'package_count', 'classes', 'packages', 'evidence', 'confidence_note'):
            assert key in d, f'missing key {key}'
        assert d['domain_source'] == 'AUTO'
        assert 'Heuristic confidence' in d['confidence_note']
    # every class is a member of exactly one domain
    assert sorted(m for d in domains for m in d['classes']) == sorted(classes)


def test_discover_domains_is_deterministic():
    classes = _mk_classes([
        ('com.app.payment.PaymentService', []),
        ('com.app.payment.PaymentRepository', ['org.springframework.stereotype.Repository']),
        ('com.app.payment.PaymentEntity', ['jakarta.persistence.Entity']),
        ('com.app.vet.VetService', []),
        ('com.app.vet.VetRepository', ['org.springframework.stereotype.Repository']),
    ])
    graph = _mk_graph(classes, [
        ('com.app.payment.PaymentService', 'com.app.payment.PaymentRepository', 1),
        ('com.app.payment.PaymentRepository', 'com.app.payment.PaymentEntity', 1),
        ('com.app.vet.VetService', 'com.app.vet.VetRepository', 1),
        ('com.app.vet.VetRepository', 'com.app.vet.VetService', 1),
    ])
    d1, m1 = discover_domains(classes, graph)
    d2, m2 = discover_domains(classes, graph)
    assert [d['id'] for d in d1] == [d['id'] for d in d2]
    assert m1 == m2


def test_discover_domains_accepts_optional_kwargs():
    classes = _mk_classes([('com.app.Service', [])])
    graph = _mk_graph(classes, [])
    discover_domains(classes, graph)
    discover_domains(classes, graph, traces=[], entity_groups=[], config=DomainDiscoveryConfig())


# --------------------------------------------------------------------------- clustering / fallback


def test_cluster_consensus_deterministic():
    classes = _mk_classes([(f'com.app.C{i}', []) for i in range(12)])
    graph = _mk_graph(classes, [(f'com.app.C{i}', f'com.app.C{(i + 1) % 12}', 1) for i in range(12)])
    affinity = build_affinity_graph(classes, graph)
    c1 = cluster_consensus(affinity)
    c2 = cluster_consensus(affinity)
    assert c1.partition == c2.partition
    assert c1.communities == c2.communities
    assert not c1.fallback


def test_cluster_consensus_louvain_fallback(monkeypatch):
    import app.services.domains as dom
    monkeypatch.setattr(dom, '_LEIDEN_AVAILABLE', False)
    classes = _mk_classes([(f'com.app.C{i}', []) for i in range(8)])
    graph = _mk_graph(classes, [(f'com.app.C{i}', f'com.app.C{(i + 1) % 8}', 1) for i in range(8)])
    affinity = build_affinity_graph(classes, graph)
    result = cluster_consensus(affinity)
    assert result.fallback is True
    assert result.partition


# --------------------------------------------------------------------------- post-processing: min-size merging


def test_postprocess_merges_small_communities():
    # Two tightly coupled pairs + one singleton attached to neither strongly;
    # min_domain_size=3 forces the small communities to merge.
    classes = _mk_classes([(f'com.app.A{i}', []) for i in range(4)])
    graph = _mk_graph(classes, [
        ('com.app.A0', 'com.app.A1', 10),
        ('com.app.A1', 'com.app.A0', 10),
        ('com.app.A2', 'com.app.A3', 10),
        ('com.app.A3', 'com.app.A2', 10),
    ])
    affinity = build_affinity_graph(classes, graph)
    config = DomainDiscoveryConfig(min_domain_size=3)
    from app.services.domains import cluster_consensus, postprocess
    cluster = cluster_consensus(affinity, config)
    member_cid, communities, _ = postprocess(cluster.partition, affinity, graph, config)
    sizes = sorted(len(m) for m in communities.values())
    assert all(s >= 3 for s in sizes), sizes


# --------------------------------------------------------------------------- PetClinic fixture


def _load_petclinic():
    path = BACKEND / 'tests' / 'fixtures' / 'petclinic.py'
    spec = importlib.util.spec_from_file_location('petclinic_fixture_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _petclinic_graph():
    petclinic = _load_petclinic()
    classes, edges, _ = petclinic.build()
    from app.services.graph import build_graphs
    built = build_graphs(list(classes.values()), edges, [])
    return classes, built['graph'], petclinic.LABELS


def test_petclinic_excludes_loader_and_does_not_reproduce_old_two_domain_output():
    classes, graph, _ = _petclinic_graph()
    domains, membership = discover_domains(classes, graph)
    loader = [f for f in classes if f.startswith('org.springframework.boot.loader')]
    assert loader, 'fixture should contain loader classes'
    excluded = [f for f, m in membership.items() if m == EXCLUDED_FRAMEWORK_ID]
    assert set(loader) <= set(excluded)
    assert all(membership[f] == EXCLUDED_FRAMEWORK_ID for f in loader)
    assert all(EXCLUDED_FRAMEWORK_ID not in d['classes'] for d in domains)
    # The old behaviour produced exactly 2 domains ('Boot' 98 classes, 'Samples' 25).
    assert len(domains) != 2
    assert sum(d['class_count'] for d in domains) == len(classes) - len(excluded)


def test_petclinic_recovers_ground_truth_labels():
    classes, graph, labels = _petclinic_graph()
    domains, membership = discover_domains(classes, graph)
    # Map each labelled class to its domain id; loader classes carry no label.
    labelled = {c: lab for c, lab in labels.items() if c in membership}
    by_domain = {}
    for c, lab in labelled.items():
        by_domain.setdefault(membership[c], set()).add(lab)
    # No predicted domain may mix ground-truth labels (purity).
    mixed = [d for d in by_domain.values() if len(d) > 1]
    assert not mixed, f'labels mixed across a domain boundary: {mixed}'
    # Each ground-truth label should be captured by at least one domain.
    captured = {lab for labs in by_domain.values() for lab in labs}
    assert captured == set(labels.values()), captured
    assert len(domains) >= 3
