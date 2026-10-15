from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from app.models import Identity, now


class RuntimeSession(Identity, Base):
    __tablename__ = 'runtime_sessions'
    application_id: Mapped[str] = mapped_column(ForeignKey('applications.id'), index=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey('analysis_runs.id'), index=True)
    name: Mapped[str] = mapped_column(String(160))
    environment: Mapped[str] = mapped_column(String(80), default='LOCAL')
    status: Mapped[str] = mapped_column(String(30), default='CREATED')
    token_hash: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    span_count: Mapped[int] = mapped_column(default=0)
    trace_count: Mapped[int] = mapped_column(default=0)
    dropped_count: Mapped[int] = mapped_column(default=0)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON)


class RuntimeEvent(Base):
    __tablename__ = 'runtime_events'
    __table_args__ = (UniqueConstraint('session_id', 'trace_id', 'span_id', name='uq_runtime_span'),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey('runtime_sessions.id'), index=True)
    trace_id: Mapped[str] = mapped_column(String(32))
    span_id: Mapped[str] = mapped_column(String(16))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    data: Mapped[dict] = mapped_column(JSON)
