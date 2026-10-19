from scripts.benchmark_scalability import encoded_size, fixture, measure, peak_memory, profile


def test_fixture_generates_balanced_modules_packages_and_reproducible_edges():
    classes, edges = fixture(21, modules=7)
    assert len(classes) == 21
    assert len({row['package_name'].split('.')[1] for row in classes}) == 7
    assert all(sum(row['package_name'].split('.')[1] == f'module{i}' for row in classes) == 3 for i in range(7))
    assert edges == fixture(21, modules=7)[1]
    assert any(edge['source'].split('.')[1] != edge['target'].split('.')[1] for edge in edges)


def test_fixture_rejects_invalid_shape_and_json_size_is_compact():
    try:
        fixture(0, modules=7)
        assert False, 'expected invalid shape'
    except ValueError:
        pass
    assert encoded_size({'nodes': [1, 2], 'label': 'a'}) == len(b'{"nodes":[1,2],"label":"a"}')


def test_measurement_includes_graph_complexity_size_memory_and_profile():
    result = measure(28, repeats=1, modules=7)
    assert result['actual_classes'] == 28
    assert result['modules'] == 7 and result['packages'] >= 7
    assert result['result_json_bytes'] > 0
    assert result['dependency_pairs'] == result['typed_dependency_edges']
    assert isinstance(peak_memory()['units'], str)
    profiled = profile(28, modules=7)
    assert profiled['top_functions']
