from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator


class NamedInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)

    @field_validator('name')
    @classmethod
    def trim(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('Name cannot be blank.')
        return value.strip()


class ProjectInput(NamedInput):
    description: str = Field(default='', max_length=4000)


class ApplicationInput(NamedInput):
    project_id: str
    version: str = Field(default='1.0', max_length=80)


class ProjectView(ProjectInput):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime


class ApplicationView(ApplicationInput):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    source_type: str


class ArtifactView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    filename: str
    sha256: str
    size: int
    available: bool
    manifest: dict


class AnalysisView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    application_id: str
    artifact_id: str
    status: str
    progress: int
    stage: str
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    error_message: str | None
    limit_details: dict | None = None
    stages: list[dict]


class QueryInput(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    domain_id: str | None = None


class ItemsResponse(BaseModel):
    items: list[dict]
    total: int


class GraphResponse(BaseModel):
    nodes: list[dict]
    edges: list[dict]
    total_nodes: int
    total_edges: int
    truncated: bool


class AssistantResponse(BaseModel):
    answer: str
    facts: list[dict]
    recommendations: list[str]
    sources: list[dict]
    mode: str
    limitations: list[str]
