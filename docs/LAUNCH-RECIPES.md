# Launch recipes and API scenario files

A launch recipe lets the runner start an application that is not a single runnable JAR: a distribution (`.tar.gz`) with a
classpath and a main class, next to disposable dependency containers. The runner then calls the application's REST API and
records an ordinary runtime session. Built-in recipes live in `backend/app/automation/recipes/*.json`; the Dynamic analysis
screen lists them under **Explore automatically → REST API**, with one upload per distribution the recipe declares
(`max_distribution_mb`, default 400).

## Recipe file

```json
{
  "id": "concord-server",
  "title": "Walmart Concord server (with a disposable PostgreSQL)",
  "description": "Shown on the Dynamic analysis screen.",
  "distribution_hint": "Where the .tar.gz comes from",
  "distributions": [
    {"id": "server", "primary": true, "title": "Concord server distribution", "hint": "server/dist/target/..."},
    {"id": "agent", "title": "Concord agent distribution", "hint": "agent/target/..."}
  ],
  "recipe": { "...": "what the runner starts, see below" },
  "instrumentation": { "mode": "DEEP", "include_packages": [], "exclude_packages": ["com.example.agent"] },
  "exploration": { "skip_paths": ["/waitForCompletion$"], "max_requests": 800, "passes": 5 },
  "scenarios": [ { "...": "see Scenario files" } ]
}
```

`recipe` is validated by the runner (`runner/src/recipes.mjs`) before anything starts:

| Field | Meaning and limits |
|---|---|
| `name` | Lower-case identifier. |
| `main_class` | Fully qualified class started with `java -cp <classpath> <main_class>`. |
| `classpath` | Entries relative to the unpacked distribution (`lib/*`, `classes`); absolute paths and `..` are refused. |
| `jvm_args`, `args` | Extra JVM and program arguments. `-javaagent`, `-agentlib`, `-agentpath`, `-cp`, `-jar`, `-Dotel.*` and `-XX:OnError` are reserved for the runner. |
| `system_properties`, `env` | `-D` properties and environment variables. |
| `generated_secrets` | `{name, kind}` with kind `base64` or `password`; a new random value per run, never returned to ArchIntel. |
| `dependencies` | Up to four containers: `{name, image, port, env, ready_log, ready_log_count, init}`. Images must match `RUNNER_ALLOWED_IMAGES` (default `postgres:`, `osixia/openldap:`). `init` `{command, stdin}` seeds the container once it is ready: an argument list run with `docker exec` (no shell) and its standard input, retried for 20 seconds; Concord's recipe adds an LDAP user and group with `ldapadd`. Each gets a fresh container on a loopback port and is removed when the run stops. |
| `config_files` | `{name, content}` written to the run folder with mode 600. |
| `ready` | `{path, timeout_ms}`: the application is ready when this path answers below HTTP 500. |
| `ports` | Up to five extra loopback ports by variable name (for example `AGENT_MM_PORT`), for listeners a companion opens. |
| `companions` | Up to three more processes started once the main process is ready, in order: `{name, distribution, main_class, classpath, jvm_args, args, system_properties, env, ready_log, ready_timeout_ms}`. `distribution` names an entry of `distributions`; each gets the OpenTelemetry agent and the same JVM-option rules; it is ready when its log contains `ready_log`. Companions stop before the main process. |
| `credential` | `{header, value}` sent with every exploration request, for example `Authorization: Bearer ${ADMIN_TOKEN}`. |
| `git_repositories` | Up to three `{name, branch, files}` repositories the runner creates with one commit and serves read-only over smart HTTP on a loopback port (`git http-backend`; clone and fetch only, pushes refused). Their URLs are `${GIT_<NAME>_URL}` in config files and scenarios. |
| `scenario_variables` | Names of generated secrets or ports that scenarios may use, for example an LDAP user's password for a `basic_auth` step. They are sent in requests and never returned. |

Placeholders in values: `${PORT}`, `${HOST}`, `${RUN_DIR}`, `${DIST_DIR}`, `${DIST_DIR_<ID>}` for a companion distribution
(`${DIST_DIR_AGENT}`), `${<DEPENDENCY>_PORT}` (for a dependency named `db`, `${DB_PORT}`), each extra port and generated
secret by name, `${FILE:<config file name>}` for the path of a written config file, and `${OTEL_JVM_ARG}`: the
`-javaagent:` option of the run (a harmless property when telemetry is off), for processes that start JVMs themselves. The
Concord agent passes it to every workflow JVM through `runner.jvmParams`, so workflow executions are traced too.

Run folders hold the generated secrets in config files and logs: they are created owner-only and deleted when the run stops
(`RUNNER_KEEP_RUN_DIRS=1` keeps them for diagnosis). A log tail attached to a start failure has every generated secret
replaced by `[generated secret]` before it leaves the runner.
An unknown upper-case placeholder is an error; lower-case and `${?NAME}` forms are left alone, so HOCON or Spring syntax in a
config file is untouched.

`instrumentation` sets the session's depth and package scope (exclude modules that do not run in the started process).
`exploration.skip_paths` are regular expressions matched against route templates the crawl must not call.

## Scenario files

A scenario is an ordered list of API calls that create, read and finally remove data, for routes the read-only crawl does
not reach. Upload one on the screen to replace the recipe's built-in scenarios (a single scenario, a list, or
`{"scenarios": [...]}`).

```json
{
  "name": "Organization lifecycle",
  "steps": [
    {"id": "create-org", "method": "POST", "path": "/api/v1/org", "json": {"name": "archintel-${RUN_ID}"}, "extract": {"ORG_ID": "id"}},
    {"id": "create-secret", "method": "POST", "path": "/api/v1/org/archintel-${RUN_ID}/secret",
     "multipart": {"name": "s-${RUN_ID}", "type": "USERNAME_PASSWORD", "username": "archintel", "password": "not-a-real-password"}},
    {"id": "start-process", "method": "POST", "path": "/api/v1/process",
     "multipart": {"org": "archintel-${RUN_ID}", "concord.yml": {"filename": "concord.yml", "content": "flows:\n  default:\n    - log: hi\n"}}}
  ],
  "cleanup": [
    {"id": "delete-org", "method": "DELETE", "path": "/api/v1/org/archintel-${RUN_ID}?confirmation=yes"}
  ]
}
```

| Step field | Meaning |
|---|---|
| `method`, `path` | GET, POST, PUT, PATCH or DELETE on a path of the started application; other origins are refused. |
| `json` or `multipart` | Request body; a multipart value given as `{filename, content, type}` is sent as a file. |
| `extract` | `{VARIABLE: "dotted.path"}` read from the JSON response, for later steps as `${VARIABLE}`. |
| `expect` | Status codes that count as passed (default: below 400). |
| `text` | A `text/plain` body, for endpoints such as Concord's value encryption. |
| `basic_auth` | `{username, password}` sent as HTTP Basic instead of the run's credential, to exercise a login realm such as LDAP. |
| `until` | GET only: `{path, in, success, timeout_ms, interval_ms}` repeats the request until the field at `path` holds a value of `in` (a final state), and passes only when it is one of `success` (default: `in`). Example: wait for a process to reach `FINISHED`, stopping early on `FAILED`. |

`${RUN_ID}` is a random value per run, so names never collide. A step whose path still holds an unresolved `${...}` (an earlier
step did not return the value) is skipped and reported, not sent, and a polling step stops at the first error response. Cleanup steps run after the second crawl, so the crawl can
read back what the scenario created. A failed step is recorded and the next one still runs.

## How the crawl fills path variables

GET routes come from the static analysis. The first crawl calls routes without variables; after the scenarios, the
list routes are read again and routes with variables are called with values seen in earlier responses: the same field of
the preceding resource (`/process/{id}` uses `id`, `processId` or `instanceId` from process responses), then name or id of
the resource the variable names (`{orgName}` uses `name` from `/org`), newest values first. Up to three concrete paths per
route are called; routes with a variable no response contained are reported as unresolved.
