"""Authenticated local Neo4j lifecycle, separate from disposable scan stores."""
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HOME=ROOT/'.runtime/neo4j-community-5.26.30'
DATA=ROOT/'.data/knowledge-graph'
JAVA=next((ROOT/'.runtime/java').glob('*/bin/java.exe'))

def environment():
    return dict(os.environ,JAVA_HOME=str(JAVA.parent.parent),NEO4J_HOME=str(HOME),NEO4J_CONF=str(DATA/'conf'))

def setup():
    if not HOME.exists():
        raise RuntimeError('Install the checksum-verified Neo4j Community 5.26.30 Windows distribution under .runtime first.')
    (DATA/'conf').mkdir(parents=True,exist_ok=True)
    key=DATA/'password.key'
    if not key.exists():
        descriptor=os.open(key,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(descriptor,'w') as target:target.write(secrets.token_urlsafe(36))
    configuration='\n'.join([
        'server.default_listen_address=127.0.0.1','server.default_advertised_address=127.0.0.1',
        'server.bolt.listen_address=127.0.0.1:17687','server.bolt.advertised_address=127.0.0.1:17687',
        'server.http.enabled=false','server.https.enabled=false',
        'server.memory.heap.initial_size=128m','server.memory.heap.max_size=512m',
        'server.memory.pagecache.size=128m','dbms.usage_report.enabled=false','db.transaction.timeout=30s',
        'server.directories.data='+(DATA/'data').as_posix(),
        'server.directories.logs='+(DATA/'logs').as_posix(),
        'server.directories.run='+(DATA/'run').as_posix()])+'\n'
    (DATA/'conf/neo4j.conf').write_text(configuration,encoding='utf-8')
    if not (DATA/'data/dbms/auth.ini').exists() and not (DATA/'data/databases/system').exists():
        result=subprocess.run([str(JAVA),'-cp',str(HOME/'lib/*'),'org.neo4j.cli.AdminTool',
                               'dbms','set-initial-password',key.read_text().strip()],
                              env=environment(),capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise RuntimeError('Neo4j credential initialization failed; credentials were not printed.')
    print('Persistent graph configured with authentication on 127.0.0.1:17687.')

def check():
    from neo4j import GraphDatabase
    with GraphDatabase.driver('bolt://127.0.0.1:17687',auth=('neo4j',(DATA/'password.key').read_text().strip()),
                              connection_timeout=2,connection_acquisition_timeout=3) as driver:
        driver.verify_connectivity()

def start():
    try:check();print('Persistent graph ready.');return
    except Exception:pass
    if not (DATA/'conf/neo4j.conf').exists():setup()
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1',17687))==0:
            raise RuntimeError('Port 17687 is occupied by an unexpected or inaccessible server.')
    with (DATA/'launcher.log').open('ab') as log:
        process=subprocess.Popen([str(JAVA),'-Xms128m','-Xmx512m','-cp',str(HOME/'lib/*'),
            'org.neo4j.server.CommunityEntryPoint','--home-dir='+str(HOME),'--config-dir='+str(DATA/'conf')],
            env=environment(),stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    (DATA/'java.pid').write_text(str(process.pid))
    for _ in range(60):
        if process.poll() is not None:raise RuntimeError('Neo4j exited; inspect .data/knowledge-graph/launcher.log.')
        try:check();print('Persistent graph ready.');return
        except Exception:time.sleep(1)
    raise RuntimeError('Neo4j startup timed out; inspect its local log.')

if __name__=='__main__':
    action=sys.argv[1] if len(sys.argv)>1 else 'check'
    if action=='setup':setup()
    elif action=='start':start()
    elif action=='check':check();print('Persistent graph connection verified.')
    else:raise SystemExit('Use setup, start or check.')
