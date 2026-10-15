"""Validate Phase 3 with real PetClinic/OTel in a disposable isolated database.
Reads the existing matching static baseline, but never mutates the user's workspace.
Only the pinned local PetClinic sample is executed. No credentials enter the report.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from uuid import uuid4
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from app.config import Settings
from app.db.session import build_engine
from app.models import Project,Application,Artifact,AnalysisRun,now
from app.runtime.models import RuntimeSession
from app.main import create_app


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def source_snapshot():
    engine=build_engine(Settings())
    try:
        with sessionmaker(engine)() as db:
            return {r.id:digest(r.result) for r in db.scalars(select(AnalysisRun).where(AnalysisRun.status=='COMPLETED'))}
    finally:engine.dispose()


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try:process.wait(timeout=15)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=15)


def wait_ready(client,process,path):
    for _ in range(120):
        if process.poll() is not None:raise RuntimeError('Validation process exited; inspect isolated logs.')
        try:
            if client.get(path).status_code==200:return
        except httpx.HTTPError:pass
        time.sleep(1)
    raise RuntimeError('Validation startup timed out.')


def main():
    for port in (18002,18080):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',port))
    artifact=next((ROOT/'.runtime/petclinic').glob('*/target/spring-petclinic-*.jar'))
    sha=hashlib.sha256(artifact.read_bytes()).hexdigest()
    original=source_snapshot()
    engine=build_engine(Settings())
    with sessionmaker(engine)() as db:
        candidates=list(db.scalars(select(AnalysisRun).join(Artifact,AnalysisRun.artifact_id==Artifact.id).where(Artifact.sha256==sha,AnalysisRun.status=='COMPLETED').order_by(AnalysisRun.created_at.desc())))
        run=next((r for r in candidates if r.result['classes'] and all('methods' in c for c in r.result['classes']) and not any(c['id'].startswith('org.springframework.boot.') for c in r.result['classes'])),None)
        if not run:raise RuntimeError('Run the real PetClinic static validation first; no matching method inventory baseline found.')
        static=copy.deepcopy(run.result)
    engine.dispose()
    data=ROOT/'.data'/('phase3-real-java-'+uuid4().hex);data.mkdir()
    env=dict(os.environ,ARCHINTEL_PHASE3_DATA=str(data))
    log=(data/'api.log').open('wb');petlog=(data/'petclinic.log').open('wb')
    api_process=None;java_process=None
    try:
        def launch_api():return subprocess.Popen([sys.executable,__file__,'--serve'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        api_process=launch_api()
        with httpx.Client(base_url='http://127.0.0.1:18002',timeout=30,headers={'X-ArchIntel-Request':'1'}) as api:
            wait_ready(api,api_process,'/api/v1/health')
            password=secrets.token_urlsafe(24)
            response=api.post('/api/v1/security/bootstrap',json={'username':'phase3-validator','password':password,'bootstrap_key':(data/'security-bootstrap.key').read_text().strip()});response.raise_for_status()
            api.headers['X-CSRF-Token']=response.json()['csrf_token']
            isolated=build_engine(Settings(_env_file=None,database_url='sqlite:///'+(data/'runtime.db').as_posix(),data_dir=data))
            with sessionmaker(isolated)() as db:
                p=Project(name='Isolated Phase 3 validation');db.add(p);db.flush()
                a=Application(name='Spring PetClinic',project_id=p.id);db.add(a);db.flush()
                f=Artifact(application_id=a.id,filename=artifact.name,path=str(artifact),sha256=sha,size=artifact.stat().st_size);db.add(f);db.flush()
                r=AnalysisRun(application_id=a.id,artifact_id=f.id,status='COMPLETED',stage='COMPLETED',progress=100,result=static);db.add(r);db.commit();app_id=a.id;analysis_id=r.id
            isolated.dispose()
            body={'analysis_id':analysis_id,'name':'Phase 3 real Java','mode':'BOUNDARY','binding_mode':'STRICT','include_packages':['org.springframework.samples.petclinic']}
            response=api.post(f'/api/v1/applications/{app_id}/runtime-sessions/plan',json=body);response.raise_for_status();plan=response.json()
            response=api.post(f'/api/v1/applications/{app_id}/runtime-sessions',json=body);response.raise_for_status();created=response.json();sid=created['session']['id'];base='/api/v1/runtime-sessions/'+sid
            assert created['agent']['plan']==plan and plan['selected_method_names']>0
            api.post(base+'/start').raise_for_status()
            java,_=Settings().runtime_paths()
            javaenv=dict(os.environ,**created['agent']['environment'],OTEL_BSP_SCHEDULE_DELAY='500')
            java_process=subprocess.Popen([str(java/'bin/java.exe'),'-Xmx512m','-javaagent:'+str(ROOT/'.runtime/otel/opentelemetry-javaagent.jar'),'-jar',str(artifact),'--server.port=18080','--server.address=127.0.0.1','--spring.docker.compose.enabled=false'],env=javaenv,stdout=petlog,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            with httpx.Client(base_url='http://127.0.0.1:18080',timeout=20) as web:
                wait_ready(web,java_process,'/')
                for path in ['/owners/find','/owners?lastName=','/owners/1']:web.get(path).raise_for_status()
                time.sleep(4)
                response=api.get(base+'/evidence');response.raise_for_status();before=response.json()
                print('Initial observed classes: '+str(before['coverage']['classes']['observed']),flush=True)
                for path in ['/vets.html','/owners/1/pets/new','/owners/1/pets/1/visits/new']:web.get(path).raise_for_status()
                time.sleep(4)
                response=api.get(base+'/evidence');response.raise_for_status();after=response.json()
                assert after['coverage']['classes']['observed']>before['coverage']['classes']['observed']
                assert after['coverage']['methods']['observed']>0
                assert after['quality']['declared_match_spans']>0 and after['quality']['unverified_spans']==0
                assert after['quality']['binding_rejected_spans']==0
                kinds={e['evidence_type'] for e in after['graph']['edges']}
                assert {'STATIC_ONLY','STATIC_AND_DYNAMIC'}<=kinds
            # Freeze only after traffic and exporter have settled; shutdown can emit extra spans.
            stop(java_process);time.sleep(2)
            api.post(base+'/stop').raise_for_status()
            frozen=api.get(base+'/evidence').json();status=api.get(base).json()
            fetched=api.get('/api/v1/analyses/'+analysis_id+'/export').json();fetched.pop('analysis_id',None)
            assert digest(fetched)==digest(static)
            stop(api_process);api_process=launch_api();wait_ready(api,api_process,'/api/v1/health')
            assert api.get(base+'/evidence').json()==frozen
            assert api.get(base+'/agent-config').json()['plan']==plan
            # A closed session must reject even an otherwise valid bearer after restart.
            assert api.post(base+'/v1/traces',json={},headers={'Authorization':'Bearer '+created['token']}).status_code==409
            assert source_snapshot()==original
            report=dict(verified_at=now().isoformat(),isolation='Disposable SQLite workspace; source workspace read-only',application_id=app_id,analysis_id=analysis_id,session_id=sid,
                petclinic_revision=(ROOT/'.runtime/petclinic-version.txt').read_text().strip(),agent_version=(ROOT/'.runtime/otel/version.txt').read_text().strip(),
                artifact_sha256=sha,static_snapshot_sha256=digest(static),static_unchanged=True,source_workspace_unchanged=True,restart_report_unchanged=True,
                trace_count=status['trace_count'],span_count=status['span_count'],plan=plan,initial_coverage=before['coverage'],final_coverage=frozen['coverage'],quality=frozen['quality'],
                runtime_nodes=len(frozen['runtime_graph']['nodes']),runtime_edges=len(frozen['runtime_graph']['edges']),
                evidence_counts={kind:sum(e['evidence_type']==kind for e in frozen['graph']['edges']) for kind in ['STATIC_ONLY','DYNAMIC_ONLY','STATIC_AND_DYNAMIC']},session_status=status['status'])
            (ROOT/'docs/phase3-runtime-validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps({k:report[k] for k in ['span_count','trace_count','static_unchanged','source_workspace_unchanged','restart_report_unchanged','evidence_counts','session_status']}),flush=True)
    finally:
        stop(java_process);stop(api_process);log.close();petlog.close()


if __name__=='__main__':
    if '--serve' in sys.argv:
        import uvicorn
        data=Path(os.environ['ARCHINTEL_PHASE3_DATA']).resolve()
        if data.parent!=ROOT/'.data' or not data.name.startswith('phase3-real-java-'):raise RuntimeError('Invalid isolated validation directory.')
        uvicorn.run(create_app(Settings(_env_file=None,database_url='sqlite:///'+(data/'runtime.db').as_posix(),data_dir=data,runtime_public_url='http://127.0.0.1:18002')),host='127.0.0.1',port=18002)
    else:main()
