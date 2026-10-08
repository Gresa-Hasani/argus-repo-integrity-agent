"""GitHub Actions forensics: parse workflows statically and check them against the repository."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from argus.collectors.gitutil import read_text
from argus.evidence import EvidenceStore

_SECRET_REF = re.compile(r"\$\{\{\s*secrets\.([A-Za-z0-9_]+)\s*\}\}")

# command pattern -> (ecosystem label, manifest basenames that justify it)
_ECOSYSTEMS = [
    (re.compile(r"\b(npm|npx|yarn|pnpm|bun)\b"), "Node.js", {"package.json"}),
    (re.compile(r"\b(pip3?|pytest|poetry|uv|tox)\b"), "Python", {"requirements.txt", "pyproject.toml", "setup.py", "Pipfile", "setup.cfg", "tox.ini"}),
    (re.compile(r"\bdotnet\b"), ".NET", set()),
    (re.compile(r"\bcargo\b"), "Rust", {"Cargo.toml"}),
    (re.compile(r"\bgo (build|test|vet|mod)\b"), "Go", {"go.mod"}),
    (re.compile(r"\b(mvn|mvnw)\b"), "Maven", {"pom.xml"}),
    (re.compile(r"\b(gradle|gradlew)\b"), "Gradle", {"build.gradle", "build.gradle.kts"}),
    (re.compile(r"\bdocker(-compose| compose)?\s+(build|compose|push)\b|\bdocker build\b"), "Docker", set()),
]


def _norm_dir(wd: Any) -> str:
    """Normalised repo-relative directory, or '' for the root / an expression we cannot resolve."""
    text = str(wd or "").strip()
    if not text or "${{" in text:
        return ""
    text = text.removeprefix("./").strip("/")
    return "" if text in {"", "."} else str(PurePosixPath(text))


def _steps_kind(run: str) -> set[str]:
    kinds = set()
    if re.search(r"\b(pytest|jest|vitest|mocha|go test|cargo test|dotnet test|mvn\w* .*test|gradle\w* .*test|npm (run )?test|yarn test|pnpm test|unittest|tox)\b", run):
        kinds.add("test")
    if re.search(r"\b(eslint|ruff|flake8|pylint|black|prettier|golangci-lint|clippy|mypy|tsc|npm run lint|yarn lint|pnpm lint)\b", run):
        kinds.add("lint")
    if re.search(r"\b(npm run build|yarn build|pnpm build|cargo build|go build|dotnet build|mvn\w* .*package|docker build|vite build|next build|python -m build)\b", run):
        kinds.add("build")
    if re.search(r"\b(deploy|vercel|netlify|firebase deploy|aws |gcloud |az |kubectl|helm|terraform apply|docker push|gh-pages)\b", run):
        kinds.add("deploy")
    return kinds


def analyze(repo: Path, tracked: list[str], store: EvidenceStore) -> dict[str, Any]:
    src = "ci"
    files = [f for f in tracked if re.match(r"^\.github/workflows/[^/]+\.ya?ml$", f)]
    other_ci = [f for f in tracked if PurePosixPath(f).name in {".gitlab-ci.yml", "Jenkinsfile", "azure-pipelines.yml"} or f.startswith(".circleci/")]
    basenames: dict[str, list[str]] = {}
    for f in tracked:
        basenames.setdefault(PurePosixPath(f).name, []).append(f)
    tracked_set = set(tracked)
    dirs = {str(p) for f in tracked for p in PurePosixPath(f).parents if str(p) != "."}
    has_tests = any(re.search(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]*\.py$|\.(test|spec)\.[cm]?[jt]sx?$|_test\.go$", f) for f in tracked)

    workflows = []
    issues: list[dict[str, Any]] = []

    def issue(workflow: str, text: str, severity: str = "LOW") -> None:
        issues.append({"workflow": workflow, "issue": text, "severity": severity})

    for wf in files:
        text = read_text(repo, wf) or ""
        try:
            doc = yaml.safe_load(text) or {}
            if not isinstance(doc, dict):
                raise ValueError("workflow root is not a mapping")
        except Exception as exc:
            issue(wf, f"workflow is not valid YAML: {str(exc)[:120]}", "MEDIUM")
            workflows.append({"file": wf, "parse_error": str(exc)[:200]})
            continue
        on = doc.get("on", doc.get(True))  # YAML 1.1 parses the bare key `on` as boolean True
        triggers = sorted(on) if isinstance(on, dict) else ([on] if isinstance(on, str) else list(on or []))
        jobs = []
        kinds: set[str] = set()
        for job_name, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            job_dir = ((job.get("defaults") or {}).get("run") or {}).get("working-directory")
            steps = []
            for step in job.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                run = step.get("run")
                wd = step.get("working-directory") or job_dir
                steps.append({"name": step.get("name"), "uses": step.get("uses"), "run": run[:300] if isinstance(run, str) else None, "working_directory": wd})
                wd_norm = _norm_dir(wd)
                if wd_norm and wd_norm not in dirs:
                    issue(wf, f"job '{job_name}' uses working-directory '{wd}' which does not exist in the repository", "MEDIUM")
                if not isinstance(run, str):
                    continue
                kinds |= _steps_kind(run)
                prefix = wd_norm + "/" if wd_norm else ""
                for pattern, label, manifests in _ECOSYSTEMS:
                    if not pattern.search(run):
                        continue
                    if label == ".NET" and not any(f.endswith((".csproj", ".sln", ".fsproj")) for f in tracked):
                        issue(wf, f"job '{job_name}' runs dotnet commands but no .csproj/.sln exists", "MEDIUM")
                    elif label == "Docker" and not any(n.startswith("Dockerfile") for n in basenames):
                        issue(wf, f"job '{job_name}' builds a Docker image but no Dockerfile is tracked", "MEDIUM")
                    elif manifests and not any(m in basenames for m in manifests):
                        issue(wf, f"job '{job_name}' runs {label} commands but no {'/'.join(sorted(manifests))} exists in the repository", "MEDIUM")
                for req in re.findall(r"pip3? install .*?-r\s+(\S+)", run):
                    if "$" not in req and prefix + req.removeprefix("./") not in tracked_set:
                        issue(wf, f"job '{job_name}' installs from '{req}' which is not tracked", "MEDIUM")
                for script in re.findall(r"\b(?:npm|pnpm|yarn|bun) run ([A-Za-z0-9:_-]+)", run):
                    pkg_path = prefix + "package.json"
                    if pkg_path in tracked_set:
                        try:
                            scripts = (json.loads(read_text(repo, pkg_path) or "{}").get("scripts") or {})
                        except json.JSONDecodeError:
                            scripts = {}
                        if script not in scripts:
                            issue(wf, f"job '{job_name}' runs package script '{script}' which {pkg_path} does not define", "MEDIUM")
                for script in re.findall(r"(?:^|\s)(?:bash|sh|python3?)\s+(\.?/?[\w./-]+\.(?:sh|py))", run):
                    if prefix + script.removeprefix("./") not in tracked_set:
                        issue(wf, f"job '{job_name}' runs '{script}' which is not tracked")
            if "test" in _steps_kind(" ".join(s["run"] or "" for s in steps)) and not has_tests:
                issue(wf, f"job '{job_name}' runs a test command but no test files were found in the repository")
            jobs.append({"name": job_name, "runs_on": job.get("runs-on"), "steps": steps[:30], "needs": job.get("needs")})
        workflows.append(
            {
                "file": wf, "name": doc.get("name"), "triggers": [str(t) for t in triggers], "jobs": jobs,
                "capabilities": sorted(kinds), "secrets_referenced": sorted(set(_SECRET_REF.findall(text))),
                "actions_used": sorted({s["uses"] for j in jobs for s in j["steps"] if s["uses"]}),
            }
        )

    capabilities = sorted({k for w in workflows for k in w.get("capabilities", [])})
    metrics = {
        "workflow_files": files,
        "other_ci_files": other_ci,
        "workflows": workflows,
        "capabilities": capabilities,
        "consistency_findings": issues,
        "has_test_files": has_tests,
    }
    if files:
        slim = [{k: v for k, v in w.items() if k != "jobs"} | {"jobs": [{"name": j["name"], "runs_on": j["runs_on"], "run": [s["run"] for s in j["steps"] if s["run"]][:8]} for j in w.get("jobs", [])]} for w in workflows]
        metrics["evidence"] = {"ci": store.add("ci", src, f"{len(files)} GitHub Actions workflow(s); capabilities: {', '.join(capabilities) or 'none detected'}", {"workflows": slim, "consistency_findings": issues})}
    else:
        metrics["evidence"] = {}
    return metrics
