"""Evaluation orchestrator: deterministic evidence first, then LLM reasoning over evidence packets."""

from __future__ import annotations

import re
import shutil
import time
import tempfile
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from argus import __version__
from argus.collectors import ci as ci_mod
from argus.collectors import commits as commits_mod
from argus.collectors import contributors as contributors_mod
from argus.collectors import github as github_mod
from argus.collectors import hygiene as hygiene_mod
from argus.collectors import readme as readme_mod
from argus.collectors import scc as scc_mod
from argus.collectors import signals as signals_mod
from argus.collectors import similarity as similarity_mod
from argus.collectors import timeline as timeline_mod
from argus.collectors.gitutil import RepositoryAccessError, RepoSource, clone, default_branch, git, parse_source, tracked_files
from argus.config import Config
from argus.evidence import EvidenceStore, build_packet
from argus.llm.interface import LLMProvider, LLMUnavailableError, create_provider
from argus.llm.runner import LLMStepError, PolicyRejection, run_step
from argus.models import (
    SEVERITY_RANK,
    AnalysisResult,
    Category,
    CompletionStatus,
    CandidateDecision,
    CoverageStatus,
    EvaluatorError,
    FinalEvaluation,
    Finding,
    FindingStatus,
    FindingType,
    IntegrityAssessment,
    Lifecycle,
    ManualReviewRequirement,
    ModuleStatus,
    NarrativeResult,
    Observation,
    Outcome,
    Severity,
    confidence_level,
)
from argus.policy import assess_candidate, deterministic_summary, numbers_in, outcome_for, reason_codes, repository_observations, sanitize_advisory, summary_problems
from argus.status import MODULES, decide, is_mandatory, open_findings

Progress = Callable[[str], None]

_SHORT = {
    Category.COMMIT_INTEGRITY: "COMMIT", Category.CONTRIBUTION_INTEGRITY: "CONTRIB", Category.COAUTHOR_INTEGRITY: "COAUTHOR",
    Category.LOC_INFLATION: "LOC", Category.COMMIT_INFLATION: "INFLATION", Category.CODE_PROVENANCE: "PROVENANCE",
    Category.SIMILARITY: "SIMILARITY", Category.AI_ASSISTANCE: "AI", Category.BRANCH_WORKFLOW: "BRANCH",
    Category.CI_CD: "CI", Category.REPOSITORY_HYGIENE: "HYGIENE", Category.SECRET_EXPOSURE: "SECRET",
    Category.README_MISMATCH: "README", Category.TIMELINE_ANOMALY: "TIMELINE", Category.REPOSITORY_ACCESS: "ACCESS",
    Category.EVALUATOR_ERROR: "EVALUATOR",
}
_INTEGRITY = {
    Category.COMMIT_INTEGRITY, Category.CONTRIBUTION_INTEGRITY, Category.COAUTHOR_INTEGRITY, Category.LOC_INFLATION,
    Category.COMMIT_INFLATION, Category.CODE_PROVENANCE, Category.SIMILARITY, Category.TIMELINE_ANOMALY,
}
AI_CLASSES = ["LOW", "MODERATE", "HIGH", "INSUFFICIENT_EVIDENCE"]

# reasoning step -> modules whose completion depends on it
STEP_MODULES = {
    "reconnaissance": ["repository_structure"],
    "commit_analysis": ["commit_quality", "commit_granularity", "commit_inflation"],
    "contribution_analysis": ["contributors", "loc_analysis", "loc_inflation"],
    "authorship_analysis": ["identity_normalization", "authorship", "coauthorship"],
    "timeline_analysis": ["timeline", "branches", "merges"],
    "provenance_analysis": ["code_provenance"],
    "ai_signal_analysis": ["ai_assistance_signals"],
    "readme_crosscheck": ["readme_crosscheck"],
    "integrity_synthesis": ["contribution_integrity"],
}
STEP_ANOMALY_CATEGORIES = {
    "commit_analysis": {Category.COMMIT_INTEGRITY, Category.COMMIT_INFLATION},
    "contribution_analysis": {Category.CONTRIBUTION_INTEGRITY, Category.LOC_INFLATION},
    "authorship_analysis": {Category.COAUTHOR_INTEGRITY},
    "timeline_analysis": {Category.TIMELINE_ANOMALY, Category.BRANCH_WORKFLOW},
}


class Evaluation:
    def __init__(self, raw_source: str, cfg: Config, provider: Optional[LLMProvider] = None, progress: Optional[Progress] = None) -> None:
        self.cfg = cfg
        self.source: RepoSource = parse_source(raw_source)
        self.provider = provider
        self.progress = progress or (lambda message: None)
        self.store = EvidenceStore()
        self.modules: dict[str, CoverageStatus] = {}
        self.errors: list[EvaluatorError] = []
        self.findings: list[Finding] = []
        self.metrics: dict[str, Any] = {}
        self.llm_analyses: dict[str, Any] = {}
        self.unverifiable: list[str] = []
        self.handoffs: list[dict[str, Any]] = []
        self.model_info: dict[str, Any] = {"provider": cfg.llm_provider, "requested_model": cfg.llm_model, "model": None, "enabled": cfg.llm_enabled}
        self.executive_summary: dict[str, Any] = {"text": "", "origin": "not_produced", "authoritative_summary": "deterministic", "llm_narrative": "", "llm_narrative_status": "NOT_PRODUCED", "narrative_rejection_reasons": [], "llm_narrative_rejection": [], "rejected_narrative": ""}
        self.candidate_decisions: list[CandidateDecision] = []
        self.llm_observations: list[tuple[str, str, list[str]]] = []
        self.integrity_summary = ("", "not_produced")
        self.evaluation_id = f"argus-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
        self.timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.repo: Optional[Path] = None
        self.repository: dict[str, Any] = {
            "input": self.source.raw, "original_url": self.source.raw, "normalized_url": self.source.url, "kind": self.source.kind, "url": self.source.url, "owner": self.source.owner,
            "name": self.source.name, "default_branch": None, "evaluated_head": None, "evaluation_timestamp": self.timestamp,
        }
        self._counters: Counter = Counter()

    # ------------------------------------------------------------------ bookkeeping
    def set(self, module: str, status: ModuleStatus, detail: str = "") -> None:
        self.modules[module] = CoverageStatus(module=module, status=status, mandatory=is_mandatory(module, self.cfg.require_similarity), detail=detail)
        if status == ModuleStatus.UNVERIFIABLE:
            self.unverifiable.append(f"{module}: {detail}")

    def error(self, stage: str, kind: str, message: str) -> None:
        self.errors.append(EvaluatorError(stage=stage, kind=kind, message=message[:800]))
        self.progress(f"  ! evaluator error in {stage}: {kind}")

    def add_finding(
        self, category: Category, severity: Severity, title: str, text: str, evidence_ids: list[str], *, reasoning: str = "",
        llm_reasoning: str = "", confidence: float = 0.9, manual: bool = False, origin: str = "deterministic", step: str = "",
        explanations: Optional[list[str]] = None, outcome: Optional[Outcome] = None, status: FindingStatus = FindingStatus.OPEN,
        finding_type: Optional[FindingType] = None, basis: Optional[list[str]] = None,
    ) -> Finding:
        """Register a finding. Callers are deterministic rules or the policy layer; never the model directly."""
        evidence_ids = list(dict.fromkeys(evidence_ids))
        missing = [e for e in evidence_ids if not self.store.has(e)]
        if missing or not evidence_ids:
            raise ValueError(f"finding '{title}' has no valid evidence (unknown: {missing})")
        if severity == Severity.INFO:
            raise ValueError(f"finding '{title}': INFO-level facts are observations, not findings")
        material = manual or SEVERITY_RANK[severity] >= SEVERITY_RANK[Severity.HIGH]
        if finding_type is None:
            finding_type = FindingType.MATERIAL_INTEGRITY_CONCERN if material else FindingType.ENGINEERING_WEAKNESS
        if (finding_type == FindingType.MATERIAL_INTEGRITY_CONCERN) != material:
            raise ValueError(f"finding '{title}': type {finding_type.value} is inconsistent with material={material}")
        self._counters[category] += 1
        finding = Finding(
            finding_id=f"ARGUS-{_SHORT[category]}-{self._counters[category]:03d}", finding_type=finding_type, category=category,
            severity=severity, title=title, finding=text, material=material, requires_manual_review=material,
            evidence_ids=evidence_ids, evidence=[self.store.get(e) for e in evidence_ids],
            deterministic_basis=basis or [f"deterministic rule: {title}"], reasoning=reasoning, llm_reasoning=llm_reasoning,
            possible_explanations=explanations or [], confidence=confidence, confidence_level=confidence_level(confidence),
            origin=origin, source_step=step, lifecycle=Lifecycle.ASSESSED, outcome=outcome or outcome_for(finding_type, material), status=status,
            text_origin="deterministic",
        )
        self.findings.append(finding)
        for evidence_id in evidence_ids:
            if self.store.has_anomaly(evidence_id):
                anomaly = self.store.anomaly(evidence_id)
                if anomaly.lifecycle != Lifecycle.RESOLVED:
                    anomaly.lifecycle = Lifecycle.ASSESSED
        return finding

    # ------------------------------------------------------------------ run
    def run(self) -> FinalEvaluation:
        work_root = Path(self.cfg.work_dir) if self.cfg.work_dir else Path(tempfile.mkdtemp(prefix="argus-"))
        work_root.mkdir(parents=True, exist_ok=True)
        try:
            self._run(work_root)
        finally:
            if not self.cfg.keep_clone and not self.cfg.work_dir:
                # Not ignore_errors=True: that silently disables onexc, and Git's read-only pack files
                # would then keep every clone on disk.
                try:
                    shutil.rmtree(work_root, onexc=_force_remove)
                except OSError:
                    pass
        return self.finalize()

    def _run(self, work_root: Path) -> None:
        self.progress(f"[1/4] Acquiring repository {self.source.slug}")
        started = time.monotonic()
        acquisition = {
            "method": "git clone (full history, no submodules, no LFS smudge, hooks disabled)" if self.source.kind == "github" else "git clone --no-local of a local repository",
            "checkout_path": str(work_root / "target"), "isolated_from_argus_source": not (work_root / "target").resolve().is_relative_to(Path(__file__).resolve().parents[2]),
            "retained_after_run": bool(self.cfg.keep_clone or self.cfg.work_dir),
        }
        self.repository["acquisition"] = acquisition
        try:
            self.repo = clone(self.source, work_root / "target")
        except RepositoryAccessError as exc:
            acquisition.update(success=False, runtime_s=round(time.monotonic() - started, 2), error=str(exc))
            self.set("repository_access", ModuleStatus.UNVERIFIABLE, str(exc))
            return
        acquisition.update(success=True, runtime_s=round(time.monotonic() - started, 2))
        self.set("repository_access", ModuleStatus.PASS, "full-history clone into an evaluator-owned directory")

        self.progress("[2/4] Collecting deterministic evidence")
        try:
            self._collect_core()
        except Exception as exc:  # an ARGUS failure, not a project failure
            self.error("deterministic_core", "COLLECTOR_EXCEPTION", f"{type(exc).__name__}: {exc}")
            return
        self._collect_optional(work_root)
        self._deterministic_findings()

        self.progress("[3/4] Reasoning over evidence packets")
        self._reason()
        self._escalate_unaddressed_anomalies()

    # ------------------------------------------------------------------ deterministic layer
    def _collect_core(self) -> None:
        repo, store, cfg, m = self.repo, self.store, self.cfg, self.metrics
        branch = default_branch(repo)
        head = git(repo, "rev-parse", "HEAD").strip()
        tracked = tracked_files(repo)
        self.tracked = tracked
        self.repository.update(default_branch=branch, evaluated_head=head)
        self.set("repository_identity", ModuleStatus.PASS, f"{self.source.slug}@{head[:12]} on {branch}")

        self.commits = commits_mod.parse_history(repo, branch)
        if not self.commits:
            raise RuntimeError("git log returned no parsable commits")

        m["scc"] = scc_mod.analyze(repo, tracked, cfg.scc_path)
        scc = m["scc"]
        self.scc_ev = store.add(
            "scc", "scc",
            f"{scc['totals']['code']} code lines in {scc['totals']['files']} counted files; meaningful source estimate {scc['meaningful_source_loc_estimate']} ({scc['tool']})",
            {k: scc[k] for k in ("tool", "totals", "raw_code_loc", "meaningful_source_loc_estimate", "excluded_loc", "excluded_content", "comment_ratio")}
            | {"languages": scc["languages"][:10], "categories": scc["categories"], "directories": scc["directories"][:10]},
        )
        self.set("scc_analysis", ModuleStatus.PASS, scc["tool_note"])
        self.set("source_classification", ModuleStatus.PASS, "path-based classification; meaningful LOC is an estimate")
        self.progress(f"  - code composition: {scc['totals']['code']} code LOC ({scc['tool']})")

        m["commits"] = commits_mod.analyze(repo, self.commits, store, cfg)
        m["contributors"] = contributors_mod.analyze(self.commits, store)
        m["timeline"] = timeline_mod.analyze_timeline(self.commits, store, cfg)
        m["branches"] = timeline_mod.analyze_branches(repo, self.commits, branch, store)
        self.progress(f"  - history: {len(self.commits)} commits, {m['contributors']['human_contributors']} human contributor(s), {m['branches']['branch_count']} branch(es)")

    def _collect_optional(self, work_root: Path) -> None:
        repo, store, cfg, m = self.repo, self.store, self.cfg, self.metrics

        # GitHub metadata -------------------------------------------------------------------
        self.github_ev: Optional[str] = None
        if self.source.kind != "github":
            m["github"] = {"applicable": False, "coverage": {"all": "NOT_APPLICABLE"}}
            self.set("repository_metadata", ModuleStatus.NOT_APPLICABLE, "local repository: no GitHub metadata")
            self.set("pull_requests", ModuleStatus.NOT_APPLICABLE, "local repository: no pull-request data")
        elif not cfg.github_api:
            m["github"] = {"applicable": True, "errors": {"all": "GitHub API disabled by configuration"}, "coverage": {"all": "NOT_APPLICABLE"}}
            self.set("repository_metadata", ModuleStatus.UNVERIFIABLE, "GitHub API disabled by configuration")
            self.set("pull_requests", ModuleStatus.UNVERIFIABLE, "GitHub API disabled by configuration")
        else:
            try:
                gh = github_mod.collect(self.source.owner, self.source.name, cfg.github_token)
            except Exception as exc:
                gh = {"available": {}, "errors": {"all": f"{type(exc).__name__}: {exc}"}}
            gh["applicable"] = True
            m["github"] = gh
            if gh.get("metadata"):
                self.repository.update({k: gh["metadata"].get(k) for k in ("visibility", "created_at", "updated_at", "fork", "parent", "template", "license")})
                self.set("repository_metadata", ModuleStatus.PASS, "GitHub REST API")
            else:
                self.set("repository_metadata", ModuleStatus.UNVERIFIABLE, gh["errors"].get("metadata") or gh["errors"].get("all", "unavailable"))
            if "pull_requests" in gh:
                n = gh["pull_requests"]["count"]
                self.set("pull_requests", ModuleStatus.PASS if n else ModuleStatus.NOT_APPLICABLE, f"{n} pull request(s)")
            else:
                self.set("pull_requests", ModuleStatus.UNVERIFIABLE, gh["errors"].get("pull_requests") or gh["errors"].get("all", "unavailable"))
            gh.setdefault("coverage", {})
            if gh["errors"].get("all"):
                gh["coverage"]["all"] = "ERROR"
            slim = {k: gh.get(k) for k in ("metadata", "workflow_runs", "workflows", "branches", "contributors", "releases", "coverage") if gh.get(k) is not None}
            if "pull_requests" in gh:
                slim["pull_requests"] = {k: v for k, v in gh["pull_requests"].items() if k != "items"} | {"items": gh["pull_requests"]["items"][:12]}
            slim["unavailable"] = gh["errors"]
            self.github_ev = store.add("github", "github", f"GitHub API data ({len(gh['errors'])} endpoint(s) unavailable)", slim)

        # CI ---------------------------------------------------------------------------------
        try:
            m["ci"] = ci_mod.analyze(repo, self.tracked, store)
            ci = m["ci"]
            if not ci["workflow_files"]:
                self.set("github_actions", ModuleStatus.NOT_APPLICABLE, "no GitHub Actions workflows in the repository")
                self.set("actions_consistency", ModuleStatus.NOT_APPLICABLE, "no workflows to validate")
            else:
                gh = m["github"]
                if gh.get("applicable") and "workflow_runs" not in gh:
                    self.set("github_actions", ModuleStatus.UNVERIFIABLE, "workflows parsed statically, but run history is unavailable: " + str(gh["errors"].get("workflow_runs") or gh["errors"].get("all")))
                else:
                    self.set("github_actions", ModuleStatus.PASS, f"{len(ci['workflow_files'])} workflow(s) parsed" + ("" if gh.get("applicable") else "; run history not applicable to a local repository"))
                self.set("actions_consistency", ModuleStatus.FAIL if ci["consistency_findings"] else ModuleStatus.PASS, f"{len(ci['consistency_findings'])} mismatch(es) between workflows and repository")
        except Exception as exc:
            m["ci"] = {"workflow_files": [], "other_ci_files": [], "consistency_findings": [], "workflows": [], "capabilities": [], "evidence": {}}
            self.error("ci", "COLLECTOR_EXCEPTION", f"{type(exc).__name__}: {exc}")
            self.set("github_actions", ModuleStatus.UNVERIFIABLE, "collector failed")
            self.set("actions_consistency", ModuleStatus.UNVERIFIABLE, "collector failed")

        # Hygiene ----------------------------------------------------------------------------
        try:
            m["hygiene"] = hygiene_mod.analyze(repo, self.tracked, self.commits, store)
        except Exception as exc:
            m["hygiene"] = None
            self.error("hygiene", "COLLECTOR_EXCEPTION", f"{type(exc).__name__}: {exc}")
            for module in ("gitignore", "environment_hygiene", "secret_scan", "dependency_hygiene"):
                self.set(module, ModuleStatus.UNVERIFIABLE, "collector failed")

        # README -----------------------------------------------------------------------------
        try:
            m["readme"] = readme_mod.analyze(repo, self.tracked, store)
        except Exception as exc:
            m["readme"] = None
            self.error("readme", "COLLECTOR_EXCEPTION", f"{type(exc).__name__}: {exc}")
            self.set("readme_crosscheck", ModuleStatus.UNVERIFIABLE, "collector failed")

        # Similarity -------------------------------------------------------------------------
        self._similarity(work_root)

        # AI signals and handoffs -------------------------------------------------------------
        try:
            m["ai_signals"] = signals_mod.ai_signals(repo, self.tracked, self.commits, m["contributors"], m["scc"], m["commits"], store)
        except Exception as exc:
            m["ai_signals"] = None
            self.error("ai_signals", "COLLECTOR_EXCEPTION", f"{type(exc).__name__}: {exc}")
            self.set("ai_assistance_signals", ModuleStatus.UNVERIFIABLE, "collector failed")
        try:
            if m["hygiene"] is None or m["readme"] is None:
                raise RuntimeError("inputs unavailable (hygiene/readme collector failed)")
            self.handoffs = signals_mod.handoffs(self.tracked, m["readme"], m["ci"], m["hygiene"], m["similarity"])
            self.set("cross_agent_handoffs", ModuleStatus.PASS, f"{len(self.handoffs)} handoff event(s) prepared")
        except Exception as exc:
            self.set("cross_agent_handoffs", ModuleStatus.UNVERIFIABLE, str(exc))
        self.progress(f"  - evidence store: {len(store.all())} items, {len(store.anomalies())} anomaly pattern(s)")

    def _similarity(self, work_root: Path) -> None:
        cfg, store = self.cfg, self.store
        sim: dict[str, Any] = {"performed": False, "threshold": cfg.similarity_threshold, "threshold_exceeded": False, "method": similarity_mod.METHOD, "comparisons": []}
        self.metrics["similarity"] = sim
        self.similarity_ev: list[str] = []
        if not cfg.compare:
            detail = "no reference repositories supplied (--compare); ARGUS does not perform open-web similarity search"
            sim["note"] = detail
            status = ModuleStatus.UNVERIFIABLE if cfg.require_similarity else ModuleStatus.NOT_APPLICABLE
            self.set("similarity_analysis", status, detail)
            return
        failures = []
        try:
            target = similarity_mod.fingerprint(self.repo, self.tracked)
        except Exception as exc:
            self.error("similarity", "COLLECTOR_EXCEPTION", f"{type(exc).__name__}: {exc}")
            self.set("similarity_analysis", ModuleStatus.UNVERIFIABLE, "fingerprinting failed")
            return
        for index, ref in enumerate(cfg.compare):
            entry: dict[str, Any] = {"comparison_source": ref}
            try:
                ref_source = parse_source(ref)
                ref_repo = clone(ref_source, work_root / f"reference-{index}")
                reference = similarity_mod.fingerprint(ref_repo, tracked_files(ref_repo))
                entry.update(similarity_mod.compare(target, reference, cfg.similarity_threshold))
                entry["methodology"] = similarity_mod.METHOD
                entry["evidence_id"] = store.add(
                    "similarity", "similarity",
                    f"similarity vs {ref}: {entry['similarity_estimate']} over {entry['files_compared']} meaningful source file(s) (threshold {cfg.similarity_threshold})",
                    entry | {"threshold": cfg.similarity_threshold},
                )
                self.similarity_ev.append(entry["evidence_id"])
                sim["performed"] = True
                sim["threshold_exceeded"] = sim["threshold_exceeded"] or entry["threshold_exceeded"]
            except (RepositoryAccessError, ValueError) as exc:
                entry["error"] = str(exc)
                failures.append(f"{ref}: {exc}")
            except Exception as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
                failures.append(f"{ref}: {exc}")
                self.error("similarity", "COLLECTOR_EXCEPTION", entry["error"])
            sim["comparisons"].append(entry)
        if failures:
            self.set("similarity_analysis", ModuleStatus.UNVERIFIABLE, "reference unavailable: " + "; ".join(failures)[:300])
        elif sim["threshold_exceeded"]:
            self.set("similarity_analysis", ModuleStatus.FAIL, "similarity at or above threshold: manual review required")
        else:
            self.set("similarity_analysis", ModuleStatus.PASS, f"{len(sim['comparisons'])} comparison(s) below threshold")

    def _deterministic_findings(self) -> None:
        m, cfg = self.metrics, self.cfg
        hygiene = m.get("hygiene")
        if hygiene:
            ev = hygiene["evidence"]
            # secrets
            real = [h for h in hygiene["secrets"]["indicators"] if h["severity"] != "LOW"]
            by_kind: dict[str, list[dict[str, Any]]] = {}
            for hit in real:
                by_kind.setdefault(hit["kind"], []).append(hit)
            secret_items = {e.id: e for e in self.store.all() if e.type == "secret_indicator"}
            for kind, hits in by_kind.items():
                ids = [i for i, e in secret_items.items() if e.data.get("kind") == kind][:8]
                if not ids:
                    continue
                worst = max((Severity(h["severity"]) for h in hits), key=lambda s: SEVERITY_RANK[s])
                self.add_finding(
                    Category.SECRET_EXPOSURE, worst, f"Possible committed credential: {kind.replace('_', ' ')}",
                    f"{len(hits)} {kind.replace('_', ' ')} indicator(s) in tracked files, e.g. {hits[0]['file']}:{hits[0]['line']}. Values are redacted in this report.",
                    ids, reasoning="Pattern-based static detection. A human must confirm whether the value is a live credential and rotate it if so.",
                    confidence=0.85 if worst != Severity.MEDIUM else 0.55, manual=True,
                    explanations=["Real credential committed by mistake", "Test fixture or revoked key", "False positive on a high-entropy non-secret value"],
                )
            self.set("secret_scan", ModuleStatus.FAIL if by_kind else ModuleStatus.PASS, f"{len(real)} indicator(s) in tracked files at HEAD; {hygiene['secrets']['scope']}")

            env = hygiene["environment"]
            populated = [e for e in env["real_env_files_tracked"] if e["non_empty_variables"]]
            if env["real_env_files_tracked"]:
                self.add_finding(
                    Category.REPOSITORY_HYGIENE, Severity.MEDIUM if populated else Severity.LOW, "Environment file committed to the repository",
                    f"{len(env['real_env_files_tracked'])} real environment file(s) are tracked ({', '.join(e['file'] for e in env['real_env_files_tracked'][:4])}); {len(populated)} contain non-empty variables.",
                    [ev["environment"]], reasoning="Environment files normally stay untracked with a committed .env.example.", confidence=0.95,
                )
            elif env["env_files_in_history_but_removed"]:
                self.add_finding(
                    Category.REPOSITORY_HYGIENE, Severity.LOW, "Environment file exists in Git history",
                    f"{len(env['env_files_in_history_but_removed'])} environment file(s) were committed earlier and later removed; their contents remain retrievable from history.",
                    [ev["environment"]], confidence=0.9,
                )
            self.set("environment_hygiene", ModuleStatus.FAIL if env["real_env_files_tracked"] or env["env_files_in_history_but_removed"] else ModuleStatus.PASS,
                     f"{len(env['real_env_files_tracked'])} real env file(s) tracked; example file {'present' if env['example_env_present'] else 'absent'}")

            gi = hygiene["gitignore"]
            wrongly = gi["tracked_files_that_should_be_ignored"]
            if not gi["present"]:
                self.add_finding(Category.REPOSITORY_HYGIENE, Severity.LOW, "No .gitignore at the repository root", "The repository has no root .gitignore.", [ev["gitignore"]], confidence=0.99)
            if wrongly:
                listing = "; ".join(f"{k}: {v['count']} file(s)" for k, v in wrongly.items())
                self.add_finding(
                    Category.REPOSITORY_HYGIENE, Severity.MEDIUM if "dependency directory" in wrongly else Severity.LOW,
                    "Files that are normally ignored are committed", f"Tracked despite being build/dependency/IDE artefacts: {listing}.", [ev["gitignore"]], confidence=0.9,
                )
            self.set("gitignore", ModuleStatus.FAIL if (not gi["present"] or wrongly) else ModuleStatus.PASS, "present" if gi["present"] else "missing")

            deps = hygiene["dependencies"]
            if deps["issues"]:
                worst = max((Severity(i["severity"]) for i in deps["issues"]), key=lambda s: SEVERITY_RANK[s])
                self.add_finding(Category.REPOSITORY_HYGIENE, worst, "Dependency hygiene issues", " ".join(i["issue"] + "." for i in deps["issues"]), [ev["dependencies"]], confidence=0.85)
            if not deps["manifests"]:
                self.set("dependency_hygiene", ModuleStatus.NOT_APPLICABLE, "no dependency manifests detected")
            else:
                self.set("dependency_hygiene", ModuleStatus.FAIL if deps["issues"] else ModuleStatus.PASS, f"{len(deps['issues'])} issue(s)")

            readme = m.get("readme")
            if readme is not None and not readme["present"]:
                self.add_finding(Category.REPOSITORY_HYGIENE, Severity.LOW, "No README", "The repository has no README, so its claims and setup cannot be cross-checked.", [ev["structure"]], confidence=0.99)
                self.set("readme_crosscheck", ModuleStatus.NOT_APPLICABLE, "no README in the repository")

        readme = m.get("readme")
        if readme and readme.get("present"):
            contradicted = [c for c in readme["claims"] if c["status"] == "CONTRADICTED"]
            if contradicted:
                self.add_finding(
                    Category.README_MISMATCH, Severity.MEDIUM if len(contradicted) >= 2 else Severity.LOW, "README claims not supported by the repository",
                    "The README presents " + ", ".join(c["technology"] for c in contradicted) + " as part of the project, but the repository contains no corresponding files.",
                    [c["evidence_id"] for c in contradicted], reasoning="For these technologies presence is fully determined by tracked files, and none exist.", confidence=0.8,
                    basis=[f"claim {c['evidence_id']}: {c['technology']} is CONTRADICTED" for c in contradicted],
                )

        ci = m["ci"]
        if ci["consistency_findings"] and ci["evidence"].get("ci"):
            worst = max((Severity(i["severity"]) for i in ci["consistency_findings"]), key=lambda s: SEVERITY_RANK[s])
            self.add_finding(
                Category.CI_CD, worst, "GitHub Actions workflows do not match the repository",
                " ".join(f"[{i['workflow']}] {i['issue']}." for i in ci["consistency_findings"][:8]), [ci["evidence"]["ci"]],
                reasoning="Static validation of workflow commands against tracked files. A workflow file existing is not proof that CI works.", confidence=0.8,
            )

        for entry in m["similarity"]["comparisons"]:
            if entry.get("threshold_exceeded"):
                self.add_finding(
                    Category.SIMILARITY, Severity.HIGH, "SIMILARITY_THRESHOLD_EXCEEDED",
                    f"Meaningful-source similarity to {entry['comparison_source']} is {entry['similarity_estimate']:.0%}, at or above the {cfg.similarity_threshold:.0%} manual-review threshold "
                    f"({entry['files_at_or_above_threshold']} of {entry['files_compared']} files individually at or above it).",
                    [entry["evidence_id"]],
                    reasoning="Measured textual overlap. It does not establish direction of copying, licensing, or intent, and is not a plagiarism verdict.",
                    confidence=0.9, manual=True, basis=[f"similarity_estimate {entry['similarity_estimate']:.2f} >= threshold {cfg.similarity_threshold:.2f}"],
                    explanations=["Shared starter template or official example", "Declared fork or reuse of the team's earlier project", "Open-source reuse", "Undeclared copying"],
                )

    # ------------------------------------------------------------------ LLM layer
    def _existing(self, categories: Optional[set[Category]] = None) -> list[dict[str, Any]]:
        return [
            {"finding_id": f.finding_id, "category": f.category.value, "severity": f.severity.value, "title": f.title, "requires_manual_review": f.requires_manual_review}
            for f in self.findings if categories is None or f.category in categories
        ]

    def _open_anomaly_ids(self, categories: Optional[set[Category]]) -> list[str]:
        ids = []
        for a in self.store.anomalies():
            if a.lifecycle == Lifecycle.RESOLVED or (categories is not None and a.category not in categories):
                continue
            ids.append(a.id)
            ids.extend(a.evidence_ids)
        return ids

    def _step_inputs(self, step: str) -> Optional[tuple[dict[str, Any], list[str]]]:
        m, store = self.metrics, self.store
        rules = {
            "similarity_threshold": self.cfg.similarity_threshold, "deadline": self.cfg.deadline,
            "ai_usage_policy": "no rule provided: AI assistance is not restricted",
        }
        repo = {k: self.repository.get(k) for k in ("name", "owner", "kind", "default_branch", "created_at", "fork", "parent", "template")}
        repo["evaluated_head"] = (self.repository.get("evaluated_head") or "")[:12]
        commits, contrib, timeline, branches = m["commits"], m["contributors"], m["timeline"], m["branches"]
        cev = contrib["evidence"]
        anomalies = self._open_anomaly_ids(STEP_ANOMALY_CATEGORIES.get(step))
        totals = {"commits": commits["total"], "non_merge_commits": commits["non_merge"], "human_contributors": contrib["human_contributors"], "duration_hours": timeline["duration_hours"]}

        if step == "reconnaissance":
            if not m.get("hygiene"):
                return None
            h = m["hygiene"]["evidence"]
            return {"repository": repo, "existing_findings": self._existing({Category.REPOSITORY_HYGIENE, Category.SECRET_EXPOSURE})}, [h["structure"], h["gitignore"], h["environment"], h["dependencies"], self.scc_ev]
        if step == "commit_analysis":
            ids = anomalies + [commits["evidence"]["quality"], commits["evidence"]["inflation"]] + store.ids_from("commits")
            return {"totals": totals, "commit_classification": commits["classification"], "granularity": {k: v for k, v in commits["granularity"].items() if k != "largest_commits"}}, ids
        if step == "contribution_analysis":
            return {"totals": totals, "scc": {k: m["scc"][k] for k in ("raw_code_loc", "meaningful_source_loc_estimate", "excluded_loc")}}, anomalies + list(cev["contributors"].values()) + [self.scc_ev]
        if step == "authorship_analysis":
            return {"totals": totals}, anomalies + [cev["identity_map"], cev["authorship"], cev["coauthorship"], *cev["coauthor_commits"], *cev["contributors"].values()]
        if step == "timeline_analysis":
            ids = anomalies + [timeline["evidence"]["timeline"], branches["evidence"]["branches"]]
            if self.github_ev:
                ids.append(self.github_ev)
            if m["ci"]["evidence"].get("ci"):
                ids.append(m["ci"]["evidence"]["ci"])
            ids += store.ids_from("timeline")
            ids += [r["evidence_id"] for r in commits["granularity"]["largest_commits"][:5]]
            return {"totals": totals, "evaluation_rules": rules, "repository": repo, "github_data": "not applicable (local repository)" if self.source.kind != "github" else "see github evidence item"}, ids
        if step == "provenance_analysis":
            sim = m["similarity"]
            drops = self._open_anomaly_ids({Category.TIMELINE_ANOMALY})
            declared = bool(self.repository.get("fork") or self.repository.get("template"))
            if not (sim["performed"] or declared):
                return None
            ids = self.similarity_ev + drops + [r["evidence_id"] for r in commits["granularity"]["largest_commits"][:5]]
            if self.github_ev:
                ids.append(self.github_ev)
            return {"evaluation_rules": rules, "repository": repo, "similarity_method": sim["method"], "comparisons_performed": len(self.similarity_ev), "existing_findings": self._existing({Category.SIMILARITY})}, ids
        if step == "ai_signal_analysis":
            if not m.get("ai_signals"):
                return None
            return {"evaluation_rules": rules, "totals": totals}, [m["ai_signals"]["evidence"]["ai_signals"], self.scc_ev]
        if step == "readme_crosscheck":
            readme = m.get("readme")
            if not readme or not readme["present"] or not m.get("hygiene"):
                return None
            ids = [readme["evidence"]["readme"], *readme["evidence"]["claims"], m["hygiene"]["evidence"]["structure"]]
            if m["ci"]["evidence"].get("ci"):
                ids.append(m["ci"]["evidence"]["ci"])
            return {"claim_status_counts": readme["claim_status_counts"], "readme_is_minimal": readme["is_minimal"], "ml_claims_handed_off": len(readme["ml_claims"]), "ci_workflows": len(m["ci"]["workflow_files"])}, ids
        if step == "integrity_synthesis":
            ids = self._open_anomaly_ids(None) + [*cev["contributors"].values(), timeline["evidence"]["timeline"], cev["coauthorship"], commits["evidence"]["inflation"], self.scc_ev, *self.similarity_ev]
            return {
                "totals": totals, "evaluation_rules": rules, "existing_findings": self._existing(),
                "raw_vs_meaningful": {"raw_code_loc": m["scc"]["raw_code_loc"], "meaningful_source_loc_estimate": m["scc"]["meaningful_source_loc_estimate"], "total_meaningful_additions_in_history": commits["granularity"]["total_meaningful_additions"]},
            }, ids
        raise KeyError(step)

    def _reason(self) -> None:
        steps = list(STEP_MODULES)
        if not self.cfg.llm_enabled:
            for step in steps:
                for module in STEP_MODULES[step]:
                    self.modules.get(module) or self.set(module, ModuleStatus.UNVERIFIABLE, "LLM reasoning disabled (--no-llm): deterministic evidence collected but not interpreted")
            return
        try:
            if self.provider is None:
                self.provider = create_provider(self.cfg)
            self.model_info = {**self.provider.prepare(), "enabled": True}
        except LLMUnavailableError as exc:
            self.error("llm", "LLM_UNAVAILABLE", str(exc))
            for step in steps:
                for module in STEP_MODULES[step]:
                    self.modules.get(module) or self.set(module, ModuleStatus.UNVERIFIABLE, "LLM unavailable")
            return
        self.progress(f"  - model: {self.model_info.get('model')} ({self.model_info.get('runtime_model_tag')})" + (" [fallback]" if self.model_info.get("fallback_used") else ""))

        # Leave room in the context window for the system prompt, task prompt and the answer.
        budget = max(3000, min(self.cfg.llm_packet_chars, (self.cfg.llm_num_ctx - self.cfg.llm_max_tokens) * 3 - 9000))
        for step in steps:
            modules = [mod for mod in STEP_MODULES[step] if mod not in self.modules]
            inputs = self._step_inputs(step)
            if inputs is None:
                for module in modules:
                    detail = {
                        "provenance_analysis": "no similarity comparison and no declared fork/template: provenance not investigated beyond history signals",
                    }.get(step, "inputs unavailable")
                    status = ModuleStatus.UNVERIFIABLE if (step != "provenance_analysis" or self.cfg.require_similarity) else ModuleStatus.NOT_APPLICABLE
                    self.set(module, status, detail)
                continue
            metrics, ids = inputs
            packet, allowed = build_packet(self.store, metrics, ids, budget)
            self.progress(f"  - {step} ({len(allowed)} evidence items)")
            try:
                result, meta = run_step(self.provider, step, packet, allowed, self.store, AnalysisResult, AI_CLASSES if step == "ai_signal_analysis" else None)
            except LLMStepError as exc:
                self.error(step, "LLM_STEP_FAILED", str(exc))
                self.llm_analyses[step] = {"status": "FAILED", "error": str(exc)[:500]}
                for module in modules:
                    self.set(module, ModuleStatus.UNVERIFIABLE, f"reasoning step '{step}' failed")
                continue
            created = self._absorb(step, result)
            decided = [d for d in self.candidate_decisions if d.step == step]
            self.progress(
                f"      done in {meta['duration_s']:.0f}s: {len(decided)} candidate(s) -> {len(created)} finding(s), "
                f"{sum(d.decision == 'MERGED' for d in decided)} merged, {sum(d.decision == 'OBSERVATION' for d in decided)} observation(s), "
                f"{sum(d.decision == 'DISCARDED' for d in decided)} discarded" + (" [repaired after retry]" if meta["repaired"] else "")
            )
            self.llm_analyses[step] = {
                "status": "OK", "summary": result.summary, "classification": result.classification, "unresolved_questions": result.unresolved_questions,
                "findings": created, "evidence_items_provided": len(allowed), "omitted_evidence": packet.get("omitted_evidence_count", 0), **meta,
            }
            if step == "integrity_synthesis":
                self.integrity_summary = (result.summary, "llm")
            for module in modules:
                self.set(module, ModuleStatus.PASS, f"deterministic metrics interpreted by '{step}'")
            if step == "timeline_analysis" and "merges" in modules and not self.metrics["branches"]["merge_commits"]:
                self.set("merges", ModuleStatus.NOT_APPLICABLE, "history contains no merge commits")
        if self.metrics.get("ai_signals") and "ai_signal_analysis" in self.llm_analyses:
            self.metrics["ai_signals"]["classification"] = self.llm_analyses["ai_signal_analysis"].get("classification")
        self.model_info = {**self.provider.info(), "enabled": True}

    def _absorb(self, step: str, result: AnalysisResult) -> list[str]:
        """Pass every model candidate through the deterministic policy. The model's own severity,
        manual-review request and category are proposals only."""
        created = []
        cited: set[str] = set()
        for candidate in result.findings:
            decision = assess_candidate(candidate, self.store, self.findings)
            finding_id = decision.merge_into
            if decision.action in ("ACCEPTED", "MERGED"):
                # The model's words are advisory. Sentences that contradict the authoritative fields are dropped.
                advisory, removed = sanitize_advisory(
                    f"{candidate.finding} {candidate.reasoning}", manual_review=decision.requires_manual_review, material=decision.material,
                    severity=decision.severity.value, finding_type=decision.finding_type.value, outcome=decision.outcome.value,
                )
            if decision.action == "ACCEPTED":
                finding = self.add_finding(
                    decision.category, decision.severity, decision.title or candidate.title, decision.text or "; ".join(decision.basis), candidate.evidence_ids,
                    llm_reasoning=advisory, confidence=candidate.confidence, manual=decision.requires_manual_review,
                    origin="llm", step=step, explanations=candidate.possible_explanations, finding_type=decision.finding_type,
                    basis=decision.basis, outcome=decision.outcome,
                )
                finding.llm_reasoning_removed = removed
                finding_id = finding.finding_id
                created.append(finding_id)
                cited.update(candidate.evidence_ids)
            elif decision.action == "MERGED":
                existing = next(f for f in self.findings if f.finding_id == decision.merge_into)
                if not existing.llm_reasoning:
                    existing.llm_reasoning = advisory
                existing.llm_reasoning_removed = list(dict.fromkeys(existing.llm_reasoning_removed + removed))
                cited.update(candidate.evidence_ids)
            elif decision.action == "OBSERVATION":
                self.llm_observations.append((candidate.category.value.lower(), f"{candidate.title}: {candidate.finding}", list(candidate.evidence_ids)))
            self.candidate_decisions.append(
                CandidateDecision(
                    candidate_id=f"CAND-{len(self.candidate_decisions) + 1:03d}", claim=candidate.finding[:400], model_reasoning=candidate.reasoning[:400],
                    step=step, title=candidate.title, proposed_category=candidate.category.value, proposed_severity=candidate.severity.value,
                    proposed_manual_review=candidate.requires_manual_review, evidence_ids=list(candidate.evidence_ids), decision=decision.action,
                    finding_type=decision.finding_type, reason=decision.reason, finding_id=finding_id,
                )
            )
        for resolution in result.resolved_anomalies:
            anomaly = self.store.anomaly(resolution.anomaly_id)
            if anomaly.material:
                # Advisory only: a model cannot remove a manual-review requirement.
                anomaly.proposed_explanation = anomaly.proposed_explanation or resolution.explanation
                anomaly.proposed_by = anomaly.proposed_by or f"llm:{step}"
            elif anomaly.id not in cited and anomaly.lifecycle != Lifecycle.ASSESSED:
                anomaly.lifecycle = Lifecycle.RESOLVED
                anomaly.resolution = resolution.explanation
                anomaly.resolved_by = f"llm:{step}"
        return created

    def _escalate_unaddressed_anomalies(self) -> None:
        """Every material anomaly ends as a finding that requires manual review, whatever the model said."""
        for anomaly in self.store.anomalies():
            if not anomaly.material or any(anomaly.id in f.evidence_ids for f in self.findings):
                continue
            explained = bool(anomaly.proposed_explanation)
            self.add_finding(
                anomaly.category, anomaly.severity_hint, anomaly.title, anomaly.description, [anomaly.id, *anomaly.evidence_ids],
                reasoning="Detected deterministically. Intent or provenance cannot be determined automatically, so it is surfaced for manual review rather than resolved.",
                llm_reasoning=(f"Explanation proposed by {anomaly.proposed_by} (advisory, not verified): {anomaly.proposed_explanation}" if explained else ""),
                confidence=0.5, manual=True, step="escalation", explanations=anomaly.possible_explanations,
                finding_type=FindingType.MATERIAL_INTEGRITY_CONCERN, basis=[f"anomaly {anomaly.id} (material): {anomaly.title}"],
                outcome=Outcome.REVIEW if explained else Outcome.UNVERIFIABLE, status=FindingStatus.OPEN if explained else FindingStatus.UNVERIFIABLE,
            )

    # ------------------------------------------------------------------ finalisation
    def _coverage(self) -> list[CoverageStatus]:
        for module in MODULES:
            if module not in self.modules and module not in {"report_generation", "report_validation"}:
                self.set(module, ModuleStatus.UNVERIFIABLE, "not run: an earlier stage did not complete")
        self.modules.setdefault("report_generation", CoverageStatus(module="report_generation", status=ModuleStatus.PASS, mandatory=True, detail="JSON and Markdown rendered from one evaluation object"))
        self.modules.setdefault("report_validation", CoverageStatus(module="report_validation", status=ModuleStatus.PASS, mandatory=True, detail="Definition-of-Done validator"))
        return [self.modules[m] for m in MODULES]

    def _scale(self) -> Optional[dict[str, Any]]:
        m = self.metrics
        if "commits" not in m:
            return None
        return {
            "commits": m["commits"]["total"], "human_contributors": m["contributors"]["human_contributors"], "tracked_files": len(self.tracked),
            "code_loc": m["scc"]["raw_code_loc"], "meaningful_source_loc_estimate": m["scc"]["meaningful_source_loc_estimate"], "branches": m["branches"]["branch_count"],
        }

    def _narrative(self, status: CompletionStatus, reasons: list[str], counts: dict[str, int], observations: list[Observation]) -> None:
        """Deterministic summary is always produced and is authoritative. A model narrative is added only
        if it is consistent with the computed result."""
        self.executive_summary.update(text=deterministic_summary(self.source.slug, status.value, counts, self._scale(), reasons), origin="deterministic")
        if not (self.cfg.llm_enabled and self.provider and self.model_info.get("model") and "commits" in self.metrics):
            return
        active = open_findings(self.findings)
        packet = {
            "repository": self.source.slug, "completion_status": status.value, "status_reasons": reasons[:12],
            "manual_review_required": counts["manual_review_requirements"] > 0, "counts": counts, "scale": self._scale(),
            "repository_observations": [o.text for o in observations][:20],
            "engineering_weaknesses": [f.title for f in active if f.finding_type == FindingType.ENGINEERING_WEAKNESS][:15],
            "integrity_findings": [{"type": f.finding_type.value, "title": f.title, "requires_manual_review": f.requires_manual_review} for f in active if f.finding_type != FindingType.ENGINEERING_WEAKNESS][:15],
            "healthy_signals": healthy_signals(self.metrics),
            "evaluator_errors": [f"{e.stage}: {e.kind}" for e in self.errors],
        }
        allowed_numbers = numbers_in(packet)

        rejected: dict[str, Any] = {}

        def consistent(result: NarrativeResult) -> None:
            problems = summary_problems(result.executive_summary, status.value, counts, allowed_numbers, self.source.slug)
            if problems:
                rejected.update(text=result.executive_summary, problems=problems)
                raise PolicyRejection("the summary contradicts the computed evaluation: " + "; ".join(problems))

        self.progress("  - final_report (model narrative)")
        try:
            result, meta = run_step(self.provider, "final_report", packet, [], self.store, NarrativeResult, extra_check=consistent)
            self.executive_summary.update(llm_narrative=result.executive_summary, llm_narrative_status="ACCEPTED")
            self.llm_analyses["final_report"] = {"status": "OK", **meta}
        except LLMStepError as exc:
            if exc.kind == "policy_rejected":
                # The model answered, but its prose contradicted the computed result. The authoritative
                # deterministic summary stands; the rejection is recorded and shown, not hidden.
                # Kept for the audit trail only: the rejected text is never rendered as the summary.
                problems = rejected.get("problems", [exc.reason[:600]])
                self.executive_summary.update(
                    llm_narrative_status="REJECTED", narrative_rejection_reasons=reason_codes(problems),
                    llm_narrative_rejection=problems, rejected_narrative=rejected.get("text", ""),
                )
                self.llm_analyses["final_report"] = {"status": "REJECTED", "narrative_rejection_reasons": reason_codes(problems), "details": problems, "attempts": exc.attempts}
                self.progress("      model narrative rejected (inconsistent with the computed result); deterministic summary used")
            else:
                self.error("final_report", "LLM_STEP_FAILED", str(exc))
                self.llm_analyses["final_report"] = {"status": "FAILED", "error": str(exc)[:500]}

    def _observations(self) -> list[Observation]:
        observations = repository_observations(self.metrics, self.source.kind)
        for topic, text, evidence_ids in self.llm_observations:
            observations.append(Observation(id=f"OBS-{len(observations) + 1:03d}", topic=topic, text=text, source="llm", evidence_ids=evidence_ids))
        return observations

    def finalize(self) -> FinalEvaluation:
        self.progress("[4/4] Validating coverage and deciding completion status")
        coverage = self._coverage()
        observations = self._observations()
        status, dod = decide(coverage, self.findings, self.errors)
        errors_before = len(self.errors)
        self._narrative(status, dod.reasons, dod.counts, observations)
        if len(self.errors) != errors_before:
            status, dod = decide(coverage, self.findings, self.errors)
            self.executive_summary.update(text=deterministic_summary(self.source.slug, status.value, dod.counts, self._scale(), dod.reasons))
        if self.provider is not None and self.model_info.get("model"):
            self.model_info = {**self.provider.info(), "enabled": True}

        active = open_findings(self.findings)
        manual = [ManualReviewRequirement(finding_id=f.finding_id, category=f.category, reason=f.title) for f in active if f.requires_manual_review]
        anomalies = self.store.anomalies()
        cited = {e for f in self.findings for e in f.evidence_ids} | {e for o in observations for e in o.evidence_ids}
        used = cited | {e for a in anomalies for e in a.evidence_ids} | {a.id for a in anomalies}
        m = self.metrics
        metrics = {k: v for k, v in m.items() if v is not None}
        if "scc" in metrics:
            metrics["scc"] = {k: v for k, v in metrics["scc"].items() if k != "files"}
        if "commits" in m:
            metrics["statistics"] = {
                "files": len(self.tracked), "raw_loc": m["scc"]["raw_code_loc"], "meaningful_loc_estimate": m["scc"]["meaningful_source_loc_estimate"],
                "commits": m["commits"]["total"], "contributors": m["contributors"]["human_contributors"], "branches": m["branches"]["branch_count"],
            }
        metrics["config"] = self.cfg.public_dict()
        metrics["healthy_signals"] = healthy_signals(m) if "commits" in m else []
        return FinalEvaluation(
            agent={"name": "ARGUS", "specialization": "Repository Forensics & Engineering Integrity", "version": __version__},
            evaluation_id=self.evaluation_id, timestamp=self.timestamp, repository=self.repository, model=self.model_info,
            coverage=coverage, deterministic_metrics=metrics, llm_analyses=self.llm_analyses, anomalies=anomalies,
            observations=observations, findings=self.findings, candidate_decisions=self.candidate_decisions,
            evidence=[e for e in self.store.all() if e.id in used or e.type not in {"commit"}],
            integrity_assessment=IntegrityAssessment(
                summary=self.integrity_summary[0], summary_origin=self.integrity_summary[1],
                open_material_concerns=dod.counts["integrity_flags"], anomalies_detected=len(anomalies),
                anomalies_resolved=sum(1 for a in anomalies if a.lifecycle == Lifecycle.RESOLVED),
                anomalies_escalated=sum(1 for f in self.findings if f.source_step == "escalation"), manual_review_required=bool(manual),
            ),
            handoffs=self.handoffs, manual_review={"required": bool(manual), "requirements": [r.model_dump(mode="json") for r in manual]},
            unverifiable_items=self.unverifiable, errors=self.errors, executive_summary=self.executive_summary,
            completion_status=status, definition_of_done=dod,
        )


def healthy_signals(m: dict[str, Any]) -> list[str]:
    """Evidence-supported positive signals, derived deterministically."""
    out = []
    if not m.get("commits"):
        return out
    q = m["commits"]["quality"]
    if q["non_merge_commits"] >= 5 and q["weak_message_ratio"] <= 0.15:
        out.append(f"Descriptive commit messages: {q['weak_message_ratio']:.0%} low-information messages across {q['non_merge_commits']} commits")
    t = m["timeline"]
    if t["active_days"] >= 3:
        out.append(f"Development spread over {t['active_days']} active days")
    if t["milestones"].get("tests_introduced"):
        out.append("Tests are present and were introduced at commit " + t["milestones"]["tests_introduced"]["sha"])
    ci = m.get("ci") or {}
    if ci.get("workflow_files") and not ci.get("consistency_findings"):
        out.append(f"{len(ci['workflow_files'])} CI workflow(s) consistent with the repository ({', '.join(ci['capabilities']) or 'no test/lint/build step detected'})")
    h = m.get("hygiene")
    if h:
        if h["gitignore"]["present"] and not h["gitignore"]["tracked_files_that_should_be_ignored"]:
            out.append(".gitignore present and no build/dependency artefacts committed")
        if not [x for x in h["secrets"]["indicators"] if x["severity"] != "LOW"]:
            out.append("No credential indicators found in tracked files")
        if h["environment"]["example_env_present"] and not h["environment"]["real_env_files_tracked"]:
            out.append("Environment template committed while real environment files stay untracked")
    b = m["branches"]
    if b["merge_commits"] or len(b["branches"]) > 1:
        out.append(f"Branch-based workflow: {b['branch_count']} branch(es), {b['merge_commits']} merge commit(s)")
    gh = m.get("github") or {}
    if (gh.get("pull_requests") or {}).get("count"):
        out.append(f"{gh['pull_requests']['count']} pull request(s) on GitHub")
    return out


def _force_remove(func, path, exc) -> None:
    """Git marks pack files read-only on Windows; clear the bit and retry."""
    import os
    import stat

    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def evaluate(raw_source: str, cfg: Config, provider: Optional[LLMProvider] = None, progress: Optional[Progress] = None) -> FinalEvaluation:
    return Evaluation(raw_source, cfg, provider, progress).run()
