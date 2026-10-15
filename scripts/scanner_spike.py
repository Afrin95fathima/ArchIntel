from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.config import Settings
from app.services.ingestion import validate_archive
from app.services.scanner import JQAssistantScanner
import json
import uuid
import subprocess

original_run = subprocess.run
original_popen = subprocess.Popen
def debug_popen(*args, **kwargs):
    if args and args[0][-1] == 'server':
        kwargs['stdout'] = (ROOT / '.data/scanner-server.log').open('wb')
        kwargs['stderr'] = subprocess.STDOUT
    return original_popen(*args, **kwargs)
subprocess.Popen = debug_popen
def debug_run(*args, **kwargs):
    result = original_run(*args, **kwargs)
    if result.returncode and result.stdout:
        print(result.stdout.decode('utf-8', errors='replace'), flush=True)
    return result
subprocess.run = debug_run

config = Settings()
work = ROOT / '.data' / 'spikes' / str(uuid.uuid4())
classes = work / 'classes'
classes.mkdir(parents=True)
print(validate_archive(ROOT / 'samples/northstar-commerce.jar', config, classes), flush=True)
nodes, edges = JQAssistantScanner(config).scan(work, classes, lambda s,p: print(s,p,flush=True))
(work / 'normalized.json').write_text(json.dumps(dict(classes=nodes, edges=edges), indent=2), encoding='utf-8')
print('RESULT', len(nodes), len(edges), 'saved', work, flush=True)
