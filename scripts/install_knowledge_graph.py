"""Install a pinned, checksum-verified Neo4j Community distribution locally."""
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
VERSION='5.26.30'
SHA256='b2c2932b16f810adcc54560e90ee35847047d2d52f78cfbfabbae133be8f82cd'
URL=f'https://dist.neo4j.org/neo4j-community-{VERSION}-windows.zip'

def main():
    runtime=ROOT/'.runtime'
    runtime.mkdir(exist_ok=True)
    archive=runtime/f'neo4j-community-{VERSION}-windows.zip'
    if not archive.exists():
        with urllib.request.urlopen(URL,timeout=60) as response,archive.open('wb') as target:
            while chunk:=response.read(1024*1024):target.write(chunk)
    if hashlib.file_digest(archive.open('rb'),'sha256').hexdigest()!=SHA256:
        raise RuntimeError('Distribution checksum mismatch; no files extracted.')
    destination=runtime/f'neo4j-community-{VERSION}'
    if not destination.exists():
        with zipfile.ZipFile(archive) as zipped:
            if any(not (runtime/name).resolve().is_relative_to(destination.resolve()) for name in zipped.namelist()):
                raise RuntimeError('Unexpected archive layout; no files extracted.')
            zipped.extractall(runtime)
    (runtime/'neo4j-distribution.json').write_text(json.dumps(dict(version=VERSION,url=URL,sha256=SHA256)),encoding='utf-8')
    print('Pinned Neo4j distribution verified. Run scripts/knowledge_graph.py setup, then start.')

if __name__=='__main__':main()
