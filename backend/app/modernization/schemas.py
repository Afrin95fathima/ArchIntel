from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Strategy = Literal['MODULAR_MONOLITH', 'MICROSERVICES', 'HYBRID', 'CLOUD_REFACTOR', 'JAVA_UPGRADE', 'FRAMEWORK_UPGRADE']


class PlanInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    strategy: Strategy = 'MODULAR_MONOLITH'
    objective: str = Field(default='Improve modular boundaries while preserving behavior.', min_length=1, max_length=1000)


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    state: Literal['APPROVED_PLANNING', 'CHANGES_REQUESTED', 'REJECTED']
    note: str = Field(min_length=1, max_length=2000)
    expected_revision: int = Field(ge=0)


class Question(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question: Literal['WHY', 'BLOCKERS', 'NEXT_STEP']
    decision_id: str = Field(min_length=1, max_length=36)
