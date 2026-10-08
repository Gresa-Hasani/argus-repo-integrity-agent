# ARGUS — Repository Forensics & Engineering Integrity Agent

ARGUS evaluates whether a Git/GitHub repository shows a credible, traceable and internally consistent
engineering process. It is one specialised agent in a larger repository-evaluation pack: it surfaces
evidence about history, contributions, provenance and hygiene, and leaves requirement fulfilment, QA and
ML-model judgement to the other agents.

**Measure first, reason second.** Every number in an ARGUS report is computed by deterministic tooling
(Git, the GitHub API, scc, static parsers). A local open-source Qwen3 model served by Ollama — `qwen3:4b` by
default (it fits free hosting), `qwen3:8b` when you have the memory — only interprets structured evidence
packets, and every finding it proposes must cite evidence that exists in the evidence store.

## Requirements

- Python 3.12+
- `git` on `PATH`
- A local inference runtime serving Qwen3. Tested with [Ollama](https://ollama.com):
  ```bash
  ollama pull qwen3:8b
  ```
  ```bash
  ollama pull qwen3:4b
  ```
- Optional: [Boyter scc](https://github.com/boyter/scc) on `PATH` (or `ARGUS_SCC_PATH`). Without it ARGUS uses a
  built-in line counter and says so in the report (no complexity metric).

## Install

```bash
pip install -e ".[dev]"
```

## Usage

```bash
argus evaluate https://github.com/owner/repository
```

```bash
argus evaluate https://github.com/owner/repository --model Qwen3-4B
```

```bash
argus evaluate ./some/local/clone --compare https://github.com/owner/reference --deadline 2026-10-01T18:00:00+02:00
```

Useful flags: `--compare REPO` (repeatable; reference repositories for similarity), `--require-similarity`,
`--similarity-threshold`, `--deadline`, `--backend ollama|openai`, `--base-url`, `--config argus.toml`,
`--out DIR`, `--no-github-api`, `--no-llm`, `--keep-clone`.

The CLI prints the repository, model, progress, modules completed, findings, manual-review requirements,
final status and report location. Reports go to `argus-reports/` as `<repo>.<evaluation_id>.md` and `.json`.

| Exit code | Meaning |
|---|---|
| 0 | `DONE_CLEAN` or `DONE_WITH_FINDINGS` |
| 2 | usage or configuration error |
| 3 | `FLAGGED` |
| 4 | `INCOMPLETE_EVALUATION` |
| 5 | `EVALUATOR_ERROR` |

## Public demo

The frontend in `ui/` deploys to **Vercel (free)** as a fully static page and needs **no backend**.

- It shows a **saved, real ARGUS evaluation**: Qwen3-8B on `https://github.com/gegedobruna/data-capstone`
  (`DONE_WITH_FINDINGS`, 5 findings, 0 integrity flags, no manual review), including the findings with their
  deterministic evidence and advisory AI reasoning, the policy decisions, the model-candidate audit table,
  repository metrics, and the Markdown and JSON reports.
- The data is the evaluator's own output, bundled as static files in `ui/public/demo/` (email addresses are
  masked and local paths removed; nothing else is altered).
- **Nothing is evaluated in the public demo.** The Evaluate form is disabled and says why. The page never
  imitates a live run.

Deploy:

1. Import the repository in Vercel and set **Root Directory** to `ui`.
2. Do **not** set `NEXT_PUBLIC_API_URL`. Its absence is what selects demo mode.
3. Deploy. No environment variables, secrets or other services are needed.

To refresh the bundled result from a newer local evaluation:

```bash
python -m argus.demo argus-reports/<report>.json
```

## Local full evaluation

Run by each team member on their own machine: the FastAPI backend, Ollama and the Qwen3 model stay local.

Prerequisites: Python 3.12+, Node.js 20+, Git, and [Ollama](https://ollama.com/download).

```bash
git clone https://github.com/Gresa-Hasani/argus-repo-integrity-agent.git
```

```bash
cd argus-repo-integrity-agent
```

```bash
pip install -e ".[dev,ui]"
```

```bash
npm --prefix ui install
```

Pull one model. `qwen3:4b` (about 2.5 GB download, about 4 GB RAM) is the default; `qwen3:8b` (about 5 GB
download, about 7 GB RAM) is slower but was used for the saved demo result:

```bash
ollama pull qwen3:4b
```

```bash
ollama pull qwen3:8b
```

Start the backend from the repository root (terminal 1). It listens on `http://localhost:8000`:

```bash
python -m uvicorn argus.server:app --port 8000
```

To use the 8B model instead, set `ARGUS_MODEL` first (PowerShell: `$env:ARGUS_MODEL = "qwen3:8b"`; bash:
`export ARGUS_MODEL=qwen3:8b`).

Start the frontend (terminal 2). `ui/.env.development` points it at `http://localhost:8000`:

```bash
npm --prefix ui run dev
```

Open http://localhost:3000, paste any public GitHub URL (`https://github.com/<owner>/<repository>`) and click
**Evaluate Repository**.

- A **full evaluation** runs every deterministic collector, then the Qwen3 reasoning steps, then the policy
  layer. On a CPU-only laptop expect roughly 30 minutes with `qwen3:4b` and 45 minutes with `qwen3:8b` for a
  repository of about 80 commits. Keep the machine awake.
- **Deterministic evidence only** skips the model and finishes in seconds; because the reasoning checks did
  not run, the result is reported as `INCOMPLETE_EVALUATION`, never as clean.
- **Completed evaluations** lists the results in `argus-reports/` plus the bundled demo result.
- Only one evaluation runs at a time; a second request gets a clear "busy" answer.

The same pipeline is available without the UI: `argus evaluate https://github.com/<owner>/<repository>`.

### Local API

`GET /health` (liveness: `{"status": "ok", "service": "argus"}`), `GET /ready` (accepting evaluations, AI
reasoning available), `POST /api/evaluate`, `GET /api/jobs/{job_id}`, `GET /api/evaluations`,
`GET /api/evaluate/{evaluation_id}`, `GET /api/evaluate/{evaluation_id}/report`,
`GET /api/evaluate/{evaluation_id}/json`.

- Only public `https://github.com/<owner>/<repository>` URLs are accepted; everything else gets the same 422.
- Reports are looked up by evaluation id only; no client-supplied path reaches the filesystem.
- Responses carry no absolute paths, local service URLs, secret values or full email addresses. Failures
  return a fixed message; details stay in the server log.
- CORS allows `http://localhost:3000` plus the exact origins in `ARGUS_ALLOWED_ORIGINS` (no wildcards).
- Jobs are held in memory: restarting the backend loses a running evaluation. Finished reports stay in
  `argus-reports/`.
- `python -m argus.server` binds `HOST`/`PORT` (default `127.0.0.1:8000`).

The frontend is Next.js 16, TypeScript and Tailwind CSS 4; the backend is FastAPI (`src/argus/server.py`)
over the Python pipeline. The frontend is presentation only: every value comes from the ARGUS result.

## Configuration

Precedence: defaults < `argus.toml` (see `argus.example.toml`) < environment (see `.env.example`) < CLI flags.

| Variable | Default | Purpose |
|---|---|---|
| `ARGUS_LLM_PROVIDER` | `qwen` | provider registered behind `LLMProvider` |
| `ARGUS_MODEL` | `qwen3:4b` | model served by the local runtime; `qwen3:8b` also supported (`ARGUS_LLM_MODEL` is still accepted) |
| `ARGUS_FALLBACK_MODEL` | *(none)* | optional; used if the primary is not installed or fails at runtime, and always reported |
| `ARGUS_ALLOWED_ORIGINS` | – | local API: extra browser origins allowed by CORS (exact origins, comma-separated) |
| `NEXT_PUBLIC_API_URL` | *(unset)* | frontend: backend address. Unset = public demo mode; `ui/.env.development` sets `http://localhost:8000` |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | web API bind address for `python -m argus.server` |
| `ARGUS_REPORTS_DIR` | `argus-reports` | where reports are written |
| `ARGUS_LLM_BACKEND` | `ollama` | `ollama`, or `openai` for any OpenAI-compatible local server (vLLM, llama.cpp, LM Studio) |
| `ARGUS_LLM_BASE_URL` | `http://localhost:11434` | runtime address |
| `ARGUS_LLM_TEMPERATURE` / `ARGUS_LLM_MAX_TOKENS` / `ARGUS_LLM_NUM_CTX` | `0.1` / `1536` / `8192` | generation settings |
| `ARGUS_LLM_PACKET_CHARS` | `9000` | evidence-packet size per reasoning step; raise on GPU hardware, lower on slow CPUs |
| `ARGUS_LLM_MODEL_TAG`, `ARGUS_LLM_FALLBACK_MODEL_TAG` | – | exact runtime tag when it cannot be derived from the name |
| `GITHUB_TOKEN` | – | optional; raises the API rate limit and enables PR review detail. Environment only. |

Logical names are mapped to runtime tags (`Qwen3-8B` → `qwen3:8b` on Ollama, `Qwen/Qwen3-8B` on OpenAI-compatible
servers); if that tag is not installed ARGUS looks for an installed model whose name contains the logical
name (e.g. `hf.co/ggml-org/Qwen3-4B-GGUF:Q4_K_M`). Whenever the fallback is used, the report says so and why.

No credentials are stored in this repository. Tokens are read from the environment only and are never
written to reports.

## Architecture

```text
src/argus/
├── cli.py                 argus evaluate …
├── config.py              defaults < file < env < flags
├── pipeline.py            orchestrator: collect → deterministic rules → reason → escalate → decide
├── policy.py              finding taxonomy, candidate validation, observations, summary checks (pure)
├── status.py              completion-state rules + Definition-of-Done (pure functions)
├── report.py              Markdown + JSON from one object, plus report validation
├── server.py              thin FastAPI layer for the web UI (no evaluation logic)
├── demo.py                exports a finished evaluation as static demo data for the public frontend
├── evidence.py            EvidenceStore and evidence-packet builder
├── models.py              Evidence, Anomaly, Finding, Observation, CandidateDecision, AnalysisResult,
│                          CoverageStatus, ManualReviewRequirement, IntegrityAssessment, FinalEvaluation
├── collectors/            DETERMINISTIC LAYER (no LLM, never runs repository code)
│   ├── gitutil.py         URL validation, safe clone, read-only git
│   ├── classify.py        source / tests / config / docs / generated / vendored / lockfile / …
│   ├── scc.py             scc (or labelled built-in fallback), meaningful-LOC estimate
│   ├── commits.py         history parsing, classification, message quality, granularity, inflation
│   ├── contributors.py    identity map, per-contributor metrics, authorship, co-author matrix
│   ├── timeline.py        timeline, late-window share, deadline, branches, merges
│   ├── github.py          repository metadata, pull requests, workflow runs (REST, read-only)
│   ├── ci.py              GitHub Actions parsed and validated against tracked files
│   ├── hygiene.py         structure, .gitignore, env files, redacted secret indicators, dependencies
│   ├── readme.py          README technology claims cross-checked against manifests/paths/source
│   ├── similarity.py      token-shingle containment against reference repositories
│   └── signals.py         explicit AI-tool attribution signals, cross-agent handoffs
└── llm/                   REASONING LAYER
    ├── interface.py       LLMProvider abstraction + provider registry
    ├── providers/qwen.py  QwenProvider with Ollama and OpenAI-compatible backends
    ├── runner.py          prompt + packet → schema-constrained call → validation → one repair retry
    ├── prompts/           system.md + one prompt per reasoning step
    └── schemas/           JSON Schemas exported from the models
```

### Deterministic vs LLM boundary

| Deterministic (authoritative) | LLM (interpretation only) |
|---|---|
| commits, authors, committers, co-authors, timestamps, branches, merges, PR metadata | commit-message and history interpretation |
| LOC, scc statistics, generated/vendored classification | raw-vs-meaningful contribution interpretation |
| identity normalisation, co-author matrix and ratios | whether a co-authorship pattern needs review |
| timeline, late-window share, deadline checks | relating timeline, branches, PRs and code drops |
| CI parsing and workflow/repository consistency | README-vs-implementation in context |
| `.gitignore`, env files, secret patterns, dependency manifests | structure coherence |
| similarity calculation and the 70 % threshold rule | provenance interpretation |
| completion status and Definition of Done | cross-evidence synthesis, executive summary |

Rules with no room for interpretation are applied in code, not by the model: committed credential
indicators, similarity at or above the threshold (`SIMILARITY_THRESHOLD_EXCEEDED`, manual review, never a
plagiarism verdict), committed env files and dependency directories, workflow/repository mismatches.

### How model output is kept honest

1. The model never sees the repository, only an evidence packet built from the evidence store (source code
   is not sent). If a packet must be shortened, the omission count is stated inside the packet.
2. The JSON Schema passed to the runtime for constrained decoding is narrowed per call: `evidence_ids` and
   `anomaly_id` are enums of the ids in that packet.
3. The response is validated with Pydantic and then checked for grounding: every cited id must be in the
   packet and in the store, every finding needs at least one, categories/severities must be valid enums.
4. On failure there is one controlled repair retry carrying the validation error. If that fails too, the
   step is marked failed: the affected modules become `UNVERIFIABLE`, an evaluator error is recorded and
   the evaluation ends as `EVALUATOR_ERROR`. Nothing is inferred on the model's behalf.
5. Structural validity is not enough. Every candidate then goes through the deterministic policy layer
   described next, which decides whether it is a finding at all.

### Finding taxonomy and the policy layer

The model only proposes *candidates*. `policy.py` classifies each one from the evidence it cites — never
from its wording, its proposed severity or its request for manual review:

```text
FACT → OBSERVATION → ENGINEERING_WEAKNESS → ANOMALY → MATERIAL_INTEGRITY_CONCERN
```

| Type | Meaning | Where it appears | Outcome |
|---|---|---|---|
| `NORMAL` | ordinary repository characteristic | discarded; listed only in the policy audit table | – |
| `OBSERVATION` | fact worth showing a reviewer | *Repository Observations* (not a finding, not counted) | – |
| `ENGINEERING_WEAKNESS` | genuine engineering failure with a measured basis | *Engineering Weaknesses* | `FAIL` |
| `ANOMALY` | deterministically detected pattern, not material | *Integrity Findings* | `PASS` |
| `MATERIAL_INTEGRITY_CONCERN` | material pattern or hard rule; needs a human | *Integrity Findings* / *Security Findings* | `REVIEW` or `UNVERIFIABLE` |

A candidate becomes a finding only if a deterministic basis exists, and that basis is recorded on the
finding (`deterministic_basis`); the model's text is kept separately as `llm_reasoning`.

- **Anomaly-anchored categories** (co-authorship, contribution, LOC, commit inflation, timeline, branch
  workflow): a finding exists only if it cites an anomaly pattern that a collector detected. Category
  and severity come from the anomaly, not from the model. One non-material anomaly gives `ANOMALY`; a
  material anomaly, or two or more combined, gives `MATERIAL_INTEGRITY_CONCERN`.
- **README_MISMATCH**: valid only for a claim the deterministic cross-check marked `CONTRADICTED`
  (presence fully determined by tracked files, none exist, and the README states it without
  qualification). A `VERIFIED` claim can never produce a mismatch.
- **Commit traceability**: a weakness only when at least 5 commits exist and at least 30 % of messages
  are low-information.
- **Hygiene, CI, secrets, similarity**: raised by deterministic rules only; a model candidate there can
  add reasoning to an existing finding and is otherwise discarded.
- **AI assistance**: at most an observation, and only with explicit attribution signals.

So facts such as a single contributor, a single commit, an initial scaffold commit, lockfile-heavy LOC,
no co-authorship, no CI, no tests, no LICENSE, no pull requests or no further activity are reported as
observations generated from the metrics. They cannot become findings unless a rule or an expectation you
configured (for example `--deadline`) makes them one.

The model is never the final authority on materiality, integrity flags, manual-review requirements,
severity or status. In particular, a model "explanation" for a *material* anomaly is advisory: it is
attached to the finding, and the manual-review requirement stays.

### Executive summary

The summary in the report is generated deterministically from the computed result. The model may add a
narrative, which is accepted only if it is consistent with the final status, the integrity-flag,
manual-review, evaluator-error and coverage-gap counts, uses no accusatory language, and contains no
number that is absent from its evidence packet. A contradictory narrative is rejected (after one repair
attempt), the rejection is shown in the report, and the computed result is unaffected. The same checks
run again on the evaluation object and on the rendered Markdown before a report is trusted.

### Anomaly lifecycle

Collectors register anomaly patterns (`OBSERVED`, or `CORROBORATED` when backed by several evidence
items). A non-material anomaly can be `RESOLVED` by a reasoning step with an evidence-grounded
explanation, or `ASSESSED` when a finding cites it. A material anomaly always ends as a finding that
requires manual review: `REVIEW` if a model offered an (advisory) explanation, `UNVERIFIABLE` if nothing
explained it. Evaluator failures live in a separate `errors` list.

### Completion states

Evaluated in this order:

| Status | When |
|---|---|
| `EVALUATOR_ERROR` | ARGUS itself failed: collector exception, model unavailable, reasoning step failed, inconsistent report |
| `INCOMPLETE_EVALUATION` | a mandatory check is `UNVERIFIABLE` (repository or history unavailable, `--no-llm`, required similarity missing) |
| `FLAGGED` | an open material finding exists (material anomaly, committed credential indicator, similarity at or above the threshold) |
| `DONE_WITH_FINDINGS` | only engineering weaknesses or non-material anomalies, or optional checks unverifiable |
| `DONE_CLEAN` | every check completed, no findings, no manual review, no errors, no unverifiable module (observations do not count) |

The status is computed from deterministic inputs only. A reasoning step can still cause
`EVALUATOR_ERROR` by failing, but it cannot produce `FLAGGED` or prevent it.

Optional checks are those whose evidence lives outside the Git repository (`repository_metadata`,
`pull_requests`, GitHub Actions run history). `similarity_analysis` and `code_provenance` become mandatory
with `--require-similarity`.

## Safety

The target repository is untrusted input. ARGUS only accepts `https://github.com/<owner>/<repo>` URLs or an
existing local directory, clones into its own temporary directory without submodules, LFS smudging, hooks,
symlinks or credential helpers, and from then on only runs read-only `git` commands and static parsers. It
never installs dependencies or runs scripts, binaries, workflows or containers from the repository.
Secret indicators are redacted at the point of detection. Repository text that reaches the model (README
excerpts, commit messages) is marked as untrusted data in the system prompt.

## Tests

```bash
python -m pytest
```

The default suite needs no model runtime: it builds throwaway Git repositories and drives the pipeline
with a scripted provider. `tests/test_regression.py` replays the candidates Qwen3-8B actually produced in
live runs and pins the policy that rejects them. The suite covers clean → `DONE_CLEAN`, anomalies → `DONE_WITH_FINDINGS` / `FLAGGED`,
missing evidence → `INCOMPLETE_EVALUATION`, model failure → `EVALUATOR_ERROR`, invalid JSON, repair on
retry, hallucinated evidence, similarity above threshold, redaction and report consistency.

```bash
python -m pytest -m live
```

runs a real evaluation with each installed Qwen3 model (skipped per model if it is not installed).

## Known limits

- Similarity is measured only against repositories you pass with `--compare`. ARGUS does not search the
  web for similar projects; without references the similarity module is `NOT_APPLICABLE` (or a mandatory
  gap with `--require-similarity`) and the report states that provenance was not verified.
- Secret scanning covers tracked files at the evaluated HEAD. History is checked for removed env files by
  path, not by content.
- Meaningful-LOC figures and the generated/vendored split come from path heuristics and are estimates.
- README claims are detected from a fixed technology vocabulary; claims outside it are not checked.
- The built-in line counter is a fallback for scc, not a replacement.
- Pull-request review detail is fetched only when `GITHUB_TOKEN` is set.
