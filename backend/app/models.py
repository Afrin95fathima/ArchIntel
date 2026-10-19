from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


class Identity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), default='local', index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Project(Identity, Base):
    __tablename__ = 'projects'
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default='')


class Application(Identity, Base):
    __tablename__ = 'applications'
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    name: Mapped[str] = mapped_column(String(160))
    version: Mapped[str] = mapped_column(String(80), default='1.0')
    source_type: Mapped[str] = mapped_column(String(20), default='JAR')


class Artifact(Identity, Base):
    __tablename__ = 'artifacts'
    application_id: Mapped[str] = mapped_column(ForeignKey('applications.id'), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int]
    available: Mapped[bool] = mapped_column(default=True)
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)


class AnalysisRun(Identity, Base):
    __tablename__ = 'analysis_runs'
    application_id: Mapped[str] = mapped_column(ForeignKey('applications.id'), index=True)
    artifact_id: Mapped[str] = mapped_column(ForeignKey('artifacts.id'))
    status: Mapped[str] = mapped_column(String(40), default='QUEUED', index=True)
    limit_details: Mapped[dict | None] = mapped_column(JSON)
    progress: Mapped[int] = mapped_column(default=0)
    stage: Mapped[str] = mapped_column(String(80), default='UPLOAD_RECEIVED')
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    stages: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[dict | None] = mapped_column(JSON)
