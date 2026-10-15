from types import SimpleNamespace

from app.transformation.extraction import build_plan


def contract(review):
    return SimpleNamespace(review=review)


def test_plan_reports_boundary_and_missing_behavior_and_data_reviews():
    analysis = dict(
        classes=[
            dict(id='shop.orders.OrderService', package_name='shop.orders', domain_id='orders'),
            dict(id='shop.orders.OrderRepository', package_name='shop.orders', domain_id='orders'),
            dict(id='shop.billing.InvoiceService', package_name='shop.billing', domain_id='billing'),
        ],
        domains=[dict(id='orders', name='Orders')],
        edges=[
            dict(source='shop.orders.OrderService', target='shop.orders.OrderRepository', dependency_type='METHOD_CALL'),
            dict(source='shop.orders.OrderService', target='shop.billing.InvoiceService', dependency_type='METHOD_CALL'),
        ],
        cycles=[dict(level='CLASS', members=['shop.orders.OrderService', 'shop.billing.InvoiceService'])],
    )
    plan = build_plan(analysis, 'orders', {
        'src/main/java/shop/orders/OrderService.java': 'a' * 64,
        'src/main/java/shop/orders/OrderRepository.java': 'b' * 64,
        'src/main/java/shop/billing/InvoiceService.java': 'c' * 64,
    }, complete_source_snapshot=True, contracts=[contract({'actor': 'reviewer'})])

    assert plan['state'] == 'PREVIEW_ONLY'
    assert plan['execution_eligible'] is False
    assert plan['target']['source_files'] == [
        'src/main/java/shop/orders/OrderRepository.java',
        'src/main/java/shop/orders/OrderService.java',
    ]
    assert plan['boundary']['outgoing_count'] == 1
    assert 'CYCLE_CROSSES_PROPOSED_EXTRACTION_BOUNDARY' in plan['blockers']
    assert 'DATA_OWNERSHIP_REVIEW_REQUIRED' in plan['blockers']
    assert 'REVIEWED_BEHAVIORAL_CONTRACTS_REQUIRED' not in plan['blockers']
    assert len(plan['fingerprint']) == 64


def test_plan_abstains_on_ambiguous_source_file_mapping_and_incomplete_snapshot():
    analysis = dict(
        classes=[dict(id='shop.orders.OrderService', package_name='shop.orders', domain_id='orders')],
        domains=[dict(id='orders', name='Orders')], edges=[], cycles=[],
    )
    plan = build_plan(analysis, 'orders', {
        'module-a/src/shop/orders/OrderService.java': 'a' * 64,
        'module-b/src/shop/orders/OrderService.java': 'b' * 64,
    }, complete_source_snapshot=False, contracts=[])

    assert plan['target']['unresolved_classes'] == ['shop.orders.OrderService']
    assert 'TARGET_SOURCE_FILES_UNRESOLVED_OR_AMBIGUOUS' in plan['blockers']
    assert 'COMPLETE_SOURCE_SNAPSHOT_REQUIRED' in plan['blockers']
    assert plan['target']['source_files'] == []
