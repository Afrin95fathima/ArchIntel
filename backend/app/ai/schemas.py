from typing import Literal
from pydantic import Field
from app.access.schemas import StrictInput


class ProviderInput(StrictInput):
    name: str = Field(min_length=1, max_length=120)
    endpoint: str = Field(default='http://127.0.0.1:11434', max_length=200)
    model: str = Field(min_length=1, max_length=120, pattern=r'^[A-Za-z0-9_.:-]+$')
    destination: str = Field(default='LOCAL_MODEL', max_length=40)


class ProviderState(StrictInput):
    enabled: bool


class SourceRange(StrictInput):
    file: str = Field(min_length=1, max_length=300)
    start: int = Field(ge=1, le=100000)
    end: int = Field(ge=1, le=100000)


class SourceQuery(StrictInput):
    repository_id: str = Field(max_length=36)
    commit: str = Field(pattern=r'^[0-9a-f]{40}$')
    ranges: list[SourceRange] = Field(min_length=1, max_length=10)
    question: str = Field(min_length=3, max_length=2000)
    purpose: str = Field(min_length=8, max_length=240, pattern=r'\S')
