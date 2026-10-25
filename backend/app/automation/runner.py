"""Client for the host-side runner. Every call carries the runner token; nothing here runs code locally."""
import httpx


class RunnerError(Exception):
    def __init__(self, code: str, detail: str = '', status: int = 0):
        super().__init__(code)
        self.code, self.detail, self.status = code, detail, status


class Runner:
    def __init__(self, settings, transport=None):
        self.base = settings.runner_url.rstrip('/')
        self.token = settings.runner_token.get_secret_value()
        self.timeout = settings.runner_timeout_seconds
        self.transport = transport

    @property
    def configured(self) -> bool:
        return len(self.token) >= 24

    def _call(self, method: str, path: str, *, json=None, content=None, timeout=None):
        if not self.configured:
            raise RunnerError('RUNNER_NOT_CONFIGURED', 'Set RUNNER_TOKEN for ArchIntel and the runner.')
        headers = {'authorization': f'Bearer {self.token}'}
        try:
            with httpx.Client(trust_env=False, follow_redirects=False, transport=self.transport,
                              timeout=httpx.Timeout(timeout or self.timeout, connect=5)) as client:
                response = client.request(method, self.base + path, json=json, content=content, headers=headers)
        except httpx.HTTPError as error:
            raise RunnerError('RUNNER_UNREACHABLE', type(error).__name__) from None
        try:
            payload = response.json()
        except ValueError:
            raise RunnerError('RUNNER_RESPONSE_INVALID', status=response.status_code) from None
        if response.status_code >= 400:
            raise RunnerError(str(payload.get('error') or 'RUNNER_ERROR'), str(payload.get('detail') or ''), response.status_code)
        return payload

    def health(self):
        return self._call('GET', '/v1/health', timeout=30)

    def upload(self, sha256: str, content: bytes):
        return self._call('PUT', f'/v1/artifacts/{sha256}', content=content, timeout=300)

    def start_app(self, artifact_sha256: str, otel: dict | None):
        return self._call('POST', '/v1/apps', json=dict(artifact_sha256=artifact_sha256, otel=otel), timeout=300)

    def stop_app(self, run_id: str):
        return self._call('DELETE', f'/v1/apps/{run_id}', timeout=60)

    def app_log(self, run_id: str):
        return self._call('GET', f'/v1/apps/{run_id}/log', timeout=30)

    def explore(self, run_id: str, seeds: list[str], max_pages: int, max_forms: int):
        return self._call('POST', '/v1/explore', json=dict(run_id=run_id, seeds=seeds, max_pages=max_pages, max_forms=max_forms))

    def upload_distribution(self, sha256: str, content: bytes):
        return self._call('PUT', f'/v1/distributions/{sha256}', content=content, timeout=600)

    def start_recipe(self, distribution_sha256: str, recipe: dict, otel: dict | None):
        # Dependencies are pulled and started first; a first database migration can take minutes.
        return self._call('POST', '/v1/recipe-runs', json=dict(distribution_sha256=distribution_sha256, recipe=recipe, otel=otel), timeout=960)

    def explore_api(self, run_id: str, endpoints: list[dict], scenarios: list[dict], skip_paths: list[str], max_requests: int):
        return self._call('POST', '/v1/explore-api', json=dict(run_id=run_id, endpoints=endpoints, scenarios=scenarios, skip_paths=skip_paths,
                                                              max_requests=max_requests), timeout=3700)

    def build_service(self, name: str, files: list[dict]):
        return self._call('POST', '/v1/services', json=dict(name=name, files=files))

    def stop_service(self, name: str):
        return self._call('DELETE', f'/v1/services/{name}', timeout=90)

    def service_log(self, name: str):
        return self._call('GET', f'/v1/services/{name}/log', timeout=30)

    def compare(self, baseline_url: str, candidate_url: str, scenarios: list[dict]):
        return self._call('POST', '/v1/compare', json=dict(baseline_url=baseline_url, candidate_url=candidate_url, scenarios=scenarios))
