# Repository profiling and task-based cross-validation

Status: implemented in the integrity pipeline, CLI, HTTP API, saved reports, and batch results.
This layer is descriptive and task-relative. It does not replace integrity findings, code-overlap
cross-validation, completion statuses, or academic grading. The existing cohort grading specification
in [`cohort-evaluation-spec.md`](cohort-evaluation-spec.md) remains a separate layer.

## Scope and separation from integrity

ARGUS evaluates repositories with two independent comparison layers:

1. **Integrity and provenance.** History, contribution, hygiene, README claims, CI, and pairwise
   code containment. These determine findings, coverage, and completion status.
2. **Task profile and peer context.** A static profile of what the repository contains, an explicit
   task identity, requirement coverage, and an explainable score with optional peer percentiles.

Profiling never changes the integrity completion status. A profile or task-scoring error is recorded
in `profiling_error`; the individual report and its integrity result remain available. Task scoring
runs only when a task is configured. The repository profile is built for every successful evaluation.

Task cross-validation does **not** train a model, create train/validation folds, or use a held-out
label. It compares repository *content and task identity*, then reports peer percentiles as
descriptive context. The term "cross-validation" here means repository-to-repository comparison, not
machine-learning cross-validation or label leakage.

## What the profile contains

`RepositoryProfile` is built from tracked files, not from the repository name or README alone:

- metadata supplied by the evaluator (owner, name, default branch, evaluated commit, visibility);
- language inventory and code share from scc, or ARGUS's labelled built-in line counter;
- runtime and development dependencies parsed from common manifests (Python, Node.js, Rust, Go,
  Java/Kotlin, PHP and Ruby);
- structure: tracked/source/test/config/documentation/CI counts, top-level components, ecosystems;
- architecture: entry points, layered/component patterns, HTTP API, CLI, database, frontend, worker,
  library, container, and deployment indicators inferred from paths, dependencies, and symbols;
- features: declared HTTP routes, CLI commands, source modules, models/schemas, and other static
  implementation units, each with file evidence and confidence;
- testing: test files, static test-case estimate, test frameworks, test/source ratio, CI test
  execution, coverage configuration, and limitations;
- quality: file size, complexity when scc supplies it, module size, comment ratio, lint/type
  configuration, TODO density, documentation, and dependency-managed indicators;
- documentation: README presence/length/headings/summary, documentation files, licence files;
- task coverage for explicit task requirements;
- confidence, evidence fingerprint, evidence index, sources, and limitations.

The profiler reads at most 700 source/test files and 250 KB per file; larger inputs are truncated by
design. It never executes repository code. Unsupported languages and manifests remain visible as
missing evidence rather than being guessed.

### Requirement coverage

Each explicit requirement is tokenised and matched against implementation vocabulary extracted from
source files (paths, symbols, routes, and content terms). Statuses are:

| Status | Meaning |
|---|---|
| `COVERED` | At least 70% weighted requirement-term coverage with implementation evidence |
| `PARTIAL` | 40–70% weighted coverage with implementation evidence |
| `MISSING` | Weak implementation match, or no implementation match |
| `UNVERIFIED` | Documentation-only mention, no source vocabulary, or requirement too generic to assess |

README and documentation terms are tracked separately. A documentation-only match is always
`UNVERIFIED` and contributes no covered score. This prevents a README claim such as "Kubernetes
deployment is planned" from becoming evidence that the feature exists. Conversely, absence of
matching terminology is reported as a coverage gap, not proof that a feature cannot exist under
different wording.

## Task identity and grouping

A `TaskDefinition` has an `id`, `description`, optional `title`, `category`, `requirements`, and
`aliases`. Assignments map a normalised repository key (`owner/repository`) to a task id.

Assignment precedence is:

1. **Caller assignment** — always authoritative, recorded as `EXPLICIT` with relevance and confidence
   1.0 even when the repository content only weakly corroborates the description. A single configured
   task is also applied explicitly to every repository.
2. **Inferred assignment** — the task description, requirements, and title are compared with the
   profile's features, symbols, paths, dependencies, architecture, and documentation headings. The
   result is `SEMANTIC` at or above the relevance threshold (default **0.62**), `UNCERTAIN` between
   78% of that threshold and the threshold, and `UNRELATED` below it. Only `EXPLICIT` and `SEMANTIC`
   assignments participate in task scoring.

Task similarity is deterministic and content-based. It combines normalised-token query coverage,
TF cosine, character 4-gram Dice, and sequence ratio over task text. Pairwise task comparison weights
description 0.55, requirements 0.33, title 0.07, and category 0.05; missing components are removed and
the remaining weights renormalise. Task definitions whose similarity reaches the configured threshold
(default **0.70**) are merged transitively into one `TaskGroup`; pairs are reported with their
component scores. Repository names, languages, and frameworks never participate in task identity or
grouping.

## Peer selection

For each evaluated profile, ARGUS considers only repositories in the same task group whose own
assignment is `EXPLICIT` or `SEMANTIC`. Everything else is excluded with a reason and relation:

- a different task group is `UNRELATED` or `UNCERTAIN`;
- a peer whose task identity was not established is `UNCERTAIN`;
- a duplicate profile is marked `duplicate: true` and `comparable: false`.

Duplicates are detected by case-insensitive repository identity or identical evidence fingerprint.
Only the first occurrence represents the repository; later copies never enter peer statistics. This
avoids double counting a repository submitted twice and avoids treating a copied submission as an
independent peer. The trade-off is deliberate: two genuinely different repositories with identical
scanned source fingerprints are also treated as duplicates.

There is no comparison across unrelated tasks merely because two repositories use the same language
or framework.

## Scoring

### Absolute layer

Five absolute criteria are computed from profile evidence:

| Criterion id | Default weight | Source |
|---|---:|---|
| `task_requirement_fulfillment` | 0.35 | Mean weighted coverage of assessed requirements; `UNVERIFIED` excluded |
| `functional_completeness` | 0.20 | 85% status mean (`COVERED`=1, `PARTIAL`=0.5, `MISSING`=0) + 15% evidence depth |
| `code_quality_maintainability` | 0.15 | Static quality indicators with internal normalisation |
| `testing_quality` | 0.15 | Static test inventory, ratios, CI test execution, coverage configuration |
| `architecture_implementation` | 0.15 | Coherent architecture, entry points, modularity, configuration |

Missing components are omitted and remaining weights renormalise. The absolute score is therefore
`None` when no criterion is measurable. Each `CriterionScore` includes its score, weight, confidence,
explanation, evidence paths, and limitations. The response also reports how much of the configured
weight was measurable.

### Relative layer

Peer context is a leave-one-out percentile over comparable repositories. For each measurable
criterion, the target's percentile is `(below + 0.5 × equal) / peer_count`; peer values include only
task-relevant, non-duplicate peers. The relative score is the weighted mean of those percentiles,
renormalised over the criteria measurable for the target.

Relative context is used only when at least `peer_minimum` peers are available (default **2**) and at
least one shared criterion is measurable. Fewer peers do not lower the score. When relative context
is used:

```text
final = absolute × (1 − peer_context_weight) + relative × peer_context_weight
```

`peer_context_weight` defaults to **0.15** and is capped at **0.5**, so absolute task fulfilment always
remains the primary term. Set it to `0` to disable peer influence.

### Statuses

| Status | Meaning |
|---|---|
| `COMPARED` | Absolute and relative layers both available |
| `ABSOLUTE_ONLY` | No comparable peer; final score equals the absolute score |
| `INSUFFICIENT_PEERS` | Fewer than the configured minimum peers; final score remains absolute |
| `INSUFFICIENT_DATA` | Absolute score unavailable, or peers exist but no shared measurable criterion |
| `TASK_NOT_ESTABLISHED` | Assignment is `UNCERTAIN` or `UNRELATED`; no comparative score |

### Confidence and explanation

The task-evaluation confidence combines profile confidence (0.40), assignment confidence (0.25),
peer sufficiency (0.20, capped at the minimum), and measurable criterion coverage (0.15). Confidence
is reported numerically and as `LOW`/`MEDIUM`/`HIGH`; it is not a probability that the repository is
correct. `limitations` records small cohorts, missing criteria, absent peer context, static-evidence
constraints, duplicate exclusions, and documentation-only evidence.

Every evaluation includes strengths, weaknesses, missing and partial requirements, peer criterion
deltas, shared strengths, and an explanation of how the final score was formed.

## Configuration

Precedence is **defaults < `argus.toml` < environment < CLI flags**.

### TOML

```toml
[task]
id = "inventory"
title = "Inventory service"
category = "backend"
description = "Build an inventory REST API with stock reservation and an audit log."
requirements = ["stock reservation endpoint", "audit log"]
relevance_threshold = 0.62
similarity_threshold = 0.70

[task.assignments]
"owner/inventory-service" = "inventory"

[scoring]
peer_context_weight = 0.15
peer_minimum = 2

[scoring.weights]
task_requirement_fulfillment = 0.35
functional_completeness = 0.20
code_quality_maintainability = 0.15
testing_quality = 0.15
architecture_implementation = 0.15
```

For multiple tasks use `[[task.definitions]]` objects instead of the single `description` fields.
See [`argus.example.toml`](../argus.example.toml) for both forms. Assignments reference task ids that
must exist; unknown ids and duplicate ids are rejected.

### Environment

| Variable | Value |
|---|---|
| `ARGUS_TASK_ID`, `ARGUS_TASK_TITLE`, `ARGUS_TASK_CATEGORY` | Single-task identity |
| `ARGUS_TASK_DESCRIPTION` | Single-task description; enables task scoring |
| `ARGUS_TASK_REQUIREMENTS` | JSON array of requirement strings |
| `ARGUS_TASK_DEFINITIONS` | JSON array of task definition objects |
| `ARGUS_TASK_ASSIGNMENTS` | JSON object mapping repository keys to task ids |
| `ARGUS_TASK_RELEVANCE_THRESHOLD` | Inferred-assignment threshold, default `0.62` |
| `ARGUS_TASK_SIMILARITY_THRESHOLD` | Task-equivalence threshold, default `0.70` |
| `ARGUS_SCORING_WEIGHTS` | JSON object of criterion weights |
| `ARGUS_PEER_CONTEXT_WEIGHT` | Peer share of final score, `0`–`0.5`, default `0.15` |
| `ARGUS_PEER_MINIMUM` | Minimum comparable peers, default `2` |

### CLI

```bash
argus evaluate https://github.com/owner/repository \
  --task 'Build an inventory REST API with stock reservation' \
  --task-id inventory \
  --task-requirement 'stock reservation endpoint' \
  --task-requirement 'audit log' \
  --peer-minimum 2 \
  --peer-context-weight 0.15
```

Additional options: `--task-file` (JSON or TOML task payload), `--task-title`, `--task-category`,
`--task-assignment REPO=TASK` (repeatable), `--task-relevance-threshold`,
`--task-similarity-threshold`, `--scoring-weight CRITERION=WEIGHT` (repeatable), `--peer-context-weight`,
and `--peer-minimum`. A multi-repository CLI run prints a cohort task summary after the individual
evaluations and rewrites each report with its peer evaluation.

### HTTP API

The batch and legacy single-evaluation endpoints accept an optional `task` object:

```json
{
  "urls": [
    "https://github.com/owner/inventory-service",
    "https://github.com/owner/other-inventory"
  ],
  "deterministic_only": false,
  "task": {
    "id": "inventory",
    "description": "Build an inventory REST API with stock reservation.",
    "requirements": ["stock reservation endpoint", "audit log"],
    "assignments": {"owner/inventory-service": "inventory"},
    "peer_minimum": 2,
    "peer_context_weight": 0.15
  }
}
```

Use `definitions` (or `tasks`) with a list of task objects for multiple tasks. The same object also
accepts `relevance_threshold`, `similarity_threshold`, and `scoring_weights`. Invalid weights,
thresholds, or assignment references return HTTP 422. The completed batch exposes
`task_cross_validation`; an auxiliary task failure sets `task_cross_validation_error` without
discarding the individual reports.

## Output

`FinalEvaluation` gains three optional fields that keep older saved reports loadable:

- `repository_profile` — the full profile described above;
- `task_evaluation` — assignment, criteria, peer comparisons, absolute/relative/final scores, status,
  confidence, and limitations;
- `profiling_error` — an auxiliary failure message, if any.

Batch results add `task_cross_validation` and `task_cross_validation_error`. Markdown reports include
section **26. Repository Profile and Task-Based Cross-Validation** without renumbering sections
1–25. The section renders profile metadata, languages, dependencies, features, requirement coverage,
absolute and relative scores, comparable and excluded peers, and criterion-level explanations.
`TaskCrossValidationResult` additionally reports task groups, pairwise task similarities, all
assignments, thresholds, scoring weights, and cohort-level limitations.

## Edge cases

| Situation | Behaviour |
|---|---|
| Inaccessible or missing path | Profile construction raises; pipeline records `profiling_error`; integrity result is unchanged |
| Empty repository or no source | Profile exists; quality/functional criteria are `None`; limitations name the missing evidence |
| Missing README/metadata | Documentation is marked absent; requirement matches found only in docs stay `UNVERIFIED` |
| Unsupported language/manifest | Language and files remain visible; dependency parsing is skipped for unrecognised manifests rather than guessed |
| Multiple languages | Language shares and mixed-stack architecture indicators are reported; no single language is assumed |
| Ambiguous task | `UNCERTAIN`/`UNRELATED`; no peer comparison and `TASK_NOT_ESTABLISHED` |
| Task described only by a name | No requirements are invented; requirement fulfilment is not scored |
| Fewer than minimum peers | `INSUFFICIENT_PEERS`; absolute score stands |
| Duplicate repository/profile | Later copy excluded from peer statistics and marked `duplicate` |
| Profile/task auxiliary error | Recorded without changing completion status; other repositories continue |
| GitHub rate limits or transient acquisition errors | Handled by the existing acquisition/retry layer before profiling; no profile is fabricated |
| Old saved report | Loads because the new fields are optional |

## Limits and non-goals

- Matching is lexical and structural, not semantic embeddings or an LLM judgement. Renamed features
  and unusual terminology can be missed; weak term matches are never promoted to implementation.
- No repository code, tests, or services are executed, so runtime correctness, security, performance,
  and test results are not claimed.
- A profile cannot prove absence of a feature; `MISSING` means the current static vocabulary did not
  support it.
- Peer percentiles are descriptive for a small, task-relevant cohort. They are not statistical
  significance tests and do not establish a ranking beyond the observed cohort.
- Code-overlap cross-validation in `cohort.py` remains the separate provenance layer. Task grouping
  never replaces it, and shared task wording never creates a code-overlap flag.
- This layer does not award grades, points, or extra credit. Use the rubric and benchmark layers in
  [`cohort-evaluation-spec.md`](cohort-evaluation-spec.md) for grading decisions.
- Dependency versions are declared versions. Resolution, vulnerability assessment, and licence
  compatibility are out of scope.

## Reproducibility and tests

Profiles are deterministic apart from timestamps and evaluator-supplied metadata; the same tracked
content yields the same fingerprint, features, criteria, and scores. Task similarity uses no random
state or external model.
`tests/test_task_profiling.py` covers source-based profiling, README-only non-evidence, missing
README/empty source/inaccessible paths, reproducibility, task similarity and grouping, explicit
assignment precedence, task-relevant peer filtering, insufficient peers, duplicates, configuration
layers, pipeline integration, CLI cohort summaries, and API propagation.
