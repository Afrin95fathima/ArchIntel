# Launch recipes and API scenario files

A launch recipe lets the runner start an application that is not a single runnable JAR: a distribution (`.tar.gz`) with a
classpath and a main class, next to disposable dependency containers. The runner then calls the application's REST API and
records an ordinary runtime session. Built-in recipes live in `backend/app/automation/recipes/*.json`; the Dynamic analysis
screen lists them under **Explore automatically → REST API**.

## Recipe file

```json
{
  "id": "concord-server",
  "title": "Walmart Concord server (with a disposable PostgreSQL)",
  "description": "Shown on the Dynamic analysis screen.",
  "distribution_hint": "Where the .tar.gz comes from",
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
| `dependencies` | Up to four containers: `{name, image, port, env, ready_log, ready_log_count}`. Images must match `RUNNER_ALLOWED_IMAGES` (default `postgres:`). Each gets a fresh container on a loopback port and is removed when the run stops. |
| `config_files` | `{name, content}` written to the run folder with mode 600. |
| `ready` | `{path, timeout_ms}`: the application is ready when this path answers below HTTP 500. |
| `credential` | `{header, value}` sent with every exploration request, for example `Authorization: Bearer ${ADMIN_TOKEN}`. |

Placeholders in values: `${PORT}`, `${HOST}`, `${RUN_DIR}`, `${DIST_DIR}`, `${<DEPENDENCY>_PORT}` (for a dependency named
`db`, `${DB_PORT}`), each generated secret by name, and `${FILE:<config file name>}` for the path of a written config file.
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

`${RUN_ID}` is a random value per run, so names never collide. Cleanup steps run after the second crawl, so the crawl can
read back what the scenario created. A failed step is recorded and the next one still runs.

## How the crawl fills path variables

GET routes come from the static analysis. The first crawl calls routes without variables; after the scenarios, the
list routes are read again and routes with variables are called with values seen in earlier responses: the same field of
the preceding resource (`/process/{id}` uses `id`, `processId` or `instanceId` from process responses), then name or id of
the resource the variable names (`{orgName}` uses `name` from `/org`), newest values first. Up to three concrete paths per
route are called; routes with a variable no response contained are reported as unresolved.
