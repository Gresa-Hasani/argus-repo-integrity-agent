"""Repository hygiene: structure, .gitignore, environment files, secret indicators, dependencies.

Secret values are redacted at the point of detection and never stored or printed in full.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from argus.collectors.classify import LOCKFILES, classify_path, component_of
from argus.collectors.commits import Commit
from argus.collectors.gitutil import read_text
from argus.evidence import EvidenceStore

_ENV_FILE = re.compile(r"(^|/)\.env(\.[A-Za-z0-9_.-]+)?$")
_ENV_SAFE = re.compile(r"\.(example|sample|template|dist|defaults?)$", re.I)

_SECRET_PATTERNS = [
    ("private_key", "CRITICAL", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY(?: BLOCK)?-----")),
    ("aws_access_key_id", "HIGH", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("databricks_token", "HIGH", re.compile(r"\bdapi[0-9a-f]{32}(?:-\d+)?\b")),
    ("github_token", "HIGH", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{60,}\b")),
    ("anthropic_api_key", "HIGH", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("openai_api_key", "HIGH", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b")),
    ("google_api_key", "HIGH", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("slack_token", "HIGH", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("stripe_live_key", "HIGH", re.compile(r"\b[sr]k_live_[A-Za-z0-9]{20,}\b")),
    ("jwt", "MEDIUM", re.compile(r"\beyJ[A-Za-z0-9_-]{15,}\.eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}\b")),
    ("credential_in_url", "HIGH", re.compile(r"\b[a-z][a-z0-9+.-]{2,}://[^\s:/@'\"]+:([^\s:/@'\"${}<>]{6,})@[^\s'\"]+")),
]
_ASSIGN = re.compile(
    r"""(?ix)\b([A-Z0-9_.-]*(?:password|passwd|secret|api[_-]?key|access[_-]?key|auth[_-]?token|private[_-]?key|client[_-]?secret)[A-Z0-9_.-]*)
        \s*[:=]\s*["']?([^\s"'#,;]{8,})["']?"""
)
_PLACEHOLDER = re.compile(
    r"(?i)(example|sample|changeme|change[_-]?me|your[_-]?|placeholder|dummy|test|xxx+|\*\*\*|<.*>|\$\{|\{\{|process\.env|os\.environ|getenv|"
    r"secrets\.|todo|none|null|true|false|localhost|password|secret|redacted|insert|replace|fake|foo|bar)"
)


_CREDENTIAL_NAME = re.compile(r"(?i)(token|secret|password|passwd|pwd|api[_-]?key|access[_-]?key|private[_-]?key|credential|client[_-]?id|(^|_)pat$)")
_KNOWN_TOKEN_SHAPE = re.compile(
    r"^(dapi[0-9a-f]{32}(-\d+)?|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,}|sk-[A-Za-z0-9_-]{20,}|(AKIA|ASIA)[0-9A-Z]{16}|"
    r"xox[abprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,})$"
)
_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def env_value(raw: str) -> str:
    """The value part of an env line, without quotes or a trailing inline comment."""
    value = re.split(r"\s+#", raw.strip(), maxsplit=1)[0].strip()
    if value.startswith("#"):
        return ""
    return value.strip("\"'")


def classify_credential_value(raw: str) -> str:
    """EMPTY | PLACEHOLDER | SECRET_LIKE | UNKNOWN. Looks at the value's shape only; never returns or stores it."""
    value = env_value(raw)
    if not value:
        return "EMPTY"
    if _KNOWN_TOKEN_SHAPE.match(value):
        return "SECRET_LIKE"
    if _PLACEHOLDER.search(value) or re.search(r"\s", value) or re.fullmatch(r"[xX*._\-]+", value):
        return "PLACEHOLDER"
    if len(value) >= 16 and _entropy(value) >= 3.5:
        return "SECRET_LIKE"
    return "UNKNOWN"


def credential_variables(repo: Path, env_files: list[str]) -> list[dict[str, Any]]:
    """Credential-named variables in env files (Databricks, cloud and generic names), classified by value shape."""
    found = []
    for rel in env_files:
        text = read_text(repo, rel) or ""
        for lineno, line in enumerate(text.splitlines(), 1):
            m = _ENV_LINE.match(line)
            if not m or not _CREDENTIAL_NAME.search(m.group(1)):
                continue
            value = env_value(m.group(2))
            found.append({
                "file": rel, "line": lineno, "variable": m.group(1), "classification": classify_credential_value(m.group(2)),
                "value_length": len(value), "is_template_file": bool(_ENV_SAFE.search(rel)),
            })
    return found


def redact(value: str) -> str:
    value = value.strip()
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * 10}{value[-3:]}"


def _entropy(value: str) -> float:
    counts = Counter(value)
    return -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values())


def scan_secrets(repo: Path, tracked: list[str]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for rel in tracked:
        if classify_path(rel) in {"vendored", "build_output", "minified", "lockfile", "binary", "model_artifact", "dataset"}:
            continue
        text = read_text(repo, rel, limit=1_000_000)
        if text is None:
            continue
        template = bool(_ENV_SAFE.search(rel)) or classify_path(rel) in {"docs", "tests"}
        for lineno, line in enumerate(text.splitlines(), 1):
            if len(line) > 2000:
                continue
            found = None
            for kind, severity, pattern in _SECRET_PATTERNS:
                m = pattern.search(line)
                if m:
                    value = m.group(1) if m.groups() else m.group(0)
                    if kind == "credential_in_url" and _PLACEHOLDER.search(value):
                        continue
                    found = (kind, severity, value)
                    break
            if not found:
                m = _ASSIGN.search(line)
                if m and not _PLACEHOLDER.search(m.group(2)) and _entropy(m.group(2)) >= 3.2 and not template:
                    found = ("hardcoded_credential_assignment", "MEDIUM", m.group(2))
            if found:
                kind, severity, value = found
                if template and kind not in {"private_key"}:
                    severity = "LOW"
                hits.append({"file": rel, "line": lineno, "kind": kind, "severity": severity, "redacted": redact(value) if kind != "private_key" else "-----BEGIN ... PRIVATE KEY-----", "in_template_or_docs": template})
                if len(hits) >= 200:
                    return hits
    return hits


_IGNORE_EXPECTATIONS = {
    "Node.js": (["node_modules"], ["node_modules/"]),
    "Next.js": ([".next"], [".next/"]),
    "Python": (["__pycache__", ".pyc", "venv"], ["__pycache__/", "*.pyc", ".venv/ or venv/"]),
    ".NET": (["bin", "obj"], ["bin/", "obj/"]),
    "Java": (["target", ".class", "build"], ["target/ or build/", "*.class"]),
    "Rust": (["target"], ["target/"]),
}
_SHOULD_NOT_BE_TRACKED = [
    ("dependency directory", re.compile(r"(^|/)(node_modules|bower_components|\.venv|venv|site-packages)/")),
    ("build output", re.compile(r"(^|/)(\.next|__pycache__|\.pytest_cache|\.turbo|\.nuxt)/|(^|/)(bin|obj)/(Debug|Release)/|\.pyc$|\.class$")),
    ("IDE/OS metadata", re.compile(r"(^|/)(\.idea|\.vs)/|(^|/)(\.DS_Store|Thumbs\.db|desktop\.ini)$")),
    ("log file", re.compile(r"\.log$")),
]


def detect_ecosystems(tracked: list[str]) -> dict[str, list[str]]:
    names: dict[str, list[str]] = {}
    for f in tracked:
        if classify_path(f) == "vendored":
            continue
        names.setdefault(PurePosixPath(f).name, []).append(f)
    eco: dict[str, list[str]] = {}

    def add(label: str, *basenames: str) -> None:
        found = [p for b in basenames for p in names.get(b, [])]
        if found:
            eco[label] = found[:5]

    add("Node.js", "package.json")
    add("Python", "requirements.txt", "pyproject.toml", "setup.py", "Pipfile")
    add("Rust", "Cargo.toml")
    add("Go", "go.mod")
    add("Java", "pom.xml", "build.gradle", "build.gradle.kts")
    add("PHP", "composer.json")
    add("Ruby", "Gemfile")
    dotnet = [f for f in tracked if f.endswith((".csproj", ".sln", ".fsproj"))]
    if dotnet:
        eco[".NET"] = dotnet[:5]
    if any(PurePosixPath(f).name.startswith("next.config.") for f in tracked):
        eco["Next.js"] = [f for f in tracked if PurePosixPath(f).name.startswith("next.config.")][:2]
    return eco


def analyze(repo: Path, tracked: list[str], commits: list[Commit], store: EvidenceStore) -> dict[str, Any]:
    src = "hygiene"
    tracked_set = set(tracked)
    ecosystems = detect_ecosystems(tracked)
    ext_counts = Counter(PurePosixPath(f).suffix.lower() for f in tracked if classify_path(f) in {"source", "tests"})

    # --- structure ---------------------------------------------------------------------------
    components = Counter(component_of(f) for f in tracked)
    categories = Counter(classify_path(f) for f in tracked)
    top_level = sorted({PurePosixPath(f).parts[0] for f in tracked})
    structure = {
        "total_files": len(tracked),
        "top_level_entries": top_level[:60],
        "components": [{"component": k, "files": v} for k, v in components.most_common(25)],
        "files_by_category": dict(categories),
        "has_readme": any(re.match(r"^readme(\.[a-z]+)?$", f, re.I) for f in tracked),
        "has_license": any(re.match(r"^(licen[sc]e|copying)(\.[a-z]+)?$", f, re.I) for f in tracked),
        "has_tests": categories.get("tests", 0) > 0,
        "test_files": categories.get("tests", 0),
        "has_dockerfile": any(PurePosixPath(f).name.startswith("Dockerfile") for f in tracked),
        "has_docker_compose": any(PurePosixPath(f).name.startswith(("docker-compose", "compose.y")) for f in tracked),
        "ecosystems": ecosystems,
    }
    structure_ev = store.add("structure", src, f"{len(tracked)} tracked files; ecosystems: {', '.join(ecosystems) or 'none detected'}", structure)

    # --- .gitignore --------------------------------------------------------------------------
    gitignore_text = read_text(repo, ".gitignore")
    missing = []
    if gitignore_text is not None:
        for label, (needles, display) in _IGNORE_EXPECTATIONS.items():
            if label in ecosystems and not any(n in gitignore_text for n in needles):
                missing.append({"ecosystem": label, "expected": display})
        if ".env" not in gitignore_text and any(k in ecosystems for k in ("Node.js", "Python", "PHP", "Ruby", "Next.js")):
            missing.append({"ecosystem": "general", "expected": [".env"]})
    wrongly_tracked: dict[str, list[str]] = {}
    for f in tracked:
        for label, pattern in _SHOULD_NOT_BE_TRACKED:
            if pattern.search(f):
                wrongly_tracked.setdefault(label, []).append(f)
                break
    gitignore = {
        "present": ".gitignore" in tracked_set,
        "nested_gitignores": [f for f in tracked if f.endswith("/.gitignore")][:10],
        "missing_expected_patterns": missing,
        "tracked_files_that_should_be_ignored": {k: {"count": len(v), "examples": v[:5]} for k, v in wrongly_tracked.items()},
    }
    gitignore_ev = store.add("gitignore", src, f".gitignore {'present' if gitignore['present'] else 'MISSING'}; {sum(len(v) for v in wrongly_tracked.values())} tracked file(s) that are normally ignored", gitignore)

    # --- environment files -------------------------------------------------------------------
    env_tracked = [f for f in tracked if _ENV_FILE.search(f)]
    real_env = [f for f in env_tracked if not _ENV_SAFE.search(f)]
    env_details = []
    for f in real_env:
        text = read_text(repo, f) or ""
        keys = [m.group(1) for m in re.finditer(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\S", text, re.M)]
        env_details.append({"file": f, "non_empty_variables": len(keys), "variable_names": keys[:20]})
    history_env = sorted({f.path for c in commits for f in c.files if _ENV_FILE.search(f.path) and not _ENV_SAFE.search(f.path)} - tracked_set)
    cred_vars = credential_variables(repo, env_tracked)
    environment = {
        "credential_variables": cred_vars,
        "credential_variable_classes": dict(Counter(v["classification"] for v in cred_vars)),
        "env_files_tracked": env_tracked,
        "real_env_files_tracked": env_details,
        "example_env_present": any(_ENV_SAFE.search(f) for f in env_tracked),
        "env_files_in_history_but_removed": history_env[:20],
    }
    env_ev = store.add("environment", src, f"{len(real_env)} real env file(s) tracked; {len(history_env)} removed env file(s) remain in history; credential-named variables: {dict(Counter(v['classification'] for v in cred_vars)) or 'none'} (values not recorded)", environment)

    # --- secrets -----------------------------------------------------------------------------
    hits = scan_secrets(repo, tracked)
    seen = {(h["file"], h["line"]) for h in hits}
    for v in cred_vars:
        # A secret-shaped value in a real (non-template) env file is a credential indicator. Only the
        # location, variable name and length are kept.
        if v["classification"] == "SECRET_LIKE" and not v["is_template_file"] and (v["file"], v["line"]) not in seen:
            hits.append({"file": v["file"], "line": v["line"], "kind": "credential_variable_value", "severity": "HIGH", "redacted": f"<{v['variable']}: {v['value_length']} chars, not stored>", "in_template_or_docs": False})
    secret_evidence = [
        store.add("secret_indicator", src, f"{h['kind']} indicator at {h['file']}:{h['line']} ({h['redacted']})", h)
        for h in hits if h["severity"] != "LOW"
    ][:40]
    secrets = {
        "scanned_files": len(tracked),
        "indicators": hits[:100],
        "by_kind": dict(Counter(h["kind"] for h in hits)),
        "scope": "tracked files at evaluated HEAD (history contents are not scanned; removed env files are listed under environment)",
    }

    # --- dependencies ------------------------------------------------------------------------
    names = Counter(PurePosixPath(f).name for f in tracked if classify_path(f) != "vendored")
    issues = []
    node_dirs: dict[str, set[str]] = {}
    for f in tracked:
        p = PurePosixPath(f)
        if p.name in {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock"} and classify_path(f) == "lockfile":
            node_dirs.setdefault(str(p.parent), set()).add(p.name)
    for d, locks in node_dirs.items():
        if len(locks) > 1:
            issues.append({"issue": f"conflicting Node lockfiles in '{d}': {', '.join(sorted(locks))}", "severity": "LOW"})
    if names.get("package.json") and not node_dirs:
        issues.append({"issue": "package.json present but no lockfile is committed", "severity": "LOW"})
    py_ext = ext_counts.get(".py", 0) + ext_counts.get(".ipynb", 0)
    js_ext = sum(ext_counts.get(e, 0) for e in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".vue", ".svelte"))
    if "Python" in ecosystems and py_ext == 0:
        issues.append({"issue": f"Python manifest ({', '.join(ecosystems['Python'])}) present but the repository contains no Python source", "severity": "LOW"})
    if "Node.js" in ecosystems and js_ext == 0:
        issues.append({"issue": "package.json present but the repository contains no JavaScript/TypeScript source", "severity": "LOW"})
    if py_ext >= 3 and "Python" not in ecosystems:
        issues.append({"issue": f"{py_ext} Python source files but no dependency manifest (requirements.txt / pyproject.toml)", "severity": "LOW"})
    vendored = [f for f in tracked if classify_path(f) == "vendored"]
    if vendored:
        issues.append({"issue": f"{len(vendored)} vendored/installed dependency files are committed (e.g. {vendored[0]})", "severity": "MEDIUM"})
    dependencies = {
        "manifests": sorted(f for f in tracked if PurePosixPath(f).name in {"package.json", "requirements.txt", "pyproject.toml", "setup.py", "Pipfile", "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "composer.json", "Gemfile"} and classify_path(f) != "vendored")[:30],
        "lockfiles": sorted(f for f in tracked if PurePosixPath(f).name in LOCKFILES)[:30],
        "committed_dependency_files": len(vendored),
        "issues": issues,
    }
    deps_ev = store.add("dependencies", src, f"{len(dependencies['manifests'])} manifest(s), {len(dependencies['lockfiles'])} lockfile(s), {len(issues)} hygiene issue(s)", dependencies)

    generated = {c: categories.get(c, 0) for c in ("generated", "vendored", "build_output", "minified", "lockfile", "dataset", "model_artifact", "binary") if categories.get(c)}
    return {
        "structure": structure,
        "gitignore": gitignore,
        "environment": environment,
        "secrets": secrets,
        "dependencies": dependencies,
        "generated_files": generated,
        "evidence": {"structure": structure_ev, "gitignore": gitignore_ev, "environment": env_ev, "dependencies": deps_ev, "secrets": secret_evidence},
    }
