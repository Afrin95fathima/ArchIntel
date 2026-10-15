from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from app.models import Identity, now


class Workspace(Base):
    __tablename__ = 'security_workspaces'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    audit_sequence: Mapped[int] = mapped_column(default=0)
    audit_head: Mapped[str] = mapped_column(String(64), default='0' * 64)


class SecurityState(Base):
    __tablename__ = 'security_state'
    id: Mapped[int] = mapped_column(primary_key=True)
    bootstrap_hash: Mapped[str] = mapped_column(String(64))
    initialized: Mapped[bool] = mapped_column(default=False)


class Principal(Identity, Base):
    __tablename__ = 'security_principals'
    username: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[str] = mapped_column(String(20))
    password_hash: Mapped[str | None] = mapped_column(Text)
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(default=True)
    platform_owner: Mapped[bool] = mapped_column(default=False)


class Credential(Base):
    __tablename__ = 'security_credentials'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    principal_id: Mapped[str] = mapped_column(ForeignKey('security_principals.id'), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LoginWindow(Base):
    __tablename__ = 'security_login_windows'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PolicyRevision(Identity, Base):
    __tablename__ = 'security_policy_revisions'
    revision: Mapped[int]
    document: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint('tenant_id', 'revision'),)


class SourceRepository(Identity, Base):
    __tablename__ = 'security_repositories'
    application_id: Mapped[str] = mapped_column(ForeignKey('applications.id'))
    name: Mapped[str] = mapped_column(String(160))
    path: Mapped[str] = mapped_column(Text)
    commit: Mapped[str] = mapped_column(String(40))


class SourceGrant(Identity, Base):
    __tablename__ = 'security_source_grants'
    principal_id: Mapped[str] = mapped_column(ForeignKey('security_principals.id'))
    repository_id: Mapped[str] = mapped_column(ForeignKey('security_repositories.id'))
    allowed_paths: Mapped[list] = mapped_column(JSON)
    protected_paths: Mapped[list] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint('principal_id', 'repository_id'),)


class AuditEvent(Base):
    __tablename__ = 'security_audit_events'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    sequence: Mapped[int]
    previous_hash: Mapped[str] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64))
    event: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint('tenant_id', 'sequence'),)
