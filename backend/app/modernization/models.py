from sqlalchemy import ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Identity
from app.db.base import Base


class Assessment(Identity, Base):
    __tablename__ = 'modernization_assessments'
    __table_args__ = (UniqueConstraint('tenant_id', 'fingerprint'),)
    version_id: Mapped[str] = mapped_column(ForeignKey('architecture_versions.id'), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(String(36))
    document: Mapped[dict] = mapped_column(JSON)
    projection_state: Mapped[str] = mapped_column(String(20), default='PENDING')
    projection_attempts: Mapped[int] = mapped_column(default=0)
    projection_error: Mapped[str | None] = mapped_column(String(60))


class PlanReview(Identity, Base):
    __tablename__ = 'modernization_reviews'
    __table_args__ = (UniqueConstraint('assessment_id', 'revision'),)
    assessment_id: Mapped[str] = mapped_column(ForeignKey('modernization_assessments.id'), index=True)
    revision: Mapped[int] = mapped_column()
    actor_id: Mapped[str] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(30))
    note: Mapped[str] = mapped_column(String(2000))

