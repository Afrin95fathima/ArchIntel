from pydantic import BaseModel,ConfigDict,Field
from typing import Literal,Annotated

class DomainEdit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(min_length=1,max_length=120)
    name:str=Field(min_length=1,max_length=120)
    classes:list[Annotated[str,Field(min_length=1,max_length=400)]]=Field(max_length=20000)

class VersionInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    analysis_id:str=Field(max_length=36)
    name:str=Field(min_length=1,max_length=160)
    runtime_session_ids:list[str]=Field(default_factory=list,max_length=10)
    parent_id:str|None=Field(default=None,max_length=36)
    domain_edits:list[DomainEdit]|None=Field(default=None,max_length=1000)
    review_reason:str=Field(default='',max_length=1000)

class DiscoveryUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    state:Literal['OPEN','PLANNED','EXERCISED','DISMISSED']
    note:str=Field(min_length=1,max_length=1000)
    expected_revision:int=Field(ge=0)
