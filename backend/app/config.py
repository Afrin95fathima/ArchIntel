from pathlib import Path
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / '.env'), extra='ignore')
    database_url: str = 'sqlite:///' + (ROOT / '.data' / 'archintel.db').as_posix()
    data_dir: Path = ROOT / '.data'
    java_home: Path | None = None
    jqassistant_home: Path | None = None
    neo4j_uri: str = 'bolt://localhost:7687'
    neo4j_user: str = 'neo4j'
    neo4j_password: SecretStr = SecretStr('')
    graph_store_mode: str = 'isolated_embedded'
    knowledge_graph_enabled: bool = False
    knowledge_graph_uri: str = 'bolt://127.0.0.1:17687'
    knowledge_graph_user: str = 'neo4j'
    knowledge_graph_password: SecretStr = SecretStr('')
    knowledge_graph_password_file: Path | None = None
    @field_validator('knowledge_graph_uri')
    @classmethod
    def local_graph_uri(cls,value):
        from urllib.parse import urlsplit
        import ipaddress
        try:
            parsed=urlsplit(value)
            valid=parsed.scheme=='bolt' and ipaddress.ip_address(parsed.hostname).is_loopback and parsed.port is not None and not parsed.username and not parsed.password and parsed.path in ('','/') and not parsed.query and not parsed.fragment
        except (ValueError,TypeError):valid=False
        if not valid:raise ValueError('Use an explicit literal loopback bolt:// address and port without embedded credentials.')
        return value
    cors_origins: list[str] = ['http://localhost:5173', 'http://127.0.0.1:5173']
    allowed_hosts: list[str] = ['localhost', '127.0.0.1', '[::1]']
    secure_cookies: bool = False  # Enable for HTTPS deployments; local launcher uses loopback HTTP.
    session_hours: int = 8
    source_repository_roots: list[Path] = []  # Default: DATA_DIR/source-repositories.
    build_sandbox_image: str = ''  # Operator-provisioned local Linux image ID; never pulled automatically.
    security_sandbox_image: str = ''  # Separate trusted scanner image; customer build plugins cannot configure it.
    dependency_sandbox_image: str = ''  # Trivy and provisioned vulnerability databases.
    dependency_database_dir: Path = ROOT / '.runtime' / 'trivy-cache'  # Public scanner databases stay outside Docker's disk image.
    build_timeout_seconds: int = 180

    @field_validator('build_sandbox_image', 'security_sandbox_image', 'dependency_sandbox_image')
    @classmethod
    def pinned_build_image(cls, value):
        import re
        if value and not re.fullmatch(r'sha256:[0-9a-f]{64}', value):
            raise ValueError('Use an installed immutable sha256 image ID.')
        return value

    @field_validator('build_timeout_seconds')
    @classmethod
    def bounded_build_timeout(cls, value):
        if not 10 <= value <= 600: raise ValueError('Build timeout must be 10 to 600 seconds.')
        return value

    @field_validator('session_hours')
    @classmethod
    def session_limit(cls, value):
        if not 1 <= value <= 24:
            raise ValueError('Session lifetime must be between 1 and 24 hours.')
        return value
    external_prefixes: list[str] = ['java.', 'javax.', 'jakarta.', 'org.springframework.', 'org.hibernate.', 'org.slf4j.', 'com.fasterxml.', 'kotlin.']
    max_upload_mb: int = 100
    max_expanded_mb: int = 400
    max_archive_entries: int = 50000
    max_classes: int = 20000
    max_edges: int = 200000
    scan_timeout_seconds: int = 600
    # Conservative placeholders; validate with deployment ramp tests before advertising capacity.
    max_compression_ratio: int = 1024  # unvalidated, to be set from ramp-test results
    max_packages_per_scan: int = 10000  # unvalidated, to be set from ramp-test results
    max_job_disk_mb: int = 2048  # unvalidated, to be set from ramp-test results
    runtime_max_span_size_bytes: int = 262144  # unvalidated, to be set from ramp-test results
    runtime_max_session_duration_hours: int = 24  # unvalidated, to be set from ramp-test results
    retain_artifacts: bool = False
    max_cycle_length: int = 8
    max_cycles_per_scc: int = 20
    large_scc_threshold: int = 50
    readiness_weights: dict[str, float] = {'cohesion': .25, 'decoupling': .30, 'cycles': .25, 'database': .20}
    ai_allowed_endpoints: list[str] = ['http://127.0.0.1:11434']
    ai_timeout_seconds: int = 60
    # Gemini is a separate, explicitly opted-in code-generation destination.
    # The API credential is read from GEMINI_API_KEY and is never persisted to DB.
    gemini_api_key: SecretStr = SecretStr('')
    gemini_model: str = 'gemini-3.8-flash'
    gemini_timeout_seconds: int = 90
    gemini_max_output_bytes: int = 1048576
    @field_validator('ai_timeout_seconds')
    @classmethod
    def ai_timeout_limit(cls,value):
        if not 1 <= value <= 120:
            raise ValueError('AI timeout must be between 1 and 120 seconds.')
        return value

    @field_validator('gemini_model')
    @classmethod
    def valid_gemini_model(cls,value):
        import re
        if not re.fullmatch(r'gemini-[A-Za-z0-9.-]{1,80}',value):
            raise ValueError('Use a Gemini model identifier.')
        return value

    @field_validator('gemini_timeout_seconds')
    @classmethod
    def valid_gemini_timeout(cls,value):
        if not 5 <= value <= 120: raise ValueError('Gemini timeout must be 5 to 120 seconds.')
        return value

    @field_validator('gemini_max_output_bytes')
    @classmethod
    def valid_gemini_output(cls,value):
        if not 16384 <= value <= 2097152: raise ValueError('Gemini output limit must be 16 KiB to 2 MiB.')
        return value

    llm_url: str = ''
    llm_model: str = ''
    runtime_max_body_bytes: int = 4 * 1024 * 1024
    runtime_max_batch_spans: int = 5000
    runtime_max_session_spans: int = 50000
    runtime_raw_trace_retention_hours: int = 24
    runtime_structural_weight: float = .6
    runtime_public_url: str = 'http://127.0.0.1:8000'
    runtime_score_weights: dict[str, float] = {'cohesion': .60, 'cycles': .25, 'persistence': .15}

    @field_validator('runtime_max_body_bytes','runtime_max_batch_spans','runtime_max_session_spans','runtime_raw_trace_retention_hours')
    @classmethod
    def positive_runtime_limit(cls, value):
        if value <= 0: raise ValueError('Runtime limits must be positive.')
        return value

    @field_validator('max_upload_mb','max_expanded_mb','max_archive_entries','max_classes','max_edges',
                     'max_compression_ratio','max_packages_per_scan','max_job_disk_mb',
                     'runtime_max_span_size_bytes','runtime_max_session_duration_hours')
    @classmethod
    def positive_ingestion_limits(cls, value):
        if value < 0: raise ValueError('Ingestion limits cannot be negative.')
        return value

    @field_validator('runtime_structural_weight')
    @classmethod
    def valid_runtime_weight(cls, value):
        if not 0 <= value <= 1: raise ValueError('Structural weight must be between zero and one.')
        return value

    @field_validator('runtime_score_weights')
    @classmethod
    def valid_runtime_weights(cls, value):
        if set(value) != {'cohesion','cycles','persistence'} or any(v < 0 for v in value.values()) or abs(sum(value.values())-1)>1e-6:
            raise ValueError('Runtime component weights must be nonnegative and sum to one.')
        return value

    @field_validator('database_url')
    @classmethod
    def valid_database(cls, value: str) -> str:
        if not value.startswith(('postgresql+psycopg://', 'sqlite:///')):
            raise ValueError('Use PostgreSQL with psycopg or SQLite local mode.')
        return value

    @field_validator('readiness_weights')
    @classmethod
    def valid_weights(cls, value: dict[str, float]) -> dict[str, float]:
        if set(value) != {'cohesion', 'decoupling', 'cycles', 'database'} or any(v < 0 for v in value.values()) or abs(sum(value.values()) - 1) > 1e-6:
            raise ValueError('Four nonnegative readiness weights must sum to one.')
        return value

    def runtime_paths(self) -> tuple[Path, Path]:
        java = self.java_home or next((ROOT / '.runtime/java').glob('*'), Path('/missing-java'))
        jqa = self.jqassistant_home or next((ROOT / '.runtime/jqassistant').glob('*'), Path('/missing-jqassistant'))
        return java, jqa
