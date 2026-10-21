from contextlib import asynccontextmanager
import asyncio
import contextlib
from pathlib import Path
import logging
from alembic.config import Config
from alembic import command
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from app.config import Settings, ROOT
from app.db.session import build_engine
from app.services.pipeline import AnalysisWorker
from app.api import router
from app.runtime.routes import router as runtime_router
from app.security import browser_boundary
from app.access.middleware import access_boundary
from app.access.routes import router as security_router
from app.access.core import initialize
from app.ai.routes import router as ai_router
from app.evidence.routes import router as evidence_router
from app.modernization.routes import router as modernization_router
from app.transformation.routes import router as transformation_router
from app.system.routes import router as system_router
from app.insight.routes import router as insight_router, glossary_router as insight_glossary_router

logging.basicConfig(level=logging.INFO, format='%(message)s')



class SpaFiles(StaticFiles):
    """Hashed build assets never change, so they are cached for good; the page that names them is always revalidated.

    Without this a browser may keep an old index.html after an upgrade and request asset files that no longer exist.
    """
    def file_response(self, full_path, stat_result, scope, status_code=200):
        response = super().file_response(full_path, stat_result, scope, status_code)
        immutable = '/assets/' in str(full_path).replace('\\', '/')
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable' if immutable else 'no-cache'
        return response

def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = build_engine(config)
        migration = Config(str(ROOT / 'backend/alembic.ini'))
        migration.attributes['engine'] = engine
        command.upgrade(migration, 'head')
        sessions = sessionmaker(engine, expire_on_commit=False)
        worker = AnalysisWorker(sessions, config)
        app.state.engine, app.state.sessions, app.state.worker = engine, sessions, worker
        initialize(sessions, config)
        from app.transformation.service import recover as recover_transformations
        recover_transformations(sessions)
        worker.recover()
        from app.services.runtime.session_service import recover
        with sessions() as db: recover(db)
        async def runtime_retention():
            from app.services.runtime.session_service import LOCK, purge
            def sweep():
                with LOCK, sessions() as db:
                    purge(db, config)
            while True:
                try:
                    await asyncio.to_thread(sweep)
                except Exception:
                    logging.getLogger('archintel.runtime').warning('Runtime retention sweep failed; retrying in 60 seconds.')
                await asyncio.sleep(60)
        retention_task = asyncio.create_task(runtime_retention())
        async def graph_projection():
            from app.evidence.projection import sweep
            from app.evidence.service import LOCK
            def project_pending():
                with LOCK: sweep(sessions,config)
            while True:
                if config.knowledge_graph_enabled:
                    try: await asyncio.to_thread(project_pending)
                    except Exception: logging.getLogger('archintel.graph').warning('Projection sweep failed; canonical evidence retained.')
                await asyncio.sleep(30)
        projection_task=asyncio.create_task(graph_projection())
        try:
            yield
        finally:
            projection_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await projection_task
            retention_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await retention_task
            worker.close()
            engine.dispose()

    app = FastAPI(title='ArchIntel',version='0.2.0',lifespan=lifespan)
    app.state.config = config
    app.add_middleware(CORSMiddleware, allow_origins=config.cors_origins,
        allow_methods=['GET','POST'], allow_headers=['Content-Type', 'X-CSRF-Token', 'X-ArchIntel-Request'], allow_credentials=True)
    app.middleware('http')(access_boundary)
    app.middleware('http')(browser_boundary)

    @app.middleware('http')
    async def upload_limit(request: Request, call_next):
        if request.url.path.endswith('/artifact') and request.method == 'POST':
            length = request.headers.get('content-length')
            if not length:
                return JSONResponse({'detail':'Content-Length required for artifact uploads.'},status_code=411)
            try:
                too_large = int(length) > (config.max_upload_mb * 1024**2 + 65536)
            except ValueError:
                return JSONResponse({'detail':'Invalid Content-Length.'},status_code=400)
            if too_large:
                return JSONResponse({'detail':{'code':'LIMIT_EXCEEDED','limit':'max_upload_size_compressed','configured':config.max_upload_mb*1024**2,'observed':int(length)-65536,'next_step':'Split the artifact by module or ask your administrator to raise max_upload_mb.'}},status_code=413)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        return response

    @app.get('/api/v1/health', response_model=dict)
    def health():
        return {'status':'ok','service':'archintel-api','version':'0.2.0'}

    @app.get('/api/v1/ready', response_model=dict)
    def ready(request: Request, response: Response):
        dependencies = {}
        try:
            with request.app.state.engine.connect() as connection:
                connection.execute(text('SELECT 1'))
            dependencies['database'] = 'ok'
        except Exception:
            dependencies['database'] = 'unavailable'
        dependencies['scanner'] = 'ok' if request.app.state.worker.scanner.available() else 'unavailable'
        available = all(v=='ok' for v in dependencies.values())
        response.status_code = 200 if available else 503
        return dict(status='ready' if available else 'not_ready', dependencies=dependencies,
            database='PostgreSQL' if config.database_url.startswith('postgresql') else 'SQLite local mode',
            graph='Isolated Neo4j per analysis', assistant='Local evidence explanations',
            max_upload_mb=config.max_upload_mb, prototype=True)

    @app.get('/api/v1/analysis/capabilities', response_model=dict)
    def capabilities():
        return dict(status='AVAILABLE', scanner='jQAssistant', formats=['JAR','WAR','Spring Boot application classes'],
            features=['graphs','cycles','metrics','domains','issues','modernization','evidence_assistant'])

    app.include_router(router)
    app.include_router(insight_router)
    app.include_router(insight_glossary_router)
    app.include_router(runtime_router)
    app.include_router(security_router)
    app.include_router(ai_router)
    app.include_router(evidence_router)
    app.include_router(modernization_router)
    app.include_router(transformation_router)
    app.include_router(system_router)
    frontend = ROOT / 'frontend/dist'
    if frontend.exists():
        app.mount('/', SpaFiles(directory=frontend,html=True),name='frontend')
    # Outermost host validation prevents a DNS-rebinding host from making an
    # attacker origin appear same-origin to browser_boundary.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.allowed_hosts)
    return app
