from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis_id: str
    name: str = Field(min_length=1, max_length=160, pattern=r'\S')
    environment: str = Field(default='LOCAL', min_length=1, max_length=80)
    mode: Literal['BOUNDARY','STANDARD','DEEP'] = 'BOUNDARY'
    include_packages: list[str] = Field(default_factory=list, max_length=30)
    exclude_packages: list[str] = Field(default_factory=list, max_length=30)
    binding_mode: Literal['COMPATIBLE','STRICT'] = 'COMPATIBLE'
    service_name: str | None = Field(default=None, min_length=1, max_length=120, pattern=r'^[A-Za-z0-9_.-]+$')
    # Classes an earlier coverage pass already traced; the plan spends its budget on the rest.
    exclude_classes: list[str] = Field(default_factory=list, max_length=10000)

    @field_validator('exclude_classes')
    @classmethod
    def class_names(cls,values):
        import re
        if any(not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)+',v) for v in values):
            raise ValueError('Use fully qualified Java class names.')
        return sorted(set(values))

    @field_validator('include_packages','exclude_packages')
    @classmethod
    def package_prefixes(cls,values):
        import re
        if any(not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*(?:\.\*?|\*)?',v) for v in values):
            raise ValueError('Use literal Java package prefixes with an optional trailing dot or wildcard.')
        return sorted(set(values))


class SessionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    application_id: str
    analysis_id: str
    name: str
    environment: str
    status: str
    started_at: datetime | None
    ended_at: datetime | None
    last_received_at: datetime | None
    created_at: datetime
    span_count: int
    trace_count: int
    dropped_count: int
    agent_status: str = 'WAITING'


class SessionCreated(BaseModel):
    session: SessionView
    token: str
    agent: dict


class EvidenceResponse(BaseModel):
    analysis_id: str
    session_ids: list[str]
    graph: dict
    runtime_graph: dict
    coverage: dict
    mappings: list[dict]
    flows: list[dict]
    database: list[dict]
    database_summary: dict = Field(default_factory=dict)
    mapping_report: dict = Field(default_factory=dict)
    modernization: list[dict]
    recommendations: list[dict]
    limitations: list[str]
    quality: dict = Field(default_factory=dict)
    derivation_version: str = "legacy"


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
