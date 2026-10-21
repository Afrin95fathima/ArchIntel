from typing import Any, Literal
from pydantic import Field, field_validator, model_validator
from app.access.schemas import StrictInput, safe_path


class TaskInput(StrictInput):
    request_key: str = Field(default='', max_length=64)
    assessment_id: str = Field(max_length=36)
    decision_id: str = Field(max_length=36)
    repository_id: str = Field(max_length=36)
    commit: str = Field(pattern=r'^[0-9a-f]{40}$')
    objective: str = Field(min_length=8, max_length=1000)
    files: list[str] = Field(min_length=1, max_length=2000)
    allowed_files: list[str] = Field(min_length=1, max_length=2000)
    artifact_path: str = Field(default='target/application.jar', max_length=300)
    expected_change: str = Field(min_length=8, max_length=1000)
    # Optional binding from the evidence-driven microservice proposal. This
    # records intent only; it never turns a heuristic domain into authority.
    service_candidate_id: str | None = Field(default=None, max_length=120)
    rollout_mode: Literal['ONE_BY_ONE'] | None = None

    @field_validator('objective', 'expected_change')
    @classmethod
    def safe_metadata(cls, value):
        from app.ai.filters import sanitize
        if not value.strip(): raise ValueError('Provide meaningful task metadata.')
        sanitize(value, 'BLOCK')
        return value

    @field_validator('files', 'allowed_files')
    @classmethod
    def paths(cls, values):
        return sorted(set(safe_path(v) for v in values))

    @field_validator('artifact_path')
    @classmethod
    def artifact(cls, value):
        value = safe_path(value)
        if not value.startswith('target/') or not value.endswith(('.jar', '.war')):
            raise ValueError('Choose a JAR/WAR below target/.')
        return value


class RevisionInput(StrictInput):
    expected_revision: int = Field(ge=0)
    note: str = Field(min_length=8, max_length=1000)

    @field_validator('note')
    @classmethod
    def safe_note(cls, value):
        from app.ai.filters import sanitize
        if not value.strip(): raise ValueError('Provide a review note.')
        sanitize(value, 'BLOCK')
        return value


class TaskAction(RevisionInput):
    action: Literal['PAUSE', 'RESUME', 'ROLLBACK', 'RECHECK']


class FileEdit(StrictInput):
    path: str = Field(max_length=300)
    operation: Literal['ADD', 'MODIFY', 'DELETE']
    expected_sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    content: str = Field(default='', max_length=262144)

    @field_validator('path')
    @classmethod
    def path_safe(cls, value): return safe_path(value)


class ChangeInput(RevisionInput):
    edits: list[FileEdit] = Field(min_length=1, max_length=100)


class RecipeInput(RevisionInput):
    recipe: Literal['INTRODUCE_INTERFACE']
    implementation_file: str = Field(max_length=300)
    interface_file: str = Field(max_length=300)
    interface_name: str = Field(pattern=r'^[A-Z][A-Za-z0-9_]{0,79}$')
    methods: list[str] = Field(min_length=1, max_length=20)

    @field_validator('implementation_file', 'interface_file')
    @classmethod
    def recipe_path(cls, value):
        value = safe_path(value)
        if not value.endswith('.java'): raise ValueError('Recipe files must be Java source files.')
        return value

    @field_validator('methods')
    @classmethod
    def method_names(cls, values):
        import re
        if len(values) != len(set(values)) or any(not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]{0,79}', v) for v in values):
            raise ValueError('Use unique Java method names.')
        return values


class MicroserviceGenerateInput(StrictInput):
    """Per-request acknowledgement before selected source is sent to the chosen external model provider."""
    expected_revision: int = Field(ge=0)
    confirm_source_transfer: Literal[True]
    provider: Literal['GEMINI', 'CLAUDE'] = 'GEMINI'
    acknowledgement: Literal['I_APPROVE_SENDING_SELECTED_SOURCE_TO_GOOGLE_GEMINI', 'I_APPROVE_SENDING_SELECTED_SOURCE_TO_ANTHROPIC_CLAUDE']

    @model_validator(mode='after')
    def acknowledgement_names_the_provider(self):
        expected = {'GEMINI': 'I_APPROVE_SENDING_SELECTED_SOURCE_TO_GOOGLE_GEMINI', 'CLAUDE': 'I_APPROVE_SENDING_SELECTED_SOURCE_TO_ANTHROPIC_CLAUDE'}[self.provider]
        if self.acknowledgement != expected:
            raise ValueError('The acknowledgement must name the provider that receives the source.')
        return self


class MicroserviceBundleReviewInput(RevisionInput):
    fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    action: Literal['APPROVE_FOR_ISOLATED_BUILD', 'REJECT']


class ExtractionPlanInput(RevisionInput):
    """Request a read-only extraction-boundary proposal for the pinned baseline."""


class DataDiscoveryInput(RevisionInput):
    """Inspect only the authorized, immutable task source snapshot."""


class BusinessInvariantInput(StrictInput):
    name: str = Field(min_length=3, max_length=120)
    kind: Literal['ROW_COUNT_EQUAL', 'UNIQUE', 'NOT_NULL', 'FOREIGN_KEY_VALID']
    table: str = Field(min_length=1, max_length=120)
    column: str = Field(default='', max_length=120)


class TargetProposalInput(RevisionInput):
    target_engine: Literal['LOGICAL', 'SQLITE_TEST'] = 'LOGICAL'
    business_invariants: list[BusinessInvariantInput] = Field(default_factory=list, max_length=50)


class DataMigrationMappingOverride(StrictInput):
    source_table: str = Field(min_length=1, max_length=120)
    source_column: str = Field(min_length=1, max_length=120)
    target_column: str = Field(min_length=1, max_length=120)
    target_type: Literal['INT16','INT32','INT64','STRING','BOOLEAN','DECIMAL','FLOAT','DATE','TIMESTAMP','TIME','UUID','JSON','BINARY']
    conversion: Literal['IDENTITY','STRING','INTEGER','DECIMAL','DATE','TIMESTAMP','BOOLEAN','MANUAL']
    rationale: str = Field(min_length=12,max_length=1000)


class DataMigrationPlanRevisionInput(RevisionInput):
    base_plan_id: str = Field(max_length=36)
    mapping_overrides: list[DataMigrationMappingOverride] = Field(min_length=1,max_length=200)


class DataMigrationPlanDecision(StrictInput):
    resource: str = Field(min_length=1, max_length=120)
    owner_domain_id: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=12, max_length=1000)


class DataMigrationPlanReviewInput(RevisionInput):
    plan_id: str = Field(max_length=36)
    fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    action: Literal['APPROVE_FOR_TEST', 'REJECT']
    ownership_decisions: list[DataMigrationPlanDecision] = Field(default_factory=list, max_length=100)
    acknowledged_risks: list[str] = Field(default_factory=list, max_length=100)


class SyntheticMigrationRunInput(StrictInput):
    expected_revision: int = Field(ge=0)
    note: str = Field(min_length=8, max_length=1000)
    plan_id: str = Field(max_length=36)
    data_classification: Literal['SYNTHETIC']
    rows: dict[str, list[dict[str, Any]]]

    @field_validator('rows')
    @classmethod
    def bound_fixture(cls, value):
        import json
        if len(value) > 100 or sum(len(rows) for rows in value.values()) > 5000:
            raise ValueError('Synthetic fixture exceeds the table or row limit.')
        if len(json.dumps(value, ensure_ascii=False).encode('utf-8')) > 1_000_000:
            raise ValueError('Synthetic fixture exceeds the 1 MB limit.')
        return value


class DataResource(StrictInput):
    system: str = Field(min_length=1, max_length=100)
    schema_name: str = Field(min_length=1, max_length=100)
    resource: str = Field(min_length=1, max_length=100)

    @field_validator('system', 'schema_name', 'resource')
    @classmethod
    def safe_identifier(cls, value):
        import re
        if not re.fullmatch(r'[A-Za-z0-9_$.-]{1,100}', value):
            raise ValueError('Use a qualified resource identifier, not SQL or an expression.')
        return value


class DataColumnMapping(StrictInput):
    source_column: str = Field(pattern=r'^[A-Za-z_][A-Za-z0-9_$]{0,99}$')
    target_column: str = Field(pattern=r'^[A-Za-z_][A-Za-z0-9_$]{0,99}$')
    conversion: Literal['IDENTITY', 'STRING', 'INTEGER', 'DECIMAL', 'DATE', 'TIMESTAMP', 'BOOLEAN', 'MANUAL']
    key: bool = False


class DataInvariant(StrictInput):
    name: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=8, max_length=1000)
    expected: str = Field(min_length=1, max_length=300)


class DataRecovery(StrictInput):
    backup_id: str = Field(default='', max_length=120)
    restore_tested: bool = False
    rollback_strategy: str = Field(min_length=8, max_length=1000)


class DataMigrationPlanInput(RevisionInput):
    source: DataResource
    target: DataResource
    mappings: list[DataColumnMapping] = Field(min_length=1, max_length=200)
    invariants: list[DataInvariant] = Field(default_factory=list, max_length=50)
    conflict_policy: Literal['ABORT_ON_CONFLICT', 'REVIEW_EACH_CONFLICT', 'EXPLICIT_UPSERT']
    recovery: DataRecovery
    ownership_statement: str = Field(min_length=20, max_length=2000)
    ownership_evidence: list[str] = Field(min_length=1, max_length=50)

    @field_validator('ownership_statement', 'ownership_evidence')
    @classmethod
    def safe_ownership_metadata(cls, value):
        from app.ai.filters import sanitize
        values = value if isinstance(value, list) else [value]
        for item in values:
            if not item.strip(): raise ValueError('Ownership evidence must be meaningful.')
            sanitize(item, 'BLOCK')
        return value


class DataMigrationReviewInput(RevisionInput):
    fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    action: Literal['APPROVE_PLAN', 'REJECT_PLAN']


class ChangeReview(RevisionInput):
    fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    action: Literal['APPROVE_STAGING', 'REJECT']


class ContractInput(StrictInput):
    name: str = Field(min_length=3, max_length=160)
    test_file: str = Field(max_length=300)
    test_case: str = Field(min_length=3, max_length=300)
    scenario: str = Field(min_length=8, max_length=2000)
    expected_behavior: str = Field(min_length=8, max_length=2000)
    critical: bool = True

    @field_validator('test_file')
    @classmethod
    def path_safe(cls, value): return safe_path(value)


class ImpactReviewInput(RevisionInput):
    impact_fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    action: Literal['ACCEPT', 'REJECT']
