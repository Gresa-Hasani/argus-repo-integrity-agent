# ARGUS — Repository Integrity & Cohort Analysis

ARGUS evaluates the engineering evidence in Git repositories: history, contributions, source provenance,
repository hygiene, README claims, and CI configuration. Its web interface evaluates **multiple public
GitHub repositories**, compares every pair, and graphs each repository's measured results.

**Measure first, reason second.** Git and static collectors produce the evidence. Ollama, OpenAI, or
Claude interprets bounded evidence packets. Deterministic policy validates citations, decides whether a
finding is justified, and calculates the final status. A model cannot invent measurements or clear a
material concern by explanation alone.

ARGUS is an integrity evaluator, not an automatic assignment grader. Requirements, extra credit, solver
correctness, and academic scores require their own verified rubric and benchmark evidence.

## Contents

- [Quick start](#quick-start)
- [Choose an AI provider](#choose-an-ai-provider)
- [Evaluate repositories in the UI](#evaluate-repositories-in-the-ui)
- [Statistics and copied-code detection](#statistics-and-copied-code-detection)
- [Complete an evaluation](#complete-an-evaluation)
- [CLI](#cli)
- [Configuration](#configuration)
- [HTTP API](#http-api)
- [Reproducible tests](#reproducible-tests)
- [Architecture and evidence policy](#architecture-and-evidence-policy)
- [Deployment and data handling](#deployment-and-data-handling)
- [Limits and troubleshooting](#limits-and-troubleshooting)

## Quick start

Requirements: **Python 3.12+**, **Git**, and **Node.js 20.9+** with npm for the UI. Use a supported Node LTS
release. A full evaluation also needs an available AI provider; Ollama is optional when using a hosted API.

From a POSIX shell:

```bash
git clone https://github.com/Gresa-Hasani/argus-repo-integrity-agent.git
cd argus-repo-integrity-agent
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev,ui,analytics]'
npm --prefix ui ci
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell instead. Set environment variables
with `$env:NAME = 'value'` instead of `export NAME=value`.

Select a provider using the next section, then start the backend from the repository root:

```bash
python -m uvicorn argus.server:app --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
npm --prefix ui run dev -- --hostname 127.0.0.1
```

Open [ARGUS at localhost:3000](http://localhost:3000). The checked-in `ui/.env.development` selects
`http://localhost:8000` as the development backend. Check connectivity with:

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/ready
```

`/health` confirms the backend is alive. `/ready` separately reports whether AI reasoning is available
and whether another batch occupies the evaluation queue. Readiness checks model availability, not the
accuracy of its future answers.

Optional: install [scc](https://github.com/boyter/scc) for its source and complexity metrics. Without scc,
ARGUS labels its built-in line counter as a fallback and leaves complexity unavailable.

## Choose an AI provider

The UI offers **Server default**, **OpenAI API**, and **Claude API**. Configure keys in the backend process
before starting it. Keys never belong in `NEXT_PUBLIC_*` variables, Git, or browser input fields.

### Ollama: local models

Install [Ollama](https://ollama.com/download), start its service, and pull a model:

```bash
ollama pull qwen3:4b
```

The portable default is Qwen3 4B. To explicitly select a different Ollama model:

```bash
export ARGUS_LLM_PROVIDER=ollama
export ARGUS_MODEL='your-installed-model-tag'
```

The checked-in `argus.gemma.toml` profile selects **Gemma 3 12B Q4_K_M**, imported on the development
workstation under `argus-gemma3:12b`. This custom tag is **not bundled with ARGUS** and is not guaranteed
to exist on another machine. Install/import a compatible model first; confirm its exact tag with
`ollama list`. Model size, context length, available RAM/VRAM, and hardware determine runtime.

```bash
argus evaluate https://github.com/owner/repository --config argus.gemma.toml
```

Local configuration is read from `argus.toml`. Copy `argus.example.toml` as a starting point, or copy
`argus.gemma.toml` when that model is installed. Ollama and the generic Ollama provider also support
other text models; the Qwen provider retains logical-name mapping and the OpenAI-compatible local
runtime backend for vLLM, llama.cpp, or LM Studio.

### OpenAI API

```bash
export OPENAI_API_KEY='your-key'
export ARGUS_OPENAI_MODEL='gpt-4.1-mini'
```

Restart the backend and select **OpenAI API** in the batch form. The adapter uses the
[Responses API](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses),
JSON mode, schema instructions, and `store=false`; ARGUS validates the returned object itself.

For CLI use, or to make OpenAI the **Server default**:

```bash
export ARGUS_LLM_PROVIDER=openai
export ARGUS_MODEL='gpt-4.1-mini'
```

### Claude API

```bash
export ANTHROPIC_API_KEY='your-key'
export ARGUS_ANTHROPIC_MODEL='claude-sonnet-4-6'
```

Restart the backend and select **Claude API**. The adapter uses the
[Anthropic Messages API](https://platform.claude.com/docs/en/api/messages/create), a schema-defined
output tool, and forced tool selection. It accepts the returned tool object only after ARGUS validation.

For CLI use, or to make Claude the **Server default**:

```bash
export ARGUS_LLM_PROVIDER=anthropic
export ARGUS_MODEL='claude-sonnet-4-6'
```

`claude` is an alias for `anthropic`. Model access depends on your provider account. Hosted requests
send the evidence packet to the selected provider and incur its API charges. ARGUS does not silently
switch providers when a request fails. API transport tests use simulated responses; a live key is
required to verify real account access, quota, and model behavior.

## Evaluate repositories in the UI

1. Build a list by **pasting URLs**, **importing a `.txt` list**, using **public GitHub search**, or adding
   the curated public test repositories.
2. Select an available AI provider. **Leave “Deterministic evidence only” unchecked for a full run.**
3. Start the batch and follow each repository's queue state, progress, findings, and report.
4. Review the statistics and every pairwise code/README comparison.
5. Use **View saved batch results** to reopen a batch without evaluating it again.

Accepts 1–50 repository home-page URLs such as `https://github.com/owner/repository`. Separate them
with newlines, spaces, commas, or semicolons. Duplicates are removed and the entire list is validated
before scheduling. The web API accepts public GitHub repositories; the CLI additionally accepts local
Git repositories. GitHub search excludes private and archived results. If search is unavailable or
rate-limited, pasted links and curated examples remain usable.

Repositories run sequentially. A failed repository does not abort the remaining queue. Closing the
browser does not cancel the server job, but stopping or restarting the backend interrupts an active
queue. Completed individual reports and batch summaries survive restarts; running queues do not.

## Statistics and copied-code detection

Choose a graph metric: findings, meaningful source lines, commits, passed-check percentage, or evaluator
errors. Each repository has a labeled bar; the distribution shows sample size, mean, median, sample
standard deviation, missing values, and a histogram. A descriptive normal fit appears only with at least
three non-identical measurements. It does not establish that the cohort is normally distributed.

The first view **excludes flagged repositories**. When flags exist, a second view includes them, using
the same axes and bins. Missing reports and unavailable measurements never become zeros. Incomplete
reports stay labeled; passed-check percentage measures evaluation coverage, not software quality.

### What the overlap flag means

ARGUS compares every acquired pair using **directional token 6-gram containment** over classified
source/test files. A→B measures the share of A's file shingles also found in B; B→A can differ when a
derivative adds substantial code. Files with fewer than 20 unique shingles are skipped. Matching source
may be renamed or reformatted; extensive identifier changes or semantic rewrites can reduce detection.
This is textual similarity, not semantic equivalence analysis.

Code containment at or above `similarity_threshold` (default **70%**) in either direction flags both
participants for review and excludes both from the primary statistics. Matched-file evidence is stored
in the batch summary. **Shared README text or headings alone never create a code-overlap flag.**
Documentation, configuration, generated/vendored content, datasets, binaries, build output, minified
files, lockfiles, and CI files are excluded by the source-classification rules.

An overlap flag does not establish intent, licensing violations, or who copied whom. Review declared
forks, attribution, shared starter templates, libraries, and commit history. The batch flag is distinct
from the completion status and findings of each individual evaluation. For an individual similarity
finding, supply references with CLI `--compare`.

### Real modified-derivative test

[Requests](https://github.com/psf/requests) and [Niquests](https://github.com/jawah/niquests) are public
repositories; GitHub explicitly identifies Niquests as a Requests fork. On the commits recorded in
[`test-cohort/requests-niquests.json`](test-cohort/requests-niquests.json), ARGUS measured **70.63%**
Requests→Niquests containment and **28.15%** in reverse, triggering the unchanged 70% review threshold.
Their corresponding `sessions.py` files contain 920 and 2,247 lines with different hashes; this is a
modified derivative, not an identical-file fixture. It is a legitimate reuse example, not a misconduct claim.
The manifest records modes, commit hashes, changed-file evidence, and reproducible API input.

## Complete an evaluation

A batch reaching `done` means its queue and comparisons finished. It does **not** mean every repository
passed, nor that all required checks were completed. Inspect each individual report and its coverage.

| Individual status | Meaning | CLI exit |
|---|---|---|
| `DONE_CLEAN` | All applicable checks completed, with no findings, review requirements, errors, or coverage gaps | 0 |
| `DONE_WITH_FINDINGS` | Evaluation completed with non-material findings, failed checks, or optional evidence gaps | 0 |
| `FLAGGED` | Required checks completed and an unresolved material concern requires review | 3 |
| `INCOMPLETE_EVALUATION` | At least one mandatory check could not be verified | 4 |
| `EVALUATOR_ERROR` | Collector, provider, reasoning, or report validation failed | 5 |

Evaluation errors take precedence over missing mandatory evidence, which takes precedence over material
findings. A report may therefore contain a verified similarity flag while its completion state remains
incomplete. These are separate facts and both remain visible. Configuration/usage errors use exit 2.

To obtain a full evaluation:

- Make the selected provider available; confirm the model tag or API key and account access.
- Enable AI reasoning. `--no-llm` and the deterministic-only checkbox intentionally skip required reasoning
  checks and **cannot produce a complete evaluation**.
- Ensure the full repository history can be acquired. If `--require-similarity` is enabled, supply valid
  reference repositories with `--compare`.
- Open a failed report, inspect `errors`, `coverage`, and `definition_of_done.reasons`, fix the recorded
  cause, and rerun with AI enabled. The new report has a new evaluation ID; earlier evidence is retained.
- Allow the backend and provider to finish. If a queue was interrupted by a backend restart, resubmit it.

ARGUS never converts skipped, unavailable, refused, truncated, or invalid model output into a pass.
The model gets one repair attempt for invalid structured output. Material findings can require manual
review even after all automated checks finish; a completed evaluation need not be clean.

## CLI

```bash
# Full evaluation using configured provider
argus evaluate https://github.com/owner/repository

# Compare local or public repositories, with a mandatory provenance check
argus evaluate ./target --compare ./reference --require-similarity

# A deadline must include the intended timezone
argus evaluate ./target --deadline '2026-10-01T18:00:00+02:00'

# Explicit collection-only diagnostic, intentionally incomplete
argus evaluate ./target --no-llm
```

Additional options: `--provider`, `--model`, `--fallback-model`, `--config`, `--backend ollama|openai`
(the latter selects the local runtime protocol), `--base-url`, `--similarity-threshold`, `--out`,
`--no-github-api`, `--keep-clone`, `--quiet`. Run `argus evaluate --help` for the full interface.
Passing multiple targets to the CLI evaluates them sequentially; automatic all-pairs comparison and
batch statistics are provided by the batch API/UI.

## Configuration

Precedence: **defaults < `argus.toml` < environment < CLI flags**. See
[`argus.example.toml`](argus.example.toml), [`argus.gemma.toml`](argus.gemma.toml), and
[`.env.example`](.env.example). ARGUS does not automatically load `.env`; export variables or use an
appropriate process launcher. Restart the backend after changing its environment or configuration.

| Variable | Purpose / default |
|---|---|
| `ARGUS_LLM_PROVIDER` | `qwen` by default; also `ollama`, `openai`, `anthropic`/`claude` |
| `ARGUS_MODEL` | Server/CLI model; local default `qwen3:4b`; provider changes select provider-specific defaults |
| `ARGUS_FALLBACK_MODEL` | Optional local fallback; disabled by default and always reported when used |
| `ARGUS_LLM_BACKEND` | Local transport: `ollama` or OpenAI-compatible `openai` |
| `ARGUS_LLM_BASE_URL` | Server/CLI endpoint; default `http://localhost:11434` locally |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | Backend-only hosted credentials; `ARGUS_LLM_API_KEY` is a generic fallback |
| `ARGUS_OPENAI_MODEL`, `ARGUS_ANTHROPIC_MODEL` | Model for each explicit hosted choice in the UI |
| `ARGUS_OPENAI_BASE_URL`, `ARGUS_ANTHROPIC_BASE_URL` | Optional HTTPS endpoints for explicit hosted UI choices |
| `ARGUS_LLM_MAX_TOKENS`, `ARGUS_LLM_NUM_CTX` | Answer token limit / local context: `1536` / `8192` |
| `ARGUS_LLM_PACKET_CHARS` | Evidence packet character budget: `9000` |
| `ARGUS_LLM_TEMPERATURE`, `ARGUS_LLM_TIMEOUT` | Temperature / request timeout: `0.1` / `900` seconds |
| `ARGUS_LLM_THINK` | Qwen local thinking toggle: `false` |
| `ARGUS_LLM_MODEL_TAG`, `ARGUS_LLM_FALLBACK_MODEL_TAG` | Exact local runtime tags when logical model mapping is insufficient |
| `ARGUS_SIMILARITY_THRESHOLD` | Code containment threshold: `0.70` |
| `GITHUB_TOKEN` or `GH_TOKEN` | Optional REST API authentication; required for some PR review detail |
| `ARGUS_SCC_PATH` | Optional path to scc |
| `ARGUS_REPORTS_DIR` | Saved output directory: `argus-reports` |
| `ARGUS_ALLOWED_ORIGINS` | Additional exact browser origins, comma-separated; no wildcards |
| `HOST`, `PORT` | Bind address for `python -m argus.server`: `127.0.0.1`, `8000` |
| `NEXT_PUBLIC_API_URL` | Frontend backend URL; unset in a production build selects the static demo |

The **Server default** UI choice uses the normal configuration chain. Explicit hosted UI choices use
provider-specific defaults and `ARGUS_OPENAI_*` / `ARGUS_ANTHROPIC_*` settings. When switching the server
provider, defaults replace local model/URL settings; explicit model/URL values at the same precedence
level override them. Do not export a local model or localhost endpoint while selecting a hosted API.

## HTTP API

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health`, `/health` | Liveness |
| GET | `/api/ready`, `/ready` | Queue capacity and configured-provider readiness |
| GET | `/api/providers` | Selectable providers, model names, and whether hosted keys are configured; no keys returned |
| GET | `/api/repositories/search?q=graph%20coloring` | Up to eight public, non-archived GitHub search results |
| POST | `/api/batches` | Validate, deduplicate, and queue 1–50 repositories |
| GET | `/api/batches` | Available saved/current batch summaries |
| GET | `/api/batches/{batch_id}` | Queue progress, reports, overlap flags, pairwise evidence |
| GET | `/api/batches/{batch_id}/statistics` | Measured rows and both eligible statistical populations |
| POST | `/api/evaluate` | Legacy single-repository evaluation |
| GET | `/api/jobs/{job_id}` | Individual job progress |
| GET | `/api/evaluations` | Saved individual evaluations |
| GET | `/api/evaluate/{evaluation_id}` | Public JSON report; `/json` is an alias |
| GET | `/api/evaluate/{evaluation_id}/report` | Markdown report |

Example **full** batch, using the configured provider:

```bash
curl -X POST http://127.0.0.1:8000/api/batches \
  -H 'Content-Type: application/json' \
  -d '{"urls":["https://github.com/psf/requests","https://github.com/jawah/niquests"],"provider":"configured","deterministic_only":false}'
```

Use the returned `batch_id` to poll. Explicit provider choices are `configured`, `openai`, or `anthropic`.
The legacy endpoint accepts `url` and `deterministic_only` and uses the server default provider.
Invalid input returns 422; an occupied queue returns 429 with `Retry-After`; unavailable GitHub search
returns 503. Search failure does not prevent evaluation of pasted URLs.

## Reproducible tests

```bash
python -m pytest
npm --prefix ui run lint
npm --prefix ui run build
```

The default Python suite does not need a live model or paid API calls. It exercises real temporary Git
repositories, deterministic collectors/policy, completion states, structured-output validation, redaction,
provider HTTP contracts, batch queue/failure handling, persistence, statistics, and copied-code detection.
Live model tests are separate: `python -m pytest -m live`.

### Controlled copying fixture

```bash
python scripts/test_copied_repos.py
```

Creates two independent temporary Git repositories containing deliberately identical graph-coloring
source, runs real collectors and similarity policy, and saves a clearly labeled batch
`c0c0c0c0c0c0` in `argus-reports`. Select it in the saved-batch picker. Expected: 100% overlap both ways,
both participants flagged, zero in the primary population, two in the population including flags.
This diagnostic intentionally skips AI; it verifies detection, not full reasoning completion. A negative
test verifies that matching README formatting/text without source overlap does not flag a pair.

[`test-cohort/manifest.json`](test-cohort/manifest.json) contains public NP-hard-problem examples.
`scripts/test_public_cohort.py` expects those repositories cloned under `test-cohort/repos` as described
in [`test-cohort/README.md`](test-cohort/README.md). Any synthetic grade plots are explicitly labeled and
are never represented as actual repository grades.

## Architecture and evidence policy

```text
src/argus/
  pipeline.py       acquire → collect → deterministic rules → reason → policy → validate
  collectors/       safe Git access, history, contributors, timeline, CI, hygiene, README, similarity
  evidence.py       evidence store, bounded packets, known IDs
  policy.py         grounding, finding taxonomy, deterministic summary checks
  status.py         completion states and Definition of Done
  report.py         Markdown + JSON from the same validated evaluation
  llm/              Ollama/Qwen/OpenAI/Claude providers, prompts, schema validation and repair
  server.py         API, serial batches, repository discovery, persisted batch summaries
  cohort.py         pairwise comparisons, overlap flags, verified-grade population helpers
  statistics.py     evidence metrics, population filtering, descriptive distributions
  benchmarks.py     validated objective/reference comparison helpers
ui/app/             batch-first interface, reports, statistical charts
```

The model receives structured evidence packets, including relevant repository text where needed,
not an unrestricted repository checkout. Repository text is untrusted input. Every proposed finding
must cite evidence IDs actually provided in the packet. Schema and grounding validation reject unknown
IDs, invalid anomaly references, and unsupported classifications. Deterministic policy decides the
finding type, severity, materiality, and manual-review requirement.

Facts such as a single contributor, missing CI, no LICENSE, or an initial scaffold are not automatically
misconduct. A finding requires a measured rule or configured expectation. AI-tool attribution signals
are observations unless independently grounded rules justify more. Material anomalies retain manual
review even when a model offers a plausible explanation.

Executive summaries are generated from the computed status/counts. A model narrative is optional and
must pass consistency checks; it cannot contradict measured results or replace the deterministic summary.

## Deployment and data handling

Targets are cloned into evaluator-owned temporary directories. ARGUS does not install target dependencies
or execute target scripts, tests, workflows, containers, or binaries. Clone safeguards disable hooks,
submodules, LFS smudging, symlinks, and credential helpers. Evaluation uses read-only Git and static parsers.
Secret indicators are redacted at detection. The API strips checkout paths, local runtime addresses,
and full email addresses from reports. API credentials are read only from the environment.

Reports live in `argus-reports` as `<repository>.<evaluation_id>.md` and `.json`. Completed batch summaries
live beside them as `batch-<id>.json`. Keep these directories on persistent storage when required.
Temporary clones are removed after batch comparison. Historical commits with invalid ISO timezone
offsets use Git's Unix timestamp in UTC; the normalization is recorded in
`deterministic_metrics.commits.timestamp_normalizations` rather than silently dropping history.

The local backend has no user authentication. Its default binding is loopback. CORS allows
`http://localhost:3000` and `http://127.0.0.1:3000` plus explicitly configured origins. CORS is not an
authentication mechanism; add appropriate access control before exposing a live evaluator remotely.

### Static public demo

Without `NEXT_PUBLIC_API_URL` in a production build, the UI shows the saved evaluation bundled under
`ui/public/demo`. It does not contact a backend or run new evaluations. The bundled Qwen3-8B report for
`gegedobruna/data-capstone` is distinct from current local runs. Live batch controls are disabled.

For Vercel, use `ui` as the project root and leave `NEXT_PUBLIC_API_URL` unset. To replace demo data with
a validated saved report:

```bash
python -m argus.demo path/to/report.json
```

A hosted live deployment additionally needs the backend, configured provider, persistent reports,
network access, and access controls. A static frontend alone cannot evaluate repositories.

## Limits and troubleshooting

| Symptom | Check / action |
|---|---|
| UI shows a static demo | Set `NEXT_PUBLIC_API_URL` for the intended frontend environment and restart/rebuild |
| Backend unavailable | Start it from the repository root; check `/health`, API URL, and exact CORS origin |
| AI unavailable | Check `/ready`, Ollama service/model tag, or backend API key and model access |
| Hosted key configured but call fails | Inspect report errors for authentication, quota, timeout, model, or output-validation failure |
| Slow local reasoning | Check RAM/VRAM and CPU fallback; use a model/context that fits, and allow enough time |
| Queue returns 429 | Wait for the active batch; inference is intentionally serial |
| Old batch unavailable after restart | Running queues are not resumed; resubmit. Completed reports and saved batch summaries remain available |
| Incomplete result | Follow [Complete an evaluation](#complete-an-evaluation); do not hide missing mandatory checks |
| Similarity is unavailable | Both repositories must be acquired and contain eligible source/test shingles |
| Shared README, no code flag | Expected: README similarity is advisory |

Additional limits:

- Batch comparisons cover supplied repositories only. CLI similarity covers `--compare` references only.
  ARGUS does not search the entire web for copied projects.
- Token similarity can miss extensive identifier changes or semantic rewrites, and shared templates can
  produce legitimate overlap. It is evidence for review, not a plagiarism verdict.
- Secret scanning checks tracked HEAD content; historical removed env files are identified by path,
  not a complete scan of all historical secret content.
- Meaningful-source and generated/vendor classification use path heuristics. README checks use a fixed
  technology vocabulary. Neither establishes full requirement compliance.
- Optional GitHub metadata may be unavailable due to access/rate limits. scc fallback has no complexity metric.
- Benchmark helpers require matching instances/objectives and independent feasibility evidence.
  Their 10% quality tolerance does not certify solver feasibility, normalize arbitrary hardware, search
  current frontier results automatically, or award assignment points. See
  [`docs/cohort-evaluation-spec.md`](docs/cohort-evaluation-spec.md) for implemented scope and pending grading inputs.
