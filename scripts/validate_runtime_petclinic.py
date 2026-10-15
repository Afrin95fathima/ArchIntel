"""Real pinned PetClinic + Java agent validation. Executes only the downloaded trusted sample."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4
import httpx
from api_auth import management_headers

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.config import Settings
from app.db.session import build_engine
from app.models import Project,Application,Artifact,AnalysisRun,now
from app.services.scanner import JQAssistantScanner
from app.services.ingestion import validate_archive
from app.services.engine import analyze


def main():
    headers=management_headers()
    # This operator utility seeds its historic fixture directly in the local DB.
    # Validate its account before any scan, DB mutation or Java process starts.
    with httpx.Client(base_url='http://127.0.0.1:8000',headers=headers,timeout=15) as check:
        response=check.get('/api/v1/security/me');response.raise_for_status()
        identity=response.json()
        if identity['tenant_id']!='local' or not {'ANALYSIS_READ','ANALYSIS_WRITE','RUNTIME_READ','RUNTIME_WRITE'} <= set(identity['permissions']):
            raise SystemExit('PetClinic operator validation requires a local-workspace service identity with analysis/runtime read and write permissions.')
    settings=Settings()
    artifact=next((ROOT/'.runtime/petclinic').glob('*/target/spring-petclinic-*.jar'))
    digest=hashlib.sha256(artifact.read_bytes()).hexdigest()
    # PetClinic owns org.springframework.samples; the default framework prefix would exclude it.
    scan_settings=settings.model_copy(update={'external_prefixes':[p for p in settings.external_prefixes if p!='org.springframework.']+['org.springframework.boot.']})
    engine=build_engine(settings); sessions=sessionmaker(engine,expire_on_commit=False)
    with sessions() as db:
        previous=db.scalar(select(Artifact).where(Artifact.sha256==digest,Artifact.filename=='petclinic-runtime-validation.jar').order_by(Artifact.created_at.desc()))
        run=db.scalar(select(AnalysisRun).where(AnalysisRun.artifact_id==previous.id,AnalysisRun.status=='COMPLETED')) if previous else None
        if run and not any(c['id'].startswith('org.springframework.boot.') for c in run.result['classes']):
            result=run.result;app_id=run.application_id;analysis_id=run.id
        else:
            work=ROOT/'.data'/('petclinic-scan-'+str(uuid4()));classes_dir=work/'classes';classes_dir.mkdir(parents=True)
            manifest=validate_archive(artifact,scan_settings,classes_dir)
            print('Scanning real PetClinic bytecode...',flush=True)
            classes,edges=JQAssistantScanner(scan_settings).scan(work,classes_dir,lambda stage,*_:print(stage,flush=True))
            result=analyze(classes,edges,scan_settings)
            result['artifact']=dict(filename=artifact.name,sha256=digest,size=artifact.stat().st_size,manifest=manifest)
            result['scanner']=dict(name='jQAssistant',version='2.7.0',graph_storage='Isolated Neo4j',normalized_results='PostgreSQL')
            p=Project(name='PetClinic runtime validation',description='Pinned open-source sample; real static and OTel evidence.')
            db.add(p);db.flush();app=Application(project_id=p.id,name='Spring PetClinic',version='3.5.0');db.add(app);db.flush()
            stored=Artifact(application_id=app.id,filename='petclinic-runtime-validation.jar',path=str(artifact),sha256=digest,size=artifact.stat().st_size,available=False,manifest=manifest)
            db.add(stored);db.flush();run=AnalysisRun(application_id=app.id,artifact_id=stored.id,status='COMPLETED',progress=100,stage='COMPLETED',result=result,started_at=now(),completed_at=now())
            db.add(run);db.commit();app_id,analysis_id=app.id,run.id
    original=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
    with httpx.Client(base_url='http://127.0.0.1:8000',timeout=60,headers=headers) as api:
        response=api.post(f'/api/v1/applications/{app_id}/runtime-sessions',json={'analysis_id':analysis_id,'name':'PetClinic real Java agent','environment':'LOCAL','mode':'BOUNDARY','include_packages':['org.springframework.samples.petclinic.']})
        response.raise_for_status();created=response.json();sid=created['session']['id'];base='/api/v1/runtime-sessions/'+sid
        api.post(base+'/start').raise_for_status()
        env=dict(os.environ,**created['agent']['environment'],OTEL_BSP_SCHEDULE_DELAY='1000')
        java,_=settings.runtime_paths()
        log=(ROOT/'.data/petclinic-runtime.log').open('wb')
        process=subprocess.Popen([str(java/'bin/java.exe'),'-Xmx512m','-javaagent:'+str(ROOT/'.runtime/otel/opentelemetry-javaagent.jar'),'-jar',str(artifact),'--server.port=18080','--server.address=127.0.0.1','--spring.docker.compose.enabled=false'],env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            with httpx.Client(base_url='http://127.0.0.1:18080',timeout=15) as web:
                for _ in range(120):
                    if process.poll() is not None: raise RuntimeError('PetClinic exited; inspect .data/petclinic-runtime.log')
                    try:
                        if web.get('/').status_code==200: break
                    except httpx.HTTPError: pass
                    time.sleep(1)
                else: raise RuntimeError('PetClinic startup timeout')
                print('PetClinic responding; exercising owner flows.',flush=True)
                for path in ['/owners/find','/owners?lastName=','/owners/1']:
                    web.get(path).raise_for_status()
                time.sleep(5)
                before=api.get(base+'/evidence');before.raise_for_status();before=before.json()
                print('Initial coverage: '+json.dumps(before['coverage']['classes']),flush=True)
                for path in ['/vets.html','/owners/1/pets/new','/owners/1/pets/1/visits/new']:
                    web.get(path).raise_for_status()
                time.sleep(5)
                after=api.get(base+'/evidence');after.raise_for_status();after=after.json()
                status=api.get(base).json()
                assert status['span_count']>0 and status['trace_count']>0
                assert any(m['state']=='EXACT' for m in after['mappings'])
                assert any(e['evidence_type']=='STATIC_ONLY' for e in after['graph']['edges'])
                assert any(e['evidence_type']=='STATIC_AND_DYNAMIC' for e in after['graph']['edges'])
                assert after['coverage']['classes']['observed']>before['coverage']['classes']['observed']
                assert after['coverage']['classes']['percentage']<100
                api.post(base+'/stop').raise_for_status()
                frozen=api.get(base+'/evidence').json()
                assert frozen==after
                static_after=api.get('/api/v1/analyses/'+analysis_id+'/export').json();static_after.pop('analysis_id',None)
                assert hashlib.sha256(json.dumps(static_after,sort_keys=True).encode()).hexdigest()==original
                report=dict(verified_at=now().isoformat(),application_id=app_id,analysis_id=analysis_id,session_id=sid,
                    petclinic_revision=(ROOT/'.runtime/petclinic-version.txt').read_text().strip(),agent_version=(ROOT/'.runtime/otel/version.txt').read_text().strip(),
                    artifact_sha256=digest,static_snapshot_sha256=original,static_unchanged=True,trace_count=status['trace_count'],span_count=status['span_count'],
                    initial_coverage=before['coverage'],final_coverage=after['coverage'],runtime_nodes=len(after['runtime_graph']['nodes']),runtime_edges=len(after['runtime_graph']['edges']),
                    evidence_counts={kind:sum(e['evidence_type']==kind for e in after['graph']['edges']) for kind in ['STATIC_ONLY','DYNAMIC_ONLY','STATIC_AND_DYNAMIC']},session_status='COMPLETED')
                (ROOT/'docs/runtime-validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
                print(json.dumps({k:v for k,v in report.items() if k not in ('initial_coverage','final_coverage')},indent=2),flush=True)
        finally:
            process.terminate()
            try: process.wait(timeout=15)
            except subprocess.TimeoutExpired: process.kill();process.wait()
            log.close()
    engine.dispose()


if __name__=='__main__': main()
