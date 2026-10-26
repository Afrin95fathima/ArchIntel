"""Single-process worker with durable stage updates and atomic final snapshots."""
from concurrent.futures import ThreadPoolExecutor
import json
import logging
from pathlib import Path
import time
from uuid import uuid4
from sqlalchemy import select, update
from app.models import AnalysisRun, Artifact, now
from app.services.ingestion import ArtifactError, LimitExceeded, validate_archive, validate_project_zip, remove_job, file_hash
from app.services.scanner import JQAssistantScanner, ScannerError
from app.services.engine import analyze
from app.services.tech_stack import inspect_artifact
from app.insight.facts import extract as extract_bytecode, bounded_for_snapshot
from app.insight.scan import BytecodeScanner, supplement as supplement_edges
from app.insight.generated import exclude as exclude_generated

logger = logging.getLogger('archintel.pipeline')


class AnalysisWorker:
    def __init__(self, sessions, config):
        self.sessions, self.config = sessions, config
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='archintel')
        self.scanner = BytecodeScanner(config) if getattr(config, 'scanner_engine', 'jqassistant') == 'bytecode' else JQAssistantScanner(config)

    def submit(self, analysis_id: str) -> None:
        self.executor.submit(self.run, analysis_id)

    def close(self) -> None:
        self.executor.shutdown(wait=True)

    def recover(self) -> None:
        # Recovery assumes one API/worker process, as does the admission queue.
        pending = []
        with self.sessions.begin() as session:
            runs = session.scalars(select(AnalysisRun).where(
                AnalysisRun.status.in_(['QUEUED', 'RUNNING'])).order_by(AnalysisRun.created_at)).all()
            for run in runs:
                artifact = session.get(Artifact, run.artifact_id)
                if not artifact or not artifact.available or not Path(artifact.path).is_file():
                    run.status, run.stage = 'FAILED', 'RECOVERY_FAILED'
                    run.error_message = 'Recovery requires the original artifact. Upload it again to start a new analysis.'
                    run.completed_at = now()
                    continue
                run.status, run.stage, run.progress = 'QUEUED', 'RECOVERED_AFTER_RESTART', 0
                run.error_message, run.completed_at, run.result = None, None, None
                pending.append(run.id)
        for analysis_id in pending:
            self.submit(analysis_id)

    def run(self, analysis_id: str) -> None:
        # Only the caller that atomically claims QUEUED may execute or clean up.
        with self.sessions.begin() as session:
            claimed = session.execute(update(AnalysisRun).where(
                AnalysisRun.id == analysis_id, AnalysisRun.status == 'QUEUED').values(
                    status='RUNNING', started_at=now(), error_message=None, completed_at=None))
            if claimed.rowcount != 1:
                return
        timings, previous, start, work = [], None, time.monotonic(), None
        job_start=time.monotonic()
        completed = False

        def check_job_budget():
            maximum=self.config.max_job_disk_mb*1024**2
            observed=sum(item.stat().st_size for item in work.rglob('*') if item.is_file()) if work and work.exists() else 0
            if observed>maximum:
                raise LimitExceeded('max_temp_disk_per_job',maximum,observed,'Split the artifact by module or ask your administrator to raise max_job_disk_mb.')

        def stage(name: str, progress: int) -> None:
            nonlocal previous, start
            current = time.monotonic()
            if current-job_start>self.config.scan_timeout_seconds:
                raise LimitExceeded('max_scan_duration',self.config.scan_timeout_seconds,int(current-job_start),'Retry with a smaller artifact or ask your administrator to raise scan_timeout_seconds.')
            if previous:
                timings.append(dict(stage=previous, duration_seconds=round(current-start,3)))
            previous, start = name, current
            with self.sessions.begin() as session:
                run = session.get(AnalysisRun, analysis_id)
                run.status, run.stage, run.progress, run.stages = 'RUNNING', name, progress, list(timings)
                if run.started_at is None:
                    run.started_at = now()
            logger.info(json.dumps(dict(event='analysis_stage', analysis_id=analysis_id, stage=name, progress=progress)))
        try:
            with self.sessions() as session:
                run = session.get(AnalysisRun, analysis_id)
                artifact = session.get(Artifact, run.artifact_id)
                artifact_id, artifact_path = artifact.id, Path(artifact.path)
                metadata = dict(filename=artifact.filename, sha256=artifact.sha256, size=artifact.size, manifest=artifact.manifest)
            # A restart may leave an old scanner/store on disk. Never reuse it.
            work = self.config.data_dir / 'jobs' / (analysis_id + '-' + str(uuid4()))
            work.mkdir(parents=True, exist_ok=False)
            stage('VALIDATING_ARTIFACT', 5)
            if not artifact_path.is_file() or file_hash(artifact_path) != metadata['sha256']:
                raise ArtifactError('Artifact is missing or its checksum changed. Upload the original artifact again.')
            classes_dir = work / 'classes'
            classes_dir.mkdir()
            validator = validate_project_zip if metadata['filename'].lower().endswith('.zip') else validate_archive
            validator(artifact_path, self.config, classes_dir)
            check_job_budget()
            generated = None
            if self.config.exclude_generated_code:
                stage('DETECTING_GENERATED_CODE', 9)
                generated = exclude_generated(classes_dir, work / 'generated')
            stage('SCANNING', 12)
            classes, edges = self.scanner.scan(work, classes_dir, stage)
            if len(classes)>self.config.max_classes:
                raise LimitExceeded('max_classes_per_scan',self.config.max_classes,len(classes),'Split the artifact by module or ask your administrator to raise max_classes.')
            if len(edges)>self.config.max_edges:
                raise LimitExceeded('max_edges_per_scan',self.config.max_edges,len(edges),'Split the artifact by module or ask your administrator to raise max_edges.')
            packages={row.get('package_name') for row in classes if row.get('package_name')}
            if len(packages)>self.config.max_packages_per_scan:
                raise LimitExceeded('max_packages_per_scan',self.config.max_packages_per_scan,len(packages),'Split the artifact by module or ask your administrator to raise max_packages_per_scan.')
            check_job_budget()
            extracted = None
            if self.config.bytecode_facts_enabled:
                stage('BYTECODE_FACTS', 36)
                extracted = extract_bytecode(classes_dir, owned={c['fqn'] for c in classes})
                if self.config.scanner_engine != 'bytecode':
                    edges = supplement_edges(edges, extracted)
            result = analyze(classes, edges, self.config, stage)
            if extracted is not None:
                internal_names = {c['id'] for c in result['classes']}
                result['bytecode'] = bounded_for_snapshot(extracted, internal_names, self.config.bytecode_facts_max_bytes)
                from app.insight.reconcile import reconcile
                reconcile(result)
                from app.insight.source_store import capture as capture_sources
                result['source_store'] = capture_sources(self.config, analysis_id, artifact_path, result)
                if result['bytecode'].get('reductions'):
                    result['limitations'].append('Bytecode facts were reduced to fit the snapshot limit: ' + '; '.join(result['bytecode']['reductions']) + '.')
            result['generated_code'] = generated or dict(status='NOT_CHECKED', class_count=0, note='Generated-code detection is disabled (EXCLUDE_GENERATED_CODE=false).')
            if generated and generated['status'] == 'EXCLUDED':
                counts = ', '.join(f'{name} {count}' for name, count in generated['by_generator'].items())
                result['limitations'].append(f"{generated['class_count']} generated classes ({counts}) were excluded from the analysis; references to them appear as external types.")
            result['tech_inventory'] = inspect_artifact(artifact_path, classes_dir, result)
            from app.insight.lifecycle import evaluate as evaluate_lifecycle, compatibility_summary
            from app.insight.model import InsightModel
            lifecycle_result = evaluate_lifecycle(InsightModel(analysis_id, result), result['tech_inventory'])
            result['tech_inventory']['compatibility'] = compatibility_summary(lifecycle_result)
            result['tech_inventory']['lifecycle_rules'] = lifecycle_result['rules']
            result['artifact'] = metadata
            result['scanner'] = dict(name='jQAssistant', version='2.7.0', graph_storage='isolated Neo4j 5', normalized_results='PostgreSQL' if self.config.database_url.startswith('postgresql') else 'SQLite local mode')
            stage('PERSISTING_RESULTS', 94)
            # A complete snapshot is committed in one transaction, never partial success.
            timings.append(dict(stage=previous, duration_seconds=round(time.monotonic()-start,3)))
            with self.sessions.begin() as session:
                run = session.get(AnalysisRun, analysis_id)
                run.result, run.status, run.stage, run.progress = result, 'COMPLETED', 'COMPLETED', 100
                run.completed_at, run.stages = now(), list(timings)
            completed = True
        except Exception as error:
            message = str(error) if isinstance(error, (ArtifactError, ScannerError, ValueError)) else 'Analysis failed unexpectedly. Check service configuration and retry.'
            rejected=isinstance(error,LimitExceeded)
            logger.error(json.dumps(dict(event='analysis_limit_rejected' if rejected else 'analysis_failed', analysis_id=analysis_id, stage=previous, error_type=type(error).__name__, limit=getattr(error,'limit',None), configured=getattr(error,'configured',None), observed=getattr(error,'observed',None))))
            with self.sessions.begin() as session:
                run = session.get(AnalysisRun, analysis_id)
                run.status, run.error_message, run.completed_at = ('REJECTED_LIMIT_EXCEEDED' if rejected else 'FAILED'), message, now()
                run.limit_details=dict(code='LIMIT_EXCEEDED',limit=error.limit,configured=error.configured,observed=error.observed,next_step=error.advice) if rejected else None
                if previous:
                    timings.append(dict(stage=previous, duration_seconds=round(time.monotonic()-start,3), failed=True))
                run.stages = timings
        finally:
            if work:
                try:
                    remove_job(work, self.config.data_dir / 'jobs')
                except OSError:
                    logger.warning(json.dumps(dict(event='cleanup_pending', analysis_id=analysis_id)))
            # Failed inputs remain available for retry through the existing API.
            if completed and not self.config.retain_artifacts:
                with self.sessions.begin() as session:
                    run = session.get(AnalysisRun, analysis_id)
                    artifact = session.get(Artifact, run.artifact_id)
                    try:
                        path = Path(artifact.path).resolve()
                        if path.is_relative_to((self.config.data_dir / 'uploads').resolve()):
                            path.unlink(missing_ok=True)
                            artifact.available = False
                    except OSError:
                        logger.warning(json.dumps(dict(event='artifact_cleanup_pending', analysis_id=analysis_id)))
