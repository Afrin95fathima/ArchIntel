"""Isolated local server used only by the Phase 1 browser test configuration."""
import os
import sys
from pathlib import Path
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from app.config import Settings
from app.main import create_app

if __name__ == '__main__':
    data = Path(os.environ['ARCHINTEL_BROWSER_DATA']).resolve()
    if not data.is_relative_to(ROOT/'.data') or not data.name.startswith('browser-validation-'):
        raise RuntimeError('Browser tests require their own workspace data directory.')
    data.mkdir(parents=True, exist_ok=True)
    settings=Settings(_env_file=None,database_url='sqlite:///'+(data/'browser.db').as_posix(),data_dir=data,knowledge_graph_enabled=os.environ.get('ARCHINTEL_RUN_GRAPH_TESTS')=='1',knowledge_graph_password_file=ROOT/'.data/knowledge-graph/password.key')
    uvicorn.run(create_app(settings), host='127.0.0.1', port=18001)
