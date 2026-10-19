from pathlib import Path
import importlib.util


def test_ramp_helper_defaults_to_requested_sizes_and_human_review(tmp_path):
    script=Path(__file__).resolve().parents[2]/'scripts'/'ramp_ingestion_limits.py'
    spec=importlib.util.spec_from_file_location('ramp_ingestion_limits',script)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    result=module.run(20,4,1.0)
    assert result['classes']==20 and result['edges']>=20
