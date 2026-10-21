"""The built frontend is served so that an upgrade cannot leave a browser with an index page that names missing files."""
import pytest
from fastapi.testclient import TestClient
from pathlib import Path

from app.main import SpaFiles


def test_hashed_assets_are_cached_for_good_and_the_page_is_always_revalidated(tmp_path):
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets' / 'index-abc123.js').write_text('console.log(1)')
    (tmp_path / 'index.html').write_text('<html></html>')
    from fastapi import FastAPI
    app = FastAPI()
    app.mount('/', SpaFiles(directory=tmp_path, html=True), name='frontend')
    client = TestClient(app)
    asset = client.get('/assets/index-abc123.js')
    page = client.get('/')
    assert asset.status_code == page.status_code == 200
    assert asset.headers['cache-control'] == 'public, max-age=31536000, immutable'
    assert page.headers['cache-control'] == 'no-cache'
    assert client.get('/index.html').headers['cache-control'] == 'no-cache'
