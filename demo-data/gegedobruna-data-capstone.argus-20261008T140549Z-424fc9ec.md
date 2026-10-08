# ARGUS Repository Forensics Report

**Repository:** gegedobruna/data-capstone  
**Evaluated HEAD:** `4b3dcb3f00b515b4223373905c6d8346f19fc3bd`  
**Model:** Qwen3-8B (`qwen3:8b`)  
**Evaluation:** `argus-20261008T140549Z-424fc9ec` at 2026-10-08T14:05:49+00:00  
**Status:** **DONE_WITH_FINDINGS**  
**Manual review required:** NO

## 1. Executive Summary

ARGUS evaluated gegedobruna/data-capstone and the evaluation status is DONE_WITH_FINDINGS. The repository has 83 commit(s) by 8 human contributor(s) on 2 branch(es), with 9,292 raw code LOC of which 4,274 is estimated to be meaningful source. 1 engineering weakness(es), 4 integrity finding(s) and 0 security finding(s) are open; 0 of them are material. No manual review is required. All applicable checks completed with no evaluator errors and no coverage gaps. Status basis: non-material finding: ARGUS-HYGIENE-001 [MEDIUM] Environment file committed to the repository; non-material finding: ARGUS-INFLATION-001 [LOW] Whitespace-Only Commit; non-material finding: ARGUS-COMMIT-001 [LOW] Timestamp Divergence.

_Authoritative summary: deterministic. Model narrative: ACCEPTED._

**Model narrative** (advisory; checked for consistency with the computed result):

> The repository gedgedobruna/data-capstone has been evaluated and is marked as DONE_WITH_FINDINGS. The evaluation identified several non-material findings, including an environment file committed to the repository, a whitespace-only commit, a timestamp divergence, an unusual co-authorship pattern for Gresa-Hasani, and a large merge late in the timeline. The repository has 83 commits, 8 human contributors, and 51 tracked files. It contains 9,292 raw code LOC, with an estimated 4,274 meaningful source LOC. The repository has 2 branches and 7 merge commits, with 28 pull requests on GitHub. Healthy signals include descriptive commit messages, tests introduced in a commit, a CI workflow, and a .gitignore file. No LICENSE file was found, and no AI-tool attribution was present in the commit history. Manual review is not required.

| Open findings | Engineering weaknesses | Integrity findings | Security findings | Integrity flags (material) | Manual-review requirements | Evaluator errors | Mandatory coverage gaps |
|---|---|---|---|---|---|---|---|
| 5 | 1 | 4 | 0 | 0 | 0 | 0 | 0 |

## 2. Repository Snapshot

| Field | Value |
|---|---|
| Repository | gegedobruna/data-capstone |
| Input | https://github.com/gegedobruna/data-capstone |
| Normalized URL | https://github.com/gegedobruna/data-capstone |
| Acquisition | git clone (full history, no submodules, no LFS smudge, hooks disabled) — succeeded in 9.41s |
| Default branch | main |
| Evaluated SHA | 4b3dcb3f00b515b4223373905c6d8346f19fc3bd |
| Visibility | public |
| Created | 2026-06-06T13:35:13Z |
| Fork / template of | n/a |
| Tracked files | 51 |
| Code LOC (raw) | 9,292 |
| Meaningful source LOC (estimate) | 4,274 |
| Commits | 83 |
| Human contributors | 8 |
| Branches | 2 |
| Languages | JSON, Python, Jupyter, YAML, CSS, Markdown |
| CI/CD workflows | 1 |
| Test files | 3 |

## 3. SCC / Codebase Composition

Tool: **builtin** — scc not found on PATH; used ARGUS built-in line counter (no complexity metric).

| Language | Files | Lines | Code | Comments | Blanks |
|---|---|---|---|---|---|
| JSON | 2 | 4,134 | 4,134 | 0 | 0 |
| Python | 12 | 2,759 | 2,198 | 157 | 404 |
| Jupyter | 5 | 1,754 | 1,753 | 0 | 1 |
| YAML | 10 | 470 | 341 | 81 | 48 |
| CSS | 1 | 404 | 323 | 16 | 65 |
| Markdown | 2 | 427 | 319 | 0 | 108 |
| Other | 12 | 265 | 215 | 0 | 50 |
| Plain Text | 2 | 9 | 9 | 0 | 0 |

| Content class | Files | Code LOC |
|---|---|---|
| source | 15 | 3,714 |
| tests | 3 | 560 |
| config | 22 | 4,657 |
| ci | 2 | 41 |
| docs | 3 | 319 |
| other | 1 | 1 |

- raw_code_LOC: **9,292**
- meaningful_source_LOC_estimate: **4,274** (source + tests; path-based estimate, not exact)
- excluded_LOC: **5,018**

- config: 4,657 LOC excluded — supporting content (config/docs/CI), not application source
- docs: 319 LOC excluded — supporting content (config/docs/CI), not application source
- ci: 41 LOC excluded — supporting content (config/docs/CI), not application source
- other: 1 LOC excluded — supporting content (config/docs/CI), not application source

## 4. Contributor Analysis

| ID | Contributor | Kind | Identities | Merge basis | Confidence |
|---|---|---|---|---|---|
| C1 | Gegë Dobruna | human | Gege Dobruna <g***@gmail.com>, Gegë Dobruna <g***@gmail.com>, gegedobruna <g***@gmail.com> | identical email g***@gmail.com | HIGH |
| C2 | Gresa-Hasani | human | Gresa-Hasani <1***@users.noreply.github.com>, Gresa-Hasani <g***@gmail.com> | GitHub noreply address matches name/login of the other identity | MEDIUM |
| C3 | flandercanaj | human | flandercanaj <1***@users.noreply.github.com> | single identity | HIGH |
| C4 | ErzaAdemi14 | human | Erza Ademi <a***@gmail.com>, ErzaAdemi14 <1***@users.noreply.github.com>, ErzaAdemi14 <a***@gmail.com> | GitHub noreply address matches name/login of the other identity, identical email a***@gmail.com | MEDIUM |
| C5 | ErzenC | human | ErzenC <e***@gmail.com> | single identity | HIGH |
| C6 | Flander Canaj | human | Flander Canaj <f***@gmail.com> | single identity | HIGH |
| C7 | Bledi Rexha | human | Bledi Rexha <b***@gmail.com>, bledirexha <2***@users.noreply.github.com>, bledirexha <b***@gmail.com> | GitHub noreply address matches name/login of the other identity, identical email b***@gmail.com | MEDIUM |
| C8 | Isaku1 | human | Isaku1 <i***@gmail.com> | single identity | HIGH |
| C9 | GitHub | platform | GitHub <n***@github.com> | single identity | HIGH |

**Gegë Dobruna** (human) — active 2026-06-06T15:35:13+02:00 → 2026-06-22T14:15:03+02:00 on 9 day(s); components: validation, app, ingestion, (root), transformation; languages: Jupyter, Python; tests +0, docs +30, config/CI +443, generated/vendored/lock/data +400.

**Gresa-Hasani** (human) — active 2026-06-16T16:37:28+02:00 → 2026-06-23T14:51:58+02:00 on 5 day(s); components: (root), app, assets, tests; languages: Python, CSS; tests +400, docs +0, config/CI +37, generated/vendored/lock/data +0.

**flandercanaj** (human) — active 2026-06-15T12:01:32+02:00 → 2026-06-23T14:46:20+02:00 on 5 day(s); components: (root), tests, app; languages: Python; tests +167, docs +0, config/CI +372, generated/vendored/lock/data +0.

**ErzaAdemi14** (human) — active 2026-06-11T15:23:36+02:00 → 2026-06-23T14:46:20+02:00 on 6 day(s); components: transformation, tests; languages: Jupyter, Python; tests +154, docs +1, config/CI +0, generated/vendored/lock/data +0.

**ErzenC** (human) — active 2026-06-13T13:01:02+00:00 → 2026-06-17T17:21:54+02:00 on 4 day(s); components: validation; languages: Jupyter; tests +0, docs +0, config/CI +0, generated/vendored/lock/data +0.

**Flander Canaj** (human) — active 2026-06-17T17:07:05+02:00 → 2026-06-21T23:33:08+02:00 on 2 day(s); components: src/transformations, (root), src/ingestion, ingestion; languages: Python, Jupyter; tests +0, docs +0, config/CI +4,250, generated/vendored/lock/data +0.

**Bledi Rexha** (human) — active 2026-06-11T00:49:21+02:00 → 2026-06-23T15:20:08+02:00 on 6 day(s); components: ingestion, (root); languages: Jupyter, Python; tests +0, docs +399, config/CI +0, generated/vendored/lock/data +0.

**Isaku1** (human) — active 2026-06-10T00:03:58+02:00 → 2026-06-17T17:21:54+02:00 on 3 day(s); components: chatbot; languages: Jupyter; tests +0, docs +0, config/CI +0, generated/vendored/lock/data +0.

_Commit counts and LOC are forensic signals, not measures of developer quality._

## 5. Commit Quality

| Metric | Value |
|---|---|
| Commits (all refs) | 83 |
| Non-merge | 76 |
| Merge | 7 |
| Low-information messages | 0 (0%) |
| Conventional-commit style | 0.00% |
| Median lines changed | 59 |
| Large commits | 1 |

| Class | Commits |
|---|---|
| FEATURE | 27 |
| CONFIGURATION | 24 |
| BUG_FIX | 9 |
| MERGE | 7 |
| UNCLEAR | 3 |
| DOCUMENTATION | 3 |
| GENERATED_CODE | 3 |
| CI_CD | 3 |
| TEST | 3 |
| REFACTOR | 1 |

| SHA | Author | Files | +Raw | +Meaningful | +Non-original | Share of meaningful | Message |
|---|---|---|---|---|---|---|---|
| f4f6e36623 | Flander Canaj | 3 | 4,134 | 0 | 0 | 0.00% | [R2] Replacing dashboard and chatbot folders |

## 6. Authorship & Co-Authorship

Author ≠ committer on 59 commit(s): 36 via platform/bot committers, 23 between human identities.

Co-authored commits: **13** (17% of non-merge commits); malformed trailers: 0.

| Contributor | Kind | Own authored commits | Co-authored appearances | Total appearances | Co-author ratio |
|---|---|---|---|---|---|
| Gegë Dobruna | human | 30 | 1 | 31 | 3.23% |
| Gresa-Hasani | human | 20 | 7 | 27 | 25.93% |
| flandercanaj | human | 13 | 2 | 15 | 13.33% |
| ErzaAdemi14 | human | 6 | 2 | 8 | 25.00% |
| ErzenC | human | 5 | 3 | 8 | 37.50% |
| Flander Canaj | human | 4 | 1 | 5 | 20.00% |
| Bledi Rexha | human | 3 | 4 | 7 | 57.14% |
| Isaku1 | human | 2 | 1 | 3 | 33.33% |

- Gresa-Hasani: 5 of 7 co-authored commits change 5 lines or fewer

## 7. Contribution Integrity

| Indicator | Value |
|---|---|
| Empty commits | 0 |
| Whitespace-only commits | 1 |
| Commits changing ≤2 lines | 11 (14%) |
| Revert commits | 0 |
| Trivial README-only commits | 0 |
| Rapid single-file bursts | 0 |

Anomaly patterns detected: 4; resolved with an evidence-grounded explanation: 0; escalated unresolved: 0.

> The repository shows a mix of raw and meaningful activity, with some anomalies that may indicate potential issues in contribution integrity and timeline. The evidence suggests a collaborative environment, but certain patterns require further review.
>
> _Integrity synthesis by the reasoning model._

| Anomaly | Category | Material | Lifecycle | Pattern | Resolution |
|---|---|---|---|---|---|
| AN-001 | COMMIT_INFLATION | no | ASSESSED | Commits with little or no semantic effect: 1 whitespace-only commit(s). Roughly 1% of non-merge commits are affected. | - |
| AN-002 | COAUTHOR_INTEGRITY | no | ASSESSED | Unusual co-authorship pattern for Gresa-Hasani: Gresa-Hasani: 5 of 7 co-authored commits change 5 lines or fewer. Co-authorship alone is never proof of misconduct. | - |
| AN-003 | COMMIT_INTEGRITY | no | ASSESSED | Author and committer timestamps diverge: 4 commit(s) were authored more than a day before being committed; 0 have an author date later than the commit date. Timestamps are client-supplied. | - |
| AN-004 | BRANCH_WORKFLOW | no | ASSESSED | Large merge late in the timeline: 1 merge(s) of 3000+ insertions landed in the final 10% of the project duration. | - |

## 8. Timeline Analysis

| Metric | Value |
|---|---|
| First commit | 2026-06-06T15:35:13+02:00 |
| Last commit | 2026-06-23T15:20:08+02:00 |
| Duration (hours) | 407.75 |
| Active days | 13 |
| Commits per active day | 5.85 |
| Deadline | n/a |
| Commits after deadline | 0 |
| Late window | final 10% of the observed project duration (no deadline configured) |
| Meaningful additions in late window | 1,749 of 7,416 (24%) |

| Milestone | Commit | Time | Message |
|---|---|---|---|
| initial_commit | 79907eef18 | 2026-06-06T15:35:13+02:00 | [R1] Initial commit |
| tests_introduced | d0e9e2d5b3 | 2026-06-23T14:33:42+02:00 | [R4] test: add unit tests for VAL-02 null and whitespace normalization pr commit |
| ci_introduced | 79bf0871f4 | 2026-06-06T17:30:16+02:00 | [R1] Initialize folder structure |
| readme_introduced | 79907eef18 | 2026-06-06T15:35:13+02:00 | [R1] Initial commit |
| final_activity | 4b3dcb3f00 | 2026-06-23T15:20:08+02:00 | [R3] fix(alerts): add summary badge for triggered/total counts |

| Date (UTC) | Commits | +Raw | +Meaningful | Authors |
|---|---|---|---|---|
| 2026-06-06 | 5 | 263 | 0 | Gege Dobruna, Gegë Dobruna |
| 2026-06-08 | 1 | 145 | 0 | Gegë Dobruna |
| 2026-06-09 | 3 | 400 | 0 | Gegë Dobruna, Isaku1 |
| 2026-06-10 | 1 | 87 | 87 | bledirexha |
| 2026-06-11 | 1 | 172 | 171 | ErzaAdemi14 |
| 2026-06-12 | 1 | 4 | 0 | Gegë Dobruna |
| 2026-06-13 | 3 | 790 | 790 | ErzaAdemi14, ErzenC |
| 2026-06-15 | 7 | 1,387 | 1,347 | ErzaAdemi14, ErzenC, Gegë Dobruna, gegedobruna |
| 2026-06-16 | 15 | 2,465 | 2,259 | ErzaAdemi14, ErzenC, Gresa-Hasani, Isaku1, flandercanaj, gegedobruna |
| 2026-06-17 | 8 | 1,034 | 898 | Flander Canaj, Gege Dobruna, Gresa-Hasani |
| 2026-06-21 | 18 | 5,268 | 932 | Flander Canaj, Gegë Dobruna, Gresa-Hasani, flandercanaj |
| 2026-06-22 | 8 | 603 | 204 | Bledi Rexha, Gege Dobruna, Gresa-Hasani |
| 2026-06-23 | 5 | 731 | 728 | Bledi Rexha, ErzaAdemi14, Gresa-Hasani, flandercanaj |

## 9. Branch & Collaboration Workflow

branches and/or merges present. Unmerged: none. Stale: none. Tags: 0.

| Branch | Default | Ahead | Behind | Merged | Last commit | Last author |
|---|---|---|---|---|---|---|
| dev |  | 0 | 0 | True | 2026-06-23T15:20:08+02:00 | Bledi Rexha |
| main | yes | n/a | n/a | n/a | 2026-06-23T15:20:08+02:00 | Bledi Rexha |

| Merge | Author | Source | PR | Files | + | - | Time |
|---|---|---|---|---|---|---|---|
| 681dd98ee2 | ErzenC | origin/dev | n/a | 0 | 0 | 0 | 2026-06-15T11:03:32+00:00 |
| ed06a1e3e1 | Gegë Dobruna | main | n/a | 3 | 238 | 143 | 2026-06-15T13:08:25+02:00 |
| 4f5bb94039 | Flander Canaj | dev | n/a | 2 | 701 | 0 | 2026-06-17T17:07:46+02:00 |
| da165670d0 | Gegë Dobruna | main | n/a | 1 | 31 | 0 | 2026-06-17T17:20:45+02:00 |
| 753e5ba430 | Gegë Dobruna | n/a | n/a | 24 | 3,262 | 23 | 2026-06-17T17:21:54+02:00 |
| 051c01adea | Gegë Dobruna | n/a | n/a | 1 | 182 | 179 | 2026-06-17T17:36:37+02:00 |
| 9877fb1624 | Gegë Dobruna | dev | 84 | 5 | 4,136 | 3 | 2026-06-21T23:34:42+02:00 |

Pull requests: 28 (23 merged), authors: ErzaAdemi14, ErzenC, Isaku1, bledirexha, flandercanaj, gegedobruna.

| # | Title | Author | State | Merged | Head → Base |
|---|---|---|---|---|---|
| 90 | test: add unit tests for VAL-02 null and whitespace normaliz | ErzaAdemi14 | closed | False | dev → main |
| 89 | update README.md | bledirexha | closed | False | dev → main |
| 88 | fix(alerts): use cached store and add summary badge | bledirexha | closed | True | fix/alerts-store-rendering → dev |
| 87 | Update file path for metadata governance dashboard | flandercanaj | closed | False | flandercanaj-patch-2 → main |
| 86 | Remove Databricks host and token from .env | flandercanaj | closed | True | flandercanaj-patch-1-1 → main |
| 85 | Add .env file from template | flandercanaj | closed | True | flandercanaj-patch-1 → main |
| 84 | Dev | flandercanaj | closed | True | dev → main |
| 83 | Dev 1 | flandercanaj | closed | True | dev-1 → main |
| 82 | Dev | flandercanaj | closed | True | dev → main |
| 81 | [R8] Update genie_client.py | gegedobruna | closed | True | dev → main |
| 80 | Merge dev into main — R2/R3/R4/R5/R6/R8 final deliverables | gegedobruna | closed | True | dev → main |
| 79 | [R5] Silver Layer | ErzaAdemi14 | closed | False | dev → main |
| 78 | [R4] Updated Gold-Layer | ErzenC | closed | True | dev → main |
| 77 | [R5] - Updates silver layer | ErzaAdemi14 | closed | True | feature/silver-update → main |
| 76 | [R5] Fixes silver layer | ErzaAdemi14 | closed | True | erza-azure-validation → main |

GitHub API coverage (unauthenticated): metadata=SUCCESS, pull_requests=SUCCESS, pull_request_reviews=NOT_APPLICABLE, workflow_runs=SUCCESS, workflows=SUCCESS, branches=SUCCESS, contributors=SUCCESS, releases=EMPTY, commits=NOT_APPLICABLE, issues=NOT_APPLICABLE

## 10. GitHub Actions / CI-CD

| Workflow | Name | Triggers | Jobs | Capabilities | Secrets referenced |
|---|---|---|---|---|---|
| .github/workflows/main.yml | Databricks CI/CD | pull_request, push, workflow_dispatch | validate-deploy-run | deploy | DATABRICKS_HOST, DATABRICKS_TOKEN |

_Workflow commands are consistent with tracked files (static check)._

Run history: {'cancelled': 4, 'success': 9, 'failure': 10} over 23 sampled run(s).

## 11. Repository Hygiene

- `.gitignore`: present; missing expected patterns: none
- Tracked files that are normally ignored: none
- Environment files tracked: .env; real env files: 1; removed but in history: 0
- Dependency manifests: requirements.txt; lockfiles: none
- Dependency issues: none

- Generated / non-original files tracked: binary: 5

## 12. Project Structure

Ecosystems: Python. README: True; LICENSE: False; tests: True; Dockerfile: False.

| Component | Files |
|---|---|
| (root) | 10 |
| docs | 6 |
| resources | 6 |
| app | 5 |
| tests | 4 |
| .github | 3 |
| chatbot | 3 |
| config | 2 |
| ingestion | 2 |
| src/transformations | 2 |
| transformation | 2 |
| validation | 2 |
| assets | 1 |
| dashboards | 1 |
| infrastructure | 1 |

> The repository has a structured layout with Python as the primary ecosystem, but some hygiene and organization concerns are present.

## 13. README vs Implementation

`README.md` (21,495 chars). Keyword-detected technology mentions cross-checked against manifests, tracked paths and source patterns. Statuses are deterministic and cannot be overridden by the model. CONTRADICTED is assigned only when presence is fully determined by tracked files, none exist, and the README states the technology without qualification.

| Claim (technology mentioned) | Status | Supporting evidence | Evidence ID |
|---|---|---|---|
| GitHub Actions / CI | VERIFIED | matching files tracked: .github/workflows/main.yml | EV-README_CLAIM-001 |
| Authentication | PARTIALLY_VERIFIED | usage pattern found in source/config | EV-README_CLAIM-002 |
| AWS | NOT_VERIFIED | none found | EV-README_CLAIM-003 |

> The README claims the project uses GitHub Actions for CI/CD and mentions authentication via OAuth2 and Service Principal, which are partially verified. It also claims AWS usage, which is not verified. The repository has one CI workflow, consistent with the claims.

## 14. Code Provenance & Similarity

Threshold for manual review: **70%**. Method: Token 6-gram containment over files classified as source/tests (files with fewer than 20 shingles skipped). Excludes vendored, generated, build output, minified, lockfiles, datasets, binaries, configuration, documentation and CI files.

No comparison performed: no reference repositories supplied (--compare); ARGUS does not perform open-web similarity search. Provenance is therefore **not verified** by similarity evidence.

## 15. AI-Assistance Signals

Classification: **LOW** (observable evidence only; never an estimate of how much code was generated).

| Signal | Value |
|---|---|
| AI-tool identities in history | - |
| Commits with explicit AI attribution | 0 |
| Commits with AI-tool markers in message | 0 |
| AI-assistant config files | - |
| Placeholder markers in source | 0 |
| Comment ratio | 2.66% |

_Explicit attribution (trailers, tool config files) is direct evidence of AI tool usage. Style-based indicators are weak and cannot establish that code was AI-generated._

## 16. Repository Observations

_Plain facts about the repository. These are not findings and do not affect the status._

- 8 human contributors [EV-CONTRIBUTOR-001, EV-CONTRIBUTOR-002, EV-CONTRIBUTOR-003]
- 83 commits over 407.75 hours on 13 active day(s) [EV-TIMELINE-001]
- No deadline or expected milestone configured: timing of activity is not assessed against any expectation
- Co-authorship: 13 commit(s) carry Co-authored-by trailers [EV-COAUTHORSHIP-001]
- Branches and/or merges present (2 branch(es), 7 merge commit(s)) [EV-BRANCHES-001]
- No LICENSE file [EV-STRUCTURE-001]
- Codebase composition: 9,292 raw code LOC, of which 4,274 is meaningful source (estimate); the remainder is config 4,657, docs 319, ci 41, other 1
- No AI-tool attribution in commit history [EV-AI_SIGNALS-001]
- No similarity comparison supplied: provenance is not verified by similarity evidence
- README technology mentions without full supporting evidence: Authentication (PARTIALLY_VERIFIED), AWS (NOT_VERIFIED) [EV-README_CLAIM-002, EV-README_CLAIM-003]

## 17. Engineering Weaknesses

### ARGUS-HYGIENE-001 — [MEDIUM] Environment file committed to the repository

- **Type:** ENGINEERING_WEAKNESS · category REPOSITORY_HYGIENE · material: no
- **Proposed by:** deterministic; accepted by the deterministic policy layer
- **Deterministic basis:** deterministic rule: Environment file committed to the repository
- **Observation:** 1 real environment file(s) are tracked (.env); 1 contain non-empty variables.
- **Evidence:**
  - `EV-ENVIRONMENT-001` (environment): 1 real env file(s) tracked; 0 removed env file(s) remain in history (values not recorded)
- **Interpretation (deterministic):** Environment files normally stay untracked with a committed .env.example.
- **Interpretation (model, advisory):** The presence of a `.env` file in the tracked files indicates that environment variables are committed, which is a security risk.
- **Confidence:** HIGH (0.95)
- **Manual review required:** no
- **Status:** OPEN · lifecycle ASSESSED · outcome FAIL

## 18. Integrity Findings

_Anomalies and material integrity concerns. Each one is anchored in a deterministically detected pattern; none is a verdict._

### ARGUS-BRANCH-001 — [LOW] Large Merge Late in Timeline

- **Type:** ANOMALY · category BRANCH_WORKFLOW · material: no
- **Proposed by:** llm (step `integrity_synthesis`); accepted by the deterministic policy layer
- **Deterministic basis:** anomaly AN-004 (non-material): Large merge late in the timeline
- **Observation:** A large merge was made late in the project timeline, which may indicate a potential issue in the branch workflow.
- **Evidence:**
  - `AN-004` (anomaly): Large merge late in the timeline: 1 merge(s) of 3000+ insertions landed in the final 10% of the project duration.
- **Interpretation (model, advisory):** The large merge of 3000+ insertions landed in the final 10% of the project duration, which could suggest a late integration of a significant feature.
- **Confidence:** MEDIUM (0.70)
- **Manual review required:** no
- **Status:** OPEN · lifecycle ASSESSED · outcome PASS

### ARGUS-COAUTHOR-001 — [LOW] Unusual co-authorship pattern for Gresa-Hasani

- **Type:** ANOMALY · category COAUTHOR_INTEGRITY · material: no
- **Proposed by:** llm (step `authorship_analysis`); accepted by the deterministic policy layer
- **Deterministic basis:** anomaly AN-002 (non-material): Unusual co-authorship pattern for Gresa-Hasani
- **Observation:** Gresa-Hasani is a co-author on 7 commits, with 5 of these commits changing 5 lines or fewer, which may indicate a pattern that requires manual review.
- **Evidence:**
  - `AN-002` (anomaly): Unusual co-authorship pattern for Gresa-Hasani: Gresa-Hasani: 5 of 7 co-authored commits change 5 lines or fewer. Co-authorship alone is never proof of misconduct.
  - `EV-COAUTHORSHIP-001` (coauthorship): 13 commits carry Co-authored-by trailers
  - `EV-CONTRIBUTOR-002` (contributor): Gresa-Hasani (human): 20 authored, 7 co-authored, +2621 raw / +2584 meaningful (est.)
- **Interpretation (model, advisory):** The co-authorship pattern for Gresa-Hasani is unusual, with a high coauthor ratio and minimal code changes in some co-authored commits. This could suggest either pair programming or potential attribution padding.
- **Possible explanations:** Pair programming; Shared implementation or joint debugging; Attribution padding
- **Confidence:** HIGH (0.80)
- **Manual review required:** no
- **Status:** OPEN · lifecycle ASSESSED · outcome PASS

### ARGUS-COMMIT-001 — [LOW] Timestamp Divergence

- **Type:** ANOMALY · category COMMIT_INTEGRITY · material: no
- **Proposed by:** llm (step `commit_analysis`); accepted by the deterministic policy layer
- **Deterministic basis:** anomaly AN-003 (non-material): Author and committer timestamps diverge
- **Observation:** Four commits have author timestamps that are more than a day before their commit dates, which may indicate rebase, amend, or cherry-pick activity.
- **Evidence:**
  - `AN-003` (anomaly): Author and committer timestamps diverge: 4 commit(s) were authored more than a day before being committed; 0 have an author date later than the commit date. Timestamps are client-supplied.
  - `EV-TIMELINE-001` (timeline): 83 commits over 407.75h across 13 active day(s)
  - `EV-COMMIT-013` (commit): timestamp divergence in 064c6fa35b
  - `EV-COMMIT-014` (commit): timestamp divergence in 057fd66a47
  - `EV-COMMIT-015` (commit): timestamp divergence in 3b312a6f21
  - `EV-COMMIT-016` (commit): timestamp divergence in c785d9453b
- **Interpretation (model, advisory):** The timestamps suggest that some commits were authored earlier than they were committed, which could be due to local clock issues or rebase/amend workflows.
- **Possible explanations:** Rebase, amend or cherry-pick; Patches applied later; Incorrect local clock
- **Confidence:** HIGH (0.90)
- **Manual review required:** no
- **Status:** OPEN · lifecycle ASSESSED · outcome PASS

### ARGUS-INFLATION-001 — [LOW] Whitespace-Only Commit

- **Type:** ANOMALY · category COMMIT_INFLATION · material: no
- **Proposed by:** llm (step `commit_analysis`); accepted by the deterministic policy layer
- **Deterministic basis:** anomaly AN-001 (non-material): Commits with little or no semantic effect
- **Observation:** A whitespace-only commit was identified, which may indicate an accidental or automated change with little semantic effect.
- **Evidence:**
  - `AN-001` (anomaly): Commits with little or no semantic effect: 1 whitespace-only commit(s). Roughly 1% of non-merge commits are affected.
  - `EV-COMMIT_INFLATION-001` (commit_inflation): commit-count inflation indicators (counts, not intent)
  - `EV-COMMIT-002` (commit): whitespace-only commit b406368341
- **Interpretation (model, advisory):** The commit 'b406368341' adds no meaningful content and is classified as a FEATURE, which is unusual for a whitespace-only change.
- **Possible explanations:** Editing files through the GitHub web UI; Triggering CI re-runs; Incremental save-style workflow
- **Confidence:** HIGH (0.85)
- **Manual review required:** no
- **Status:** OPEN · lifecycle ASSESSED · outcome PASS

## 19. Security Findings

None (static secret-pattern scan of tracked files at HEAD).

## 20. Manual Review Requirements

None.

## 21. Contributor Evidence Matrix

| Contributor | Authored commits | Co-authored appearances | Meaningful commits | Raw LOC (+/-) | Meaningful LOC estimate (+) | Active days | Components | Integrity flags |
|---|---|---|---|---|---|---|---|---|
| Gegë Dobruna | 30 | 1 | 7 | +1,646 / -160 | 772 | 9 | validation, app, ingestion, (root), transformation | none |
| Gresa-Hasani | 20 | 7 | 17 | +2,621 / -423 | 2,584 | 5 | (root), app, assets, tests | none |
| flandercanaj | 13 | 2 | 2 | +1,004 / -322 | 632 | 5 | (root), tests, app | none |
| ErzaAdemi14 | 6 | 2 | 6 | +975 / -193 | 974 | 6 | transformation, tests | none |
| ErzenC | 5 | 3 | 4 | +971 / -181 | 971 | 4 | validation | none |
| Flander Canaj | 4 | 1 | 1 | +4,966 / -38 | 716 | 2 | src/transformations, (root), src/ingestion, ingestion | none |
| Bledi Rexha | 3 | 4 | 2 | +493 / -3 | 94 | 6 | ingestion, (root) | none |
| Isaku1 | 2 | 1 | 1 | +673 / -0 | 673 | 3 | chatbot | none |

_Not ranked. "Meaningful commits" counts commits classified FEATURE, BUG_FIX, REFACTOR or TEST._

## 22. Healthy Engineering Signals

- Descriptive commit messages: 0% low-information messages across 76 commits
- Development spread over 13 active days
- Tests are present and were introduced at commit d0e9e2d5b3
- 1 CI workflow(s) consistent with the repository (deploy)
- .gitignore present and no build/dependency artefacts committed
- No credential indicators found in tracked files
- Branch-based workflow: 2 branch(es), 7 merge commit(s)
- 28 pull request(s) on GitHub

## 23. Unverifiable Items, Errors and Policy Decisions

No unverifiable items.

**Cross-agent handoffs:**

- REQUIREMENT_EVIDENCE → Requirements Fulfillment Agent (CI/CD pipeline: PRESENT)
- REQUIREMENT_EVIDENCE → Requirements Fulfillment Agent (Automated tests: PRESENT)
- REQUIREMENT_EVIDENCE → Requirements Fulfillment Agent (README technology claims: PARTIAL)

**Model candidates and what the deterministic policy did with them:**

| ID | Step | Candidate | Proposed | Decision | Type | Reason |
|---|---|---|---|---|---|---|
| CAND-001 | reconnaissance | Environment file committed to the repository | REPOSITORY_HYGIENE / MEDIUM | MERGED → ARGUS-HYGIENE-001 | ENGINEERING_WEAKNESS | already raised by a deterministic rule; model reasoning attached |
| CAND-002 | reconnaissance | High proportion of configuration files | REPOSITORY_HYGIENE / LOW / review | DISCARDED | NORMAL | REPOSITORY_HYGIENE findings are raised by deterministic rules; no rule fired on the cited evidence |
| CAND-003 | commit_analysis | Whitespace-Only Commit | COMMIT_INTEGRITY / LOW / review | ACCEPTED → ARGUS-INFLATION-001 | ANOMALY | anchored in a deterministically detected anomaly |
| CAND-004 | commit_analysis | Timestamp Divergence | COMMIT_INTEGRITY / LOW / review | ACCEPTED → ARGUS-COMMIT-001 | ANOMALY | anchored in a deterministically detected anomaly |
| CAND-005 | commit_analysis | Large Commit Detected | COMMIT_INTEGRITY / LOW / review | DISCARDED | NORMAL | commit metrics do not show a traceability weakness (needs >=5 commits and >=30% low-information messages) |
| CAND-006 | contribution_analysis | High raw additions with low meaningful contributions | LOC_INFLATION / LOW / review | DISCARDED | NORMAL | LOC_INFLATION requires a deterministically detected anomaly pattern; none is cited, so this is an ordinary repository characteristic |
| CAND-007 | contribution_analysis | Uneven contribution distribution | CONTRIBUTION_INTEGRITY / MEDIUM / review | DISCARDED | NORMAL | CONTRIBUTION_INTEGRITY requires a deterministically detected anomaly pattern; none is cited, so this is an ordinary repository characteristic |
| CAND-008 | contribution_analysis | High co-authorship ratio | CONTRIBUTION_INTEGRITY / LOW / review | DISCARDED | NORMAL | CONTRIBUTION_INTEGRITY requires a deterministically detected anomaly pattern; none is cited, so this is an ordinary repository characteristic |
| CAND-009 | authorship_analysis | Unusual co-authorship pattern for Gresa-Hasani | COAUTHOR_INTEGRITY / MEDIUM / review | ACCEPTED → ARGUS-COAUTHOR-001 | ANOMALY | anchored in a deterministically detected anomaly |
| CAND-010 | timeline_analysis | Large code additions in final window | TIMELINE_ANOMALY / MEDIUM / review | DISCARDED | NORMAL | TIMELINE_ANOMALY requires a deterministically detected anomaly pattern; none is cited, so this is an ordinary repository characteristic |
| CAND-011 | timeline_analysis | Divergent timestamps on commits | COMMIT_INTEGRITY / LOW | MERGED → ARGUS-COMMIT-001 | ANOMALY | anchored in a deterministically detected anomaly |
| CAND-012 | ai_signal_analysis | No explicit AI-assisted development signals | AI_ASSISTANCE / INFO | DISCARDED | NORMAL | no explicit AI-tool attribution in the evidence; style is not evidence |
| CAND-013 | ai_signal_analysis | Weak indirect indicators of AI-assisted development | AI_ASSISTANCE / INFO | DISCARDED | NORMAL | no explicit AI-tool attribution in the evidence; style is not evidence |
| CAND-014 | readme_crosscheck | README_MISMATCH | README_MISMATCH / LOW / review | DISCARDED | NORMAL | README_MISMATCH is valid only for a CONTRADICTED claim; deterministic cross-check says: AWS=NOT_VERIFIED |
| CAND-015 | readme_crosscheck | CI/CD Claim Verified | CI_CD / INFO | DISCARDED | NORMAL | CI_CD findings are raised by deterministic rules; no rule fired on the cited evidence |
| CAND-016 | readme_crosscheck | Authentication Claim Partially Verified | SECRET_EXPOSURE / LOW / review | DISCARDED | NORMAL | SECRET_EXPOSURE findings are raised by deterministic rules; no rule fired on the cited evidence |
| CAND-017 | integrity_synthesis | Unusual Contribution Patterns | CONTRIBUTION_INTEGRITY / MEDIUM / review | MERGED → ARGUS-COAUTHOR-001 | ANOMALY | anchored in a deterministically detected anomaly |
| CAND-018 | integrity_synthesis | Large Merge Late in Timeline | TIMELINE_ANOMALY / LOW / review | ACCEPTED → ARGUS-BRANCH-001 | ANOMALY | anchored in a deterministically detected anomaly |

## 24. Definition of Done

| Module | Status | Mandatory | Detail |
|---|---|---|---|
| repository_access | PASS | yes | full-history clone into an evaluator-owned directory |
| repository_identity | PASS | yes | gegedobruna/data-capstone@4b3dcb3f00b5 on main |
| repository_metadata | PASS | no | GitHub REST API |
| scc_analysis | PASS | yes | scc not found on PATH; used ARGUS built-in line counter (no complexity metric) |
| source_classification | PASS | yes | path-based classification; meaningful LOC is an estimate |
| contributors | PASS | yes | deterministic metrics interpreted by 'contribution_analysis' |
| identity_normalization | PASS | yes | deterministic metrics interpreted by 'authorship_analysis' |
| authorship | PASS | yes | deterministic metrics interpreted by 'authorship_analysis' |
| coauthorship | PASS | yes | deterministic metrics interpreted by 'authorship_analysis' |
| commit_quality | PASS | yes | deterministic metrics interpreted by 'commit_analysis' |
| commit_granularity | PASS | yes | deterministic metrics interpreted by 'commit_analysis' |
| commit_inflation | PASS | yes | deterministic metrics interpreted by 'commit_analysis' |
| loc_analysis | PASS | yes | deterministic metrics interpreted by 'contribution_analysis' |
| loc_inflation | PASS | yes | deterministic metrics interpreted by 'contribution_analysis' |
| contribution_integrity | PASS | yes | deterministic metrics interpreted by 'integrity_synthesis' |
| timeline | PASS | yes | deterministic metrics interpreted by 'timeline_analysis' |
| branches | PASS | yes | deterministic metrics interpreted by 'timeline_analysis' |
| merges | PASS | yes | deterministic metrics interpreted by 'timeline_analysis' |
| pull_requests | PASS | no | 28 pull request(s) |
| github_actions | PASS | no | 1 workflow(s) parsed |
| actions_consistency | PASS | yes | 0 mismatch(es) between workflows and repository |
| repository_structure | PASS | yes | deterministic metrics interpreted by 'reconnaissance' |
| gitignore | PASS | yes | present |
| environment_hygiene | FAIL | yes | 1 real env file(s) tracked; example file absent |
| secret_scan | PASS | yes | 0 indicator(s) in tracked files at HEAD; tracked files at evaluated HEAD (history contents are not scanned; removed env files are listed under environment) |
| dependency_hygiene | PASS | yes | 0 issue(s) |
| readme_crosscheck | PASS | yes | deterministic metrics interpreted by 'readme_crosscheck' |
| ai_assistance_signals | PASS | yes | deterministic metrics interpreted by 'ai_signal_analysis' |
| code_provenance | NOT_APPLICABLE | no | no similarity comparison and no declared fork/template: provenance not investigated beyond history signals |
| similarity_analysis | NOT_APPLICABLE | no | no reference repositories supplied (--compare); ARGUS does not perform open-web similarity search |
| cross_agent_handoffs | PASS | yes | 3 handoff event(s) prepared |
| report_generation | PASS | yes | JSON and Markdown rendered from one evaluation object |
| report_validation | PASS | yes | Definition-of-Done validator |

- non-material finding: ARGUS-HYGIENE-001 [MEDIUM] Environment file committed to the repository
- non-material finding: ARGUS-INFLATION-001 [LOW] Whitespace-Only Commit
- non-material finding: ARGUS-COMMIT-001 [LOW] Timestamp Divergence
- non-material finding: ARGUS-COAUTHOR-001 [LOW] Unusual co-authorship pattern for Gresa-Hasani
- non-material finding: ARGUS-BRANCH-001 [LOW] Large Merge Late in Timeline

## 25. Final Status

```text
ARGUS EVALUATION COMPLETE

Repository: gegedobruna/data-capstone
Evaluated HEAD: 4b3dcb3f00b515b4223373905c6d8346f19fc3bd
Model: Qwen3-8B

Required checks: 31
Completed checks: 31
Not applicable: 2
Unverifiable: 0
Failed checks: 1

Engineering weaknesses: 1
Integrity findings: 4
Security findings: 0
Critical findings: 0
High findings: 0
Integrity flags: 0
Manual-review requirements: 0
Evaluator errors: 0

Evaluation Status: DONE_WITH_FINDINGS
Definition of Done: SATISFIED
```
