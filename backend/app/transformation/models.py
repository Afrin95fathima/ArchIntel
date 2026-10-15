from sqlalchemy import ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Identity
from app.db.base import Base


class TransformationTask(Identity, Base):
    __tablename__ = 'transformation_tasks'
    __table_args__ = (UniqueConstraint('tenant_id', 'fingerprint'),)
    fingerprint: Mapped[str] = mapped_column(String(64))
    version_id: Mapped[str] = mapped_column(ForeignKey('architecture_versions.id'), index=True)
    assessment_id: Mapped[str] = mapped_column(ForeignKey('modernization_assessments.id'))
    repository_id: Mapped[str] = mapped_column(ForeignKey('security_repositories.id'))
    actor_id: Mapped[str] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(30), default='PLANNED')
    revision: Mapped[int] = mapped_column(default=0)
    document: Mapped[dict] = mapped_column(JSON)
    history: Mapped[list] = mapped_column(JSON, default=list)


class ChangeSet(Identity, Base):
    __tablename__ = 'transformation_changesets'
    task_id: Mapped[str] = mapped_column(ForeignKey('transformation_tasks.id'), index=True)
    actor_id: Mapped[str] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(30), default='PROPOSED')
    fingerprint: Mapped[str] = mapped_column(String(64))
    document: Mapped[dict] = mapped_column(JSON)
    approval: Mapped[dict | None] = mapped_column(JSON)


class BehavioralContract(Identity, Base):
    __tablename__ = 'transformation_contracts'
    task_id: Mapped[str] = mapped_column(ForeignKey('transformation_tasks.id'), index=True)
    actor_id: Mapped[str] = mapped_column(String(36))
    document: Mapped[dict] = mapped_column(JSON)
    review: Mapped[dict | None] = mapped_column(JSON)


class BuildRun(Identity, Base):
    __tablename__ = 'transformation_builds'
    task_id: Mapped[str] = mapped_column(ForeignKey('transformation_tasks.id'), index=True)
    actor_id: Mapped[str] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(30))
    document: Mapped[dict] = mapped_column(JSON)


class DataDiscoveryRun(Identity, Base):
    __tablename__ = 'transformation_data_discovery_runs'
    task_id: Mapped[str] = mapped_column(ForeignKey('transformation_tasks.id'), index=True)
    actor_id: Mapped[str] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(30), default='COMPLETED')
    fingerprint: Mapped[str] = mapped_column(String(64))
    document: Mapped[dict] = mapped_column(JSON)


class DataMigrationPlan(Identity, Base):
    __tablename__ = 'transformation_data_migration_plans'
    task_id: Mapped[str] = mapped_column(ForeignKey('transformation_tasks.id'), index=True)
    discovery_id: Mapped[str] = mapped_column(ForeignKey('transformation_data_discovery_runs.id'), index=True)
    revision: Mapped[int] = mapped_column(default=1)
    state: Mapped[str] = mapped_column(String(30), default='PROPOSED_REVIEW_REQUIRED')
    fingerprint: Mapped[str] = mapped_column(String(64))
    document: Mapped[dict] = mapped_column(JSON)
    review: Mapped[dict | None] = mapped_column(JSON)


class DataMigrationRun(Identity, Base):
    __tablename__ = 'transformation_data_migration_runs'
    task_id: Mapped[str] = mapped_column(ForeignKey('transformation_tasks.id'), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey('transformation_data_migration_plans.id'), index=True)
    actor_id: Mapped[str] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(30), default='QUEUED')
    document: Mapped[dict] = mapped_column(JSON)
