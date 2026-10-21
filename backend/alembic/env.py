from alembic import context
from app.config import Settings
from app.db.session import build_engine
from app.db.base import Base
from app import models
from app.runtime import models as runtime_models
from app.access import models as security_models
from app.ai import models as ai_models
from app.evidence import models as evidence_models
from app.modernization import models as modernization_models
from app.transformation import models as transformation_models
from app.insight import models as insight_models
from app.automation import models as automation_models

engine = context.config.attributes.get('engine') or build_engine(Settings())
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
