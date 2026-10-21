from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from app.models import Identity, now


class AutomationJob(Identity, Base):
    """One exploration or conversion run; `document` holds its steps, progress and result."""
    __tablename__ = 'automation_jobs'
    application_id: Mapped[str] = mapped_column(ForeignKey('applications.id'), index=True)
    analysis_id: Mapped[str | None] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(20), default='QUEUED')
    actor_id: Mapped[str] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    document: Mapped[dict] = mapped_column(JSON, default=dict)
