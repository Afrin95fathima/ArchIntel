from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .core import PERMISSIONS


class StrictInput(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Login(StrictInput):
    username: str = Field(min_length=3, max_length=120, pattern=r'^[A-Za-z0-9_.@-]+$')
    password: str = Field(min_length=1, max_length=128)


class Bootstrap(Login):
    bootstrap_key: str = Field(min_length=20, max_length=100)


class PasswordChange(StrictInput):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class PrincipalInput(Login):
    password: str = Field(default='', max_length=128)
    kind: Literal['HUMAN', 'SERVICE'] = 'HUMAN'
    permissions: list[str] = Field(max_length=10)

    @field_validator('permissions')
    @classmethod
    def permissions_known(cls, value):
        if not set(value) <= PERMISSIONS:
            raise ValueError('Unknown permission.')
        return sorted(set(value))


class WorkspaceInput(StrictInput):
    name: str = Field(min_length=1, max_length=160, pattern=r'\S')
    admin_username: str = Field(min_length=3, max_length=120, pattern=r'^[A-Za-z0-9_.@-]+$')
    admin_password: str = Field(min_length=12, max_length=128)


def safe_path(value):
    # Literal portable repository paths; no globs, dot segments, ADS or shell syntax.
    import re
    if not re.fullmatch(r'[A-Za-z0-9_./@ -]+', value) or value.startswith('/'):
        raise ValueError('Use literal relative repository paths.')
    if any(p in ('', '.', '..') for p in value.rstrip('/').split('/')):
        raise ValueError('Dot segments and empty path components are not allowed.')
    return value


class PolicyInput(StrictInput):
    expected_revision: int = Field(ge=0)
    source_read_enabled: bool = True
    max_files: int = Field(default=5, ge=1, le=20)
    max_bytes: int = Field(default=65536, ge=1, le=262144)
    protected_paths: list[str] = Field(default_factory=list, max_length=100)
    external_transfer: Literal['DENY'] = 'DENY'
    gemini_source_transfer_enabled: bool = False
    telemetry: Literal['DISABLED'] = 'DISABLED'
    model_enabled: bool = False
    model_provider_id: str | None = Field(default=None, max_length=36)
    model_context_bytes: int = Field(default=16384, ge=1024, le=32768)
    model_output_tokens: int = Field(default=128, ge=32, le=512)
    model_calls_per_hour: int = Field(default=30, ge=1, le=120)
    sensitive_data: Literal['REDACT', 'BLOCK'] = 'REDACT'
    deployment_profile: Literal['LOCAL_PRIVATE'] = 'LOCAL_PRIVATE'
    transformation_enabled: bool = False
    build_execution_enabled: bool = False
    max_task_files: int = Field(default=100, ge=1, le=2000)
    max_task_bytes: int = Field(default=1048576, ge=1, le=33554432)

    @field_validator('protected_paths')
    @classmethod
    def validate_paths(cls, values):
        return [safe_path(v) for v in values]


class RepositoryInput(StrictInput):
    application_id: str = Field(max_length=36)
    name: str = Field(min_length=1, max_length=160)
    path: str = Field(min_length=1, max_length=1000)
    commit: str = Field(pattern=r'^[0-9a-f]{40}$')


class GrantInput(StrictInput):
    principal_id: str = Field(max_length=36)
    repository_id: str = Field(max_length=36)
    allowed_paths: list[str] = Field(min_length=1, max_length=50)
    protected_paths: list[str] = Field(default_factory=list, max_length=50)

    @field_validator('allowed_paths', 'protected_paths')
    @classmethod
    def validate_paths(cls, values):
        return [safe_path(v) for v in values]


class ContextInput(StrictInput):
    repository_id: str = Field(max_length=36)
    commit: str = Field(pattern=r'^[0-9a-f]{40}$')
    files: list[str] = Field(min_length=1, max_length=20)
    purpose: str = Field(min_length=8, max_length=240, pattern=r'\S')
    operation: str = Field(default='SOURCE_READ', max_length=40)
    destination: str = Field(default='LOCAL_CONTEXT', max_length=40)


class PermissionsInput(StrictInput):
    permissions: list[str] = Field(max_length=10)

    @field_validator('permissions')
    @classmethod
    def known(cls, value):
        if not set(value) <= PERMISSIONS:
            raise ValueError('Unknown permission.')
        return sorted(set(value))
