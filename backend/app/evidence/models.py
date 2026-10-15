"""Authoritative version/evidence records. Neo4j is a rebuildable projection."""
from sqlalchemy import ForeignKey,JSON,String,Text,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from app.models import Identity
from app.db.base import Base

class ArchitectureVersion(Identity,Base):
    __tablename__='architecture_versions'
    __table_args__=(UniqueConstraint('tenant_id','fingerprint'),)
    application_id:Mapped[str]=mapped_column(ForeignKey('applications.id'),index=True)
    analysis_id:Mapped[str]=mapped_column(ForeignKey('analysis_runs.id'))
    parent_id:Mapped[str|None]=mapped_column(ForeignKey('architecture_versions.id'))
    name:Mapped[str]=mapped_column(String(160))
    fingerprint:Mapped[str]=mapped_column(String(64))
    manifest:Mapped[dict]=mapped_column(JSON)
    document:Mapped[dict]=mapped_column(JSON)

class Evidence(Identity,Base):
    __tablename__='architecture_evidence'
    version_id:Mapped[str]=mapped_column(ForeignKey('architecture_versions.id'),index=True)
    kind:Mapped[str]=mapped_column(String(30))
    document:Mapped[dict]=mapped_column(JSON)

class ArchitectureFact(Identity,Base):
    __tablename__='architecture_facts'
    version_id:Mapped[str]=mapped_column(ForeignKey('architecture_versions.id'),index=True)
    classification:Mapped[str]=mapped_column(String(30))
    document:Mapped[dict]=mapped_column(JSON)

class Projection(Identity,Base):
    __tablename__='architecture_projections'
    version_id:Mapped[str]=mapped_column(ForeignKey('architecture_versions.id'),unique=True)
    state:Mapped[str]=mapped_column(String(20),default='PENDING')
    attempts:Mapped[int]=mapped_column(default=0)
    content_hash:Mapped[str]=mapped_column(String(64))
    error_code:Mapped[str|None]=mapped_column(String(60))

class DiscoveryItem(Identity,Base):
    __tablename__='architecture_discovery'
    version_id:Mapped[str]=mapped_column(ForeignKey('architecture_versions.id'),index=True)
    priority:Mapped[int]=mapped_column(default=2)
    state:Mapped[str]=mapped_column(String(20),default='OPEN')
    document:Mapped[dict]=mapped_column(JSON)
    history:Mapped[list]=mapped_column(JSON,default=list)
