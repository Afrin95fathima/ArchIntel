from sqlalchemy import String, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from app.models import Identity


class ModelProvider(Identity, Base):
    __tablename__ = 'ai_providers'
    name: Mapped[str] = mapped_column(String(120))
    adapter: Mapped[str] = mapped_column(String(30), default='OLLAMA')
    destination: Mapped[str] = mapped_column(String(40), default='LOCAL_MODEL')
    endpoint: Mapped[str] = mapped_column(String(200))
    model: Mapped[str] = mapped_column(String(120))
    model_digest: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(default=True)


class ModelInvocation(Identity, Base):
    __tablename__ = 'ai_invocations'
    principal_id: Mapped[str] = mapped_column(String(36))
    provider_id: Mapped[str] = mapped_column(String(36), default='')
    resource: Mapped[str] = mapped_column(String(120))
    outcome: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(String(80))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
