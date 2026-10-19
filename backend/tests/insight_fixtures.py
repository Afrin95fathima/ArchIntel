"""Analysis snapshots built from the committed, compiled fixture classes (no JDK needed)."""
from functools import lru_cache
import io
from pathlib import Path
import zipfile
from app.config import Settings
from app.services.engine import analyze
from app.insight.facts import extract, bounded_for_snapshot
from app.insight.scan import scanner_rows
from app.insight.reconcile import reconcile
from app.insight.model import InsightModel

CLASSES = Path(__file__).resolve().parent / 'fixtures' / 'classes'
PETCLINIC = 'org.springframework.samples.petclinic'


@lru_cache(maxsize=4)
def snapshot(name: str = 'petclinic') -> dict:
    extracted = extract(CLASSES / name)
    classes, edges = scanner_rows(extracted)
    result = analyze(classes, edges, Settings(_env_file=None))
    internal = {c['id'] for c in result['classes']}
    result['bytecode'] = bounded_for_snapshot(extracted, internal, 48 * 1024 * 1024)
    reconcile(result)
    result['source_store'] = dict(status='NO_SOURCE_IN_ARTIFACT', index={})
    return result


def model(name: str = 'petclinic', runtime=None) -> InsightModel:
    return InsightModel('fixture-' + name, snapshot(name), runtime)


def jar(name: str = 'petclinic') -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        for path in sorted((CLASSES / name).rglob('*.class')):
            archive.write(path, path.relative_to(CLASSES / name).as_posix())
    return data.getvalue()
