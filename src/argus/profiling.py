"""Deterministic repository profiling in the context of an assigned task.

The profiler uses static evidence: tracked paths, source symbols, dependency manifests, routes,
configuration, tests and README structure. It never executes repository code. README text may
describe a repository, but it is never accepted as proof that a feature is implemented.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional, Sequence

from argus.collectors import ci as ci_mod
from argus.collectors import commits as commits_mod
from argus.collectors import hygiene as hygiene_mod
from argus.collectors import readme as readme_mod
from argus.collectors import scc as scc_mod
from argus.collectors.classify import classify_path, component_of, language_of
from argus.collectors.gitutil import default_branch, read_text, tracked_files
from argus.models import RepositoryProfile, RequirementAssessment, RequirementStatus, confidence_level
from argus.tasks import TaskDefinition, content_tokens, tokens_match

PROFILE_VERSION = "1.0"
PROFILE_METHOD = (
    "Static profile from tracked files: existing ARGUS source/classification collectors, dependency "
    "manifest parsing, symbol and route extraction, test/config/documentation inventory and "
    "architecture heuristics. Repository code is never executed."
)

MAX_SCAN_FILES = 700
MAX_FILE_BYTES = 250_000
MAX_INDEX_TERMS = 2500
MAX_FEATURES = 60
MAX_DEPENDENCIES = 250

_SOURCE_CATEGORIES = {"source", "tests"}
# Requirement coverage may cite code, tests, and deployment/configuration artifacts. Documentation is
# kept in a separate vocabulary: a README or docs mention can never establish implementation.
_IMPLEMENTATION_CATEGORIES = {"source", "tests", "config", "ci"}
_LINT_FILES = {
    "ruff.toml", ".ruff.toml", ".pylintrc", "pylintrc", "mypy.ini", ".flake8", "tox.ini",
    ".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", "eslint.config.js", "eslint.config.mjs",
    ".prettierrc", "prettier.config.js", "biome.json", ".golangci.yml", ".golangci.yaml", "clippy.toml",
    "rustfmt.toml", ".editorconfig",
}
_COVERAGE_FILES = {
    ".coveragerc", "coverage.xml", "codecov.yml", ".codecov.yml", "jest.config.js", "jest.config.ts",
    "vitest.config.ts", "vitest.config.js", "cypress.config.ts", "playwright.config.ts", ".nycrc", ".nycrc.json",
}
_ENTRY_NAMES = {
    "main.py", "app.py", "server.py", "manage.py", "wsgi.py", "asgi.py", "index.js", "index.jsx",
    "index.ts", "index.tsx", "main.go", "main.rs", "program.cs", "application.java", "app.ts", "app.tsx",
    "src/main.py", "src/app.py", "src/server.py", "src/main.ts", "src/main.tsx", "src/index.ts", "src/index.tsx",
    "src/app.ts", "src/app.tsx", "cmd/main.go", "app/main.py", "backend/main.py", "frontend/src/main.tsx",
}
_TEST_FRAMEWORKS = {
    "pytest": "pytest", "unittest": "unittest", "nose": "nose", "jest": "Jest", "vitest": "Vitest",
    "mocha": "Mocha", "jasmine": "Jasmine", "cypress": "Cypress", "playwright": "Playwright",
    "junit": "JUnit", "testng": "TestNG", "xunit": "xUnit", "nunit": "NUnit", "phpunit": "PHPUnit",
    "rspec": "RSpec", "minitest": "Minitest", "@testing-library/react": "Testing Library",
}
_TEST_PATTERNS = {
    "Python": re.compile(r"(?m)^\s*(?:async\s+)?def\s+test_\w+\s*\("),
    "JavaScript": re.compile(r"(?m)^\s*(?:it|test)\s*\(\s*['\"`]"),
    "TypeScript": re.compile(r"(?m)^\s*(?:it|test)\s*\(\s*['\"`]"),
    "Java": re.compile(r"(?m)^\s*@Test\b"),
    "C#": re.compile(r"(?m)^\s*\[(?:Fact|Test|Theory)\]"),
    "Go": re.compile(r"(?m)^\s*func\s+Test\w+\s*\("),
    "Rust": re.compile(r"(?m)^\s*#\[(?:tokio::)?test\]"),
    "PHP": re.compile(r"(?m)^\s*(?:public\s+)?function\s+test\w+\s*\("),
    "Ruby": re.compile(r"(?m)^\s*(?:it|test)\s+['\"]"),
}
_TODO = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")
_ROUTE_PATTERNS = [
    re.compile(r"@(?:app|router|bp|blueprint)\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]", re.I),
    re.compile(r"@(?:Get|Post|Put|Patch|Delete)Mapping\(\s*(?:value\s*=\s*)?['\"]?([^'\"\)]*)", re.I),
    re.compile(r"\b(?:app|router)\.(get|post|put|patch|delete)\(\s*['\"`]([^'\"`]+)['\"`]", re.I),
    re.compile(r"\bHandleFunc\(\s*['\"]([^'\"]+)['\"]"),
]
_CLI_PATTERNS = [
    re.compile(r"add_parser\(\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"@(?:click|app|cli)\.command\(\s*(?:name\s*=\s*)?['\"]?([A-Za-z0-9_-]+)?"),
    re.compile(r"\.command\(\s*['\"]([^'\"]+)['\"]"),
]


def _read(repo: Path, rel: str, limit: int = MAX_FILE_BYTES) -> Optional[str]:
    return read_text(repo, rel, limit=limit)


def _clean_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.@/+:-]+", " ", value).strip()[:120]


def _add_dependency(
    runtime: dict[str, dict[str, Any]], development: dict[str, dict[str, Any]],
    name: str, version: str, manifest: str, scope: str,
) -> None:
    name = _clean_name(name)
    if not name or len(runtime) + len(development) >= MAX_DEPENDENCIES:
        return
    target = development if scope == "development" else runtime
    key = name.casefold()
    for existing in target:
        if existing.casefold() == key:
            return
    target[name] = {"version": _clean_name(version) or "unspecified", "manifest": manifest}


def _parse_requirements(text: str, manifest: str, scope: str, runtime: dict, development: dict) -> None:
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-", "git+", "http:", "https:", "file:")):
            continue
        match = re.match(r"^([A-Za-z0-9_.\-]+(?:\[[^\]]+\])?)\s*(?:[<>=!~]=?\s*([^;#\s]+))?", line)
        if match:
            _add_dependency(runtime, development, match.group(1), match.group(2) or "", manifest, scope)


def _parse_pyproject(text: str, manifest: str, runtime: dict, development: dict) -> None:
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        return
    project = data.get("project") or {}
    for item in project.get("dependencies") or []:
        match = re.match(r"^([A-Za-z0-9_.\-]+(?:\[[^\]]+\])?)\s*(.*)$", str(item))
        if match:
            _add_dependency(runtime, development, match.group(1), match.group(2), manifest, "runtime")
    for group, items in (project.get("optional-dependencies") or {}).items():
        scope = "development" if re.search(r"(?i)dev|test|lint|doc", str(group)) else "runtime"
        for item in items or []:
            match = re.match(r"^([A-Za-z0-9_.\-]+(?:\[[^\]]+\])?)\s*(.*)$", str(item))
            if match:
                _add_dependency(runtime, development, match.group(1), match.group(2), manifest, scope)
    poetry = (data.get("tool") or {}).get("poetry") or {}
    for name, spec in (poetry.get("dependencies") or {}).items():
        if str(name).casefold() != "python":
            version = spec if isinstance(spec, str) else (spec or {}).get("version", "")
            _add_dependency(runtime, development, str(name), str(version or ""), manifest, "runtime")
    for group, group_data in (poetry.get("group") or {}).items():
        scope = "development" if re.search(r"(?i)dev|test|lint", str(group)) else "runtime"
        for name, spec in ((group_data or {}).get("dependencies") or {}).items():
            version = spec if isinstance(spec, str) else (spec or {}).get("version", "")
            _add_dependency(runtime, development, str(name), str(version or ""), manifest, scope)
    for name, spec in (poetry.get("dev-dependencies") or {}).items():
        version = spec if isinstance(spec, str) else (spec or {}).get("version", "")
        _add_dependency(runtime, development, str(name), str(version or ""), manifest, "development")


def _parse_package_json(text: str, manifest: str, runtime: dict, development: dict) -> None:
    try:
        data = json.loads(text)
    except ValueError:
        return
    for key, scope in (("dependencies", "runtime"), ("peerDependencies", "runtime"), ("devDependencies", "development")):
        for name, version in (data.get(key) or {}).items():
            _add_dependency(runtime, development, str(name), str(version), manifest, scope)


def _parse_go_mod(text: str, manifest: str, runtime: dict, development: dict) -> None:
    body = text
    for match in re.finditer(r"(?ms)^\s*require\s*\((.*?)^\s*\)", text):
        body += "\n" + match.group(1)
    for line in body.splitlines():
        match = re.match(r"^\s*([A-Za-z0-9_.\-/]+)\s+(v[^\s]+)", line)
        if match:
            _add_dependency(runtime, development, match.group(1), match.group(2), manifest, "runtime")


def _parse_cargo(text: str, manifest: str, runtime: dict, development: dict) -> None:
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        return
    for section, scope in (("dependencies", "runtime"), ("dev-dependencies", "development"), ("build-dependencies", "development")):
        for name, spec in (data.get(section) or {}).items():
            version = spec if isinstance(spec, str) else (spec or {}).get("version", "")
            _add_dependency(runtime, development, str(name), str(version or ""), manifest, scope)
    workspace = data.get("workspace") or {}
    for name, spec in (workspace.get("dependencies") or {}).items():
        version = spec if isinstance(spec, str) else (spec or {}).get("version", "")
        _add_dependency(runtime, development, str(name), str(version or ""), manifest, "runtime")


def _parse_composer(text: str, manifest: str, runtime: dict, development: dict) -> None:
    try:
        data = json.loads(text)
    except ValueError:
        return
    for key, scope in (("require", "runtime"), ("require-dev", "development")):
        for name, version in (data.get(key) or {}).items():
            _add_dependency(runtime, development, str(name), str(version), manifest, scope)


def _parse_simple_manifest(text: str, manifest: str, runtime: dict, development: dict, *, scope: str = "runtime") -> None:
    for line in text.splitlines():
        match = re.match(r"^\s*(?:gem|package|library|requires?)\s*['\"]([^'\"]+)['\"]", line)
        if match:
            _add_dependency(runtime, development, match.group(1), "", manifest, scope)
        elif manifest.endswith((".gradle", ".gradle.kts")):
            match = re.match(r"^\s*(?:implementation|api|compileOnly|runtimeOnly|testImplementation)\s*['\"]([^'\"]+)['\"]", line)
            if match:
                line_scope = "development" if line.lstrip().startswith("test") else "runtime"
                parts = match.group(1).split(":")
                _add_dependency(runtime, development, parts[1] if len(parts) > 1 else parts[0], parts[-1] if len(parts) > 2 else "", manifest, line_scope)


def _parse_pom(text: str, manifest: str, runtime: dict, development: dict) -> None:
    for block in re.findall(r"(?is)<dependency>(.*?)</dependency>", text)[:200]:
        name = re.search(r"(?is)<artifactId>\s*([^<\s]+)\s*</artifactId>", block)
        version = re.search(r"(?is)<version>\s*([^<\s]+)\s*</version>", block)
        scope = "development" if re.search(r"(?is)<scope>\s*test\s*</scope>", block) else "runtime"
        if name:
            _add_dependency(runtime, development, name.group(1), version.group(1) if version else "", manifest, scope)


def parse_dependencies(repo: Path, tracked: Sequence[str]) -> dict[str, Any]:
    runtime: dict[str, dict[str, Any]] = {}
    development: dict[str, dict[str, Any]] = {}
    manifests: list[str] = []
    ecosystems: set[str] = set()
    for rel in tracked:
        name = PurePosixPath(rel).name
        lower = name.casefold()
        if classify_path(rel) in {"vendored", "build_output", "generated", "minified", "binary", "model_artifact", "dataset"}:
            continue
        parser = None
        ecosystem = None
        if lower.startswith("requirements") and lower.endswith((".txt", ".in")):
            parser, ecosystem = "requirements", "Python"
        elif lower == "pyproject.toml":
            parser, ecosystem = "pyproject", "Python"
        elif lower in {"setup.cfg", "setup.py"}:
            parser, ecosystem = "simple", "Python"
        elif lower == "package.json":
            parser, ecosystem = "package", "Node.js"
        elif lower == "go.mod":
            parser, ecosystem = "go", "Go"
        elif lower == "cargo.toml":
            parser, ecosystem = "cargo", "Rust"
        elif lower == "composer.json":
            parser, ecosystem = "composer", "PHP"
        elif lower in {"gemfile", "rakefile"}:
            parser, ecosystem = "simple", "Ruby"
        elif lower == "pom.xml":
            parser, ecosystem = "pom", "Java"
        elif lower.endswith((".gradle", ".gradle.kts")):
            parser, ecosystem = "simple", "Java/Kotlin"
        elif lower in {"environment.yml", "environment.yaml"}:
            parser, ecosystem = "environment", "Python"
        if not parser:
            continue
        text = _read(repo, rel, limit=500_000)
        if text is None:
            continue
        manifests.append(rel)
        ecosystems.add(ecosystem)
        scope = "development" if re.search(r"(?i)dev|test|lint", lower) else "runtime"
        if parser == "requirements":
            _parse_requirements(text, rel, scope, runtime, development)
        elif parser == "pyproject":
            _parse_pyproject(text, rel, runtime, development)
        elif parser == "package":
            _parse_package_json(text, rel, runtime, development)
        elif parser == "go":
            _parse_go_mod(text, rel, runtime, development)
        elif parser == "cargo":
            _parse_cargo(text, rel, runtime, development)
        elif parser == "composer":
            _parse_composer(text, rel, runtime, development)
        elif parser == "pom":
            _parse_pom(text, rel, runtime, development)
        elif parser == "environment":
            for line in text.splitlines():
                match = re.match(r"^\s*-\s+([A-Za-z0-9_.\-]+)(?:=([^\s#]+))?", line)
                if match and match.group(1).casefold() not in {"pip", "python"}:
                    _add_dependency(runtime, development, match.group(1), match.group(2) or "", rel, "runtime")
        else:
            _parse_simple_manifest(text, rel, runtime, development, scope=scope)
    return {
        "manifests": sorted(manifests),
        "ecosystems": sorted(ecosystems),
        "runtime": dict(sorted(runtime.items(), key=lambda item: item[0].casefold())),
        "development": dict(sorted(development.items(), key=lambda item: item[0].casefold())),
        "total": len(runtime) + len(development),
        "method": "Manifest parsing only. Versions are recorded as declared; resolution, licences and vulnerabilities are not assessed.",
    }


def _extract_symbols(text: str, language: str) -> list[dict[str, Any]]:
    patterns = {
        "Python": [re.compile(r"(?m)^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)"), re.compile(r"(?m)^\s*class\s+([A-Za-z_]\w*)")],
        "JavaScript": [
            re.compile(r"(?m)^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"),
            re.compile(r"(?m)^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)"),
            re.compile(r"(?m)^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\("),
        ],
        "TypeScript": [
            re.compile(r"(?m)^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"),
            re.compile(r"(?m)^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)"),
            re.compile(r"(?m)^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\("),
        ],
        "Go": [re.compile(r"(?m)^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)"), re.compile(r"(?m)^\s*type\s+([A-Za-z_]\w*)\s+struct")],
        "Rust": [re.compile(r"(?m)^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)"), re.compile(r"(?m)^\s*(?:pub\s+)?(?:struct|enum|trait)\s+([A-Za-z_]\w*)")],
        "Java": [re.compile(r"(?m)^\s*(?:public\s+|private\s+|protected\s+)?(?:class|interface|enum|record)\s+([A-Za-z_]\w*)")],
        "C#": [re.compile(r"(?m)^\s*(?:public\s+|private\s+|internal\s+)?(?:class|interface|enum|record|struct)\s+([A-Za-z_]\w*)")],
        "Kotlin": [re.compile(r"(?m)^\s*(?:data\s+)?(?:class|interface|object)\s+([A-Za-z_]\w*)")],
        "Ruby": [re.compile(r"(?m)^\s*(?:class|module)\s+([A-Za-z_]\w*)"), re.compile(r"(?m)^\s*def\s+([A-Za-z_]\w*[!?]?)")],
    }
    found: list[dict[str, Any]] = []
    seen = set()
    for pattern in patterns.get(language, []):
        for match in pattern.finditer(text):
            name = match.group(1)
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            found.append({"name": name, "line": text[: match.start()].count("\n") + 1})
            if len(found) >= 40:
                return found
    return found


def _extract_routes(text: str, rel: str) -> list[dict[str, Any]]:
    rows = []
    seen = set()
    for pattern in _ROUTE_PATTERNS:
        for match in pattern.finditer(text):
            groups = [group for group in match.groups() if group]
            if len(groups) >= 2:
                method, path = str(groups[0]).upper(), str(groups[1])
            elif groups:
                method, path = "GET", str(groups[0])
            else:
                continue
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                method, path = "GET", str(groups[-1])
            key = (method, path, rel, text[: match.start()].count("\n") + 1)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"method": method, "path": path[:160], "file": rel, "line": key[3]})
            if len(rows) >= 40:
                return rows
    return rows


def _extract_cli_commands(text: str, rel: str) -> list[dict[str, Any]]:
    rows = []
    for pattern in _CLI_PATTERNS:
        for match in pattern.finditer(text):
            name = next((group for group in match.groups() if group), "")
            rows.append({"name": name or PurePosixPath(rel).stem, "file": rel, "line": text[: match.start()].count("\n") + 1})
            if len(rows) >= 20:
                return rows
    return rows


def _weighted_score(components: list[dict[str, Any]]) -> tuple[Optional[float], float]:
    available = [item for item in components if item.get("normalized") is not None]
    total = sum(float(item["weight"]) for item in available)
    if not total:
        return None, 0.0
    score = sum(float(item["normalized"]) * float(item["weight"]) for item in available) / total
    confidence = min(1.0, total)
    return round(max(0.0, min(1.0, score)), 6), round(confidence, 6)


def _documentation_profile(repo: Path, tracked: Sequence[str], readme: Optional[dict[str, Any]]) -> dict[str, Any]:
    readme_path = (readme or {}).get("path")
    text = _read(repo, readme_path, limit=2_000_000) if readme_path else ""
    headings = re.findall(r"(?m)^#{1,4}\s+(.+?)\s*#*\s*$", text or "")
    docs = [rel for rel in tracked if classify_path(rel) == "docs"]
    license_files = [rel for rel in tracked if PurePosixPath(rel).name.upper().startswith(("LICENSE", "COPYING", "NOTICE"))]
    contributing = any("contribut" in Path(rel).name.casefold() for rel in tracked)
    changelog = any("changelog" in Path(rel).name.casefold() or "changes" in Path(rel).name.casefold() for rel in tracked)
    plain = re.sub(r"[#*`>\[\]()]", " ", text or "")
    summary = re.sub(r"\s+", " ", plain).strip()[:1200]
    return {
        "readme_present": bool(readme_path),
        "readme_path": readme_path,
        "readme_chars": len(text or ""),
        "headings": headings[:30],
        "summary": summary,
        "documentation_files": docs[:100],
        "license_files": license_files[:5],
        "contributing": contributing,
        "changelog": changelog,
        "method": "README structure and documentation inventory. README statements are not implementation evidence.",
    }


def _technologies(readme: Optional[dict[str, Any]], dependencies: dict[str, Any], tracked: Sequence[str], readme_text: str) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}

    def add(name: str, category: str, evidence: str, confidence: float) -> None:
        key = name.casefold()
        existing = rows.get(key)
        if existing:
            if evidence and evidence not in existing["evidence"]:
                existing["evidence"].append(evidence)
            existing["confidence"] = max(existing["confidence"], confidence)
            return
        rows[key] = {"name": name, "category": category, "evidence": [evidence] if evidence else [], "confidence": confidence}

    for claim in (readme or {}).get("claims", []):
        if claim.get("status") in {"VERIFIED", "PARTIALLY_VERIFIED"}:
            add(str(claim["technology"]), "README claim cross-checked against files", claim.get("supporting_evidence", [""])[0] if claim.get("supporting_evidence") else "", 0.9 if claim.get("status") == "VERIFIED" else 0.6)
    for scope in ("runtime", "development"):
        for name in list((dependencies.get(scope) or {}))[:80]:
            add(name, f"{scope} dependency", (dependencies.get(scope) or {})[name].get("manifest", ""), 1.0)
    path_rules = [
        ("Docker", "containerisation", r"(^|/)Dockerfile[^/]*$"),
        ("Docker Compose", "containerisation", r"(^|/)(docker-)?compose[^/]*\.ya?ml$"),
        ("Kubernetes / Helm", "orchestration", r"(^|/)(k8s|kubernetes|helm|charts)/"),
        ("Terraform", "infrastructure as code", r"\.tf$"),
        ("GitHub Actions", "CI/CD", r"^\.github/workflows/[^/]+\.ya?ml$"),
        ("GitLab CI", "CI/CD", r"(^|/)\.gitlab-ci\.ya?ml$"),
        ("Make", "build tooling", r"(^|/)Makefile$"),
    ]
    for name, category, pattern in path_rules:
        matches = [rel for rel in tracked if re.search(pattern, rel, re.I)][:4]
        if matches:
            add(name, category, ", ".join(matches), 1.0)
    if re.search(r"(?i)kubernetes|k8s|helm", readme_text):
        add("Kubernetes / Helm", "README mention (not implementation evidence)", "", 0.2)
    return sorted(rows.values(), key=lambda item: (-item["confidence"], item["name"].casefold()))[:80]


def _entry_points(repo: Path, tracked: Sequence[str], dependencies: dict[str, Any]) -> list[str]:
    entries = []
    for rel in tracked:
        lower = rel.casefold()
        if lower in _ENTRY_NAMES or re.search(r"(^|/)cmd/[^/]+/main\.go$", rel):
            entries.append(rel)
    for manifest in dependencies.get("manifests", []):
        if PurePosixPath(manifest).name == "package.json":
            text = _read(repo, manifest, limit=500_000)
            try:
                scripts = (json.loads(text or "{}").get("scripts") or {}) if text else {}
            except ValueError:
                scripts = {}
            entries.extend(f"{manifest}: npm run {key}" for key in sorted(scripts) if key in {"start", "dev", "build", "serve"})
        if PurePosixPath(manifest).name == "pyproject.toml":
            text = _read(repo, manifest, limit=500_000) or ""
            try:
                scripts = ((tomllib.loads(text).get("project") or {}).get("scripts") or {})
            except (tomllib.TOMLDecodeError, ValueError):
                scripts = {}
            entries.extend(f"{manifest}: console script {key}" for key in sorted(scripts))
    if "Procfile" in {PurePosixPath(rel).name for rel in tracked}:
        entries.append("Procfile")
    return list(dict.fromkeys(entries))[:40]


def _architecture_profile(
    tracked: Sequence[str], dependencies: dict[str, Any], features: Sequence[dict[str, Any]],
    routes: Sequence[dict[str, Any]], entry_points: Sequence[str], source_files: Sequence[str],
) -> dict[str, Any]:
    dirs = {part.casefold() for rel in tracked for part in PurePosixPath(rel).parts[:-1]}
    all_paths = "\n".join(rel.casefold() for rel in tracked)
    dep_names = {name.casefold() for scope in ("runtime", "development") for name in (dependencies.get(scope) or {})}
    patterns: list[str] = []
    pattern_evidence: dict[str, list[str]] = {}

    def mark(name: str, condition: bool, evidence: Iterable[str]) -> None:
        if condition:
            patterns.append(name)
            pattern_evidence[name] = list(dict.fromkeys(evidence))[:6]

    api = bool(dirs & {"api", "routes", "controllers", "handlers", "endpoints"})
    services = bool(dirs & {"services", "service", "domain", "usecases", "use_cases", "core"})
    storage = bool(dirs & {"models", "model", "repositories", "repository", "repos", "db", "database", "persistence"})
    mark("layered service boundaries", api and services and storage, ["api/routes", "services", "models/repositories"])
    mark("model-view-controller", bool(dirs & {"models", "views", "controllers"}) and bool(dirs & {"views", "templates"}), ["models", "views", "controllers"])
    mark("component-based frontend", bool(dirs & {"components", "pages", "app", "hooks", "views"}) and any(rel.endswith((".tsx", ".jsx", ".vue", ".svelte")) for rel in tracked), ["components/pages/hooks"])
    package_manifests = {
        (parts[0].casefold(), parts[1].casefold())
        for rel in tracked
        for parts in (PurePosixPath(rel).parts,)
        if len(parts) >= 3
        and parts[0].casefold() in {"packages", "apps", "services", "modules"}
        and parts[-1].casefold() in {"package.json", "pyproject.toml", "go.mod", "cargo.toml"}
    }
    mark(
        "monorepo with multiple packages", len(package_manifests) >= 2,
        [f"{root}/{package}/" for root, package in sorted(package_manifests)[:4]],
    )
    mark("command-line interface", bool(entry_points) and (bool(dirs & {"cli", "commands", "cmd"}) or any(feature.get("kind") == "cli_command" for feature in features)), ["cli/commands", "entry point"])
    mark("containerised service", bool(dirs & {"dockerfile"}) or any(PurePosixPath(rel).name.casefold().startswith("dockerfile") for rel in tracked), ["Dockerfile"])
    mark("event/queue processing", bool(dirs & {"workers", "worker", "consumers", "consumer", "jobs", "tasks", "queue"}) or bool(dep_names & {"celery", "rq", "kafka-python", "kafkajs", "pika", "amqplib", "bullmq"}), ["workers/tasks", "queue dependency"])
    mark("data or ML pipeline", bool(dirs & {"notebooks", "training", "models", "pipelines", "experiments"}) and bool(dep_names & {"torch", "tensorflow", "sklearn", "scikit-learn", "pandas", "numpy", "transformers", "xgboost", "lightgbm"}), ["notebooks/pipelines", "ML dependency"])
    mark(
        "reusable library",
        any(PurePosixPath(rel).name == "__init__.py" for rel in tracked)
        and not routes and not entry_points and "containerised service" not in patterns,
        ["package __init__", "no service routes or entry point"],
    )
    mark("HTTP API", bool(routes), [route["file"] for route in routes[:4]])

    components = [
        {"id": "pattern_coherence", "label": "Architecture patterns with file evidence", "normalized": min(1.0, len(patterns) / 2), "weight": 0.30, "raw": patterns},
        {"id": "entrypoint", "label": "Executable/app entry point", "normalized": 1.0 if entry_points else 0.0, "weight": 0.20, "raw": list(entry_points[:5])},
        {"id": "modularity", "label": "Source split across components", "normalized": min(1.0, len({component_of(rel) for rel in source_files}) / 4), "weight": 0.20, "raw": len({component_of(rel) for rel in source_files})},
        {"id": "configuration", "label": "Build/service configuration present", "normalized": 1.0 if dependencies.get("manifests") or any(rel.casefold().startswith("docker") for rel in tracked) else 0.0, "weight": 0.15, "raw": len(dependencies.get("manifests") or [])},
        {"id": "dependency_management", "label": "Dependency manifest present", "normalized": 1.0 if dependencies.get("manifests") else 0.0, "weight": 0.15, "raw": dependencies.get("manifests") or []},
    ]
    if not source_files:
        for component in components:
            component["normalized"] = None
    score, confidence = _weighted_score(components)
    return {
        "patterns": patterns,
        "pattern_evidence": pattern_evidence,
        "entry_points": list(dict.fromkeys(entry_points))[:20],
        "module_count": len({component_of(rel) for rel in source_files}),
        "components": components,
        "score": score,
        "confidence": confidence,
        "method": "Path and symbol heuristics. Patterns are descriptive, not a ranking of architectural styles; different valid architectures are not penalised.",
    }


def _testing_profile(
    repo: Path, tracked: Sequence[str], scc: dict[str, Any], dependencies: dict[str, Any], ci: Optional[dict[str, Any]],
) -> dict[str, Any]:
    test_files = [rel for rel in tracked if classify_path(rel) == "tests"]
    source_files = [rel for rel in tracked if classify_path(rel) == "source"]
    frameworks = sorted({label for name, label in _TEST_FRAMEWORKS.items() if name.casefold() in {dep.casefold() for scope in ("runtime", "development") for dep in (dependencies.get(scope) or {})}})
    case_count = 0
    scanned = 0
    for rel in test_files[:80]:
        text = _read(repo, rel, limit=300_000)
        if not text:
            continue
        scanned += 1
        language = language_of(rel)
        pattern = _TEST_PATTERNS.get(language)
        if pattern:
            case_count += len(pattern.findall(text))
        else:
            case_count += len(re.findall(r"(?m)^\s*(?:def\s+test_|it\s*\(|test\s*\(|func\s+Test)", text))
    names = {PurePosixPath(rel).name.casefold() for rel in tracked}
    coverage_configured = bool(names & _COVERAGE_FILES) or any("coverage" in rel.casefold() and PurePosixPath(rel).suffix.casefold() in {".xml", ".json", ".html"} for rel in tracked)
    ci_capabilities = {str(value).casefold() for value in ((ci or {}).get("capabilities") or [])}
    ci_test = "test" in ci_capabilities or any(
        re.search(r"(?i)\b(?:pytest|tox|jest|vitest|npm (?:run )?test|go test|cargo test|mvn test|gradle test)\b", str(workflow.get("commands", "")) + " " + str(workflow.get("capabilities", "")))
        for workflow in ((ci or {}).get("workflows") or [])
    )
    source_code = sum(int(row.get("code", 0)) for row in (scc.get("files") or []) if classify_path(str(row.get("path", ""))) == "source")
    test_code = sum(int(row.get("code", 0)) for row in (scc.get("files") or []) if classify_path(str(row.get("path", ""))) == "tests")
    file_ratio = len(test_files) / max(1, len(source_files)) if source_files else 0.0
    loc_ratio = test_code / max(1, source_code) if source_code else 0.0
    components = [
        {"id": "tests_present", "label": "Test files present", "normalized": 1.0 if test_files else 0.0, "weight": 0.25, "raw": len(test_files)},
        {"id": "test_file_ratio", "label": "Test/source file ratio (target 0.25)", "normalized": min(1.0, file_ratio / 0.25) if source_files else 0.0, "weight": 0.20, "raw": round(file_ratio, 4)},
        {"id": "test_cases", "label": "Static test cases (target 10)", "normalized": min(1.0, case_count / 10), "weight": 0.20, "raw": case_count},
        {"id": "test_loc_ratio", "label": "Test/source LOC ratio (target 0.30)", "normalized": min(1.0, loc_ratio / 0.30) if source_code else 0.0, "weight": 0.15, "raw": round(loc_ratio, 4)},
        {"id": "ci_executes_tests", "label": "CI workflow includes tests", "normalized": 1.0 if ci_test else 0.0, "weight": 0.10, "raw": ci_test},
        {"id": "coverage_configuration", "label": "Coverage configuration/report present", "normalized": 1.0 if coverage_configured else 0.0, "weight": 0.10, "raw": coverage_configured},
    ]
    score, confidence = _weighted_score(components)
    limitations = []
    if not test_files:
        limitations.append("No test files were detected; testing quality is limited to the absence of static test evidence.")
    if not coverage_configured:
        limitations.append("No coverage configuration or report was found; runtime coverage is not measured.")
    limitations.append("Test cases are counted statically. The suite is not executed and passing tests are not claimed.")
    return {
        "test_files": len(test_files),
        "test_file_examples": test_files[:20],
        "test_frameworks": frameworks,
        "test_cases_estimate": case_count,
        "test_files_scanned": scanned,
        "test_to_source_file_ratio": round(file_ratio, 4),
        "test_to_source_loc_ratio": round(loc_ratio, 4),
        "source_files": len(source_files),
        "source_loc": source_code,
        "test_loc": test_code,
        "ci_executes_tests": ci_test,
        "coverage_configured": coverage_configured,
        "components": components,
        "score": score,
        "confidence": confidence,
        "limitations": limitations,
        "method": "Path classification, manifest parsing, static test-case patterns and CI capability detection. No tests are run.",
    }


def _quality_profile(
    repo: Path, tracked: Sequence[str], scc: dict[str, Any], source_texts: dict[str, str], documentation: dict[str, Any],
) -> dict[str, Any]:
    files = [row for row in (scc.get("files") or []) if classify_path(str(row.get("path", ""))) in {"source", "tests"}]
    source = [row for row in files if classify_path(str(row.get("path", ""))) == "source"]
    code_lines = [int(row.get("code", 0)) for row in source]
    large = [row for row in source if int(row.get("code", 0)) > 600]
    large_share = len(large) / len(source) if source else 0.0
    complexity_rows = [int(row.get("complexity") or 0) for row in source if row.get("complexity") is not None]
    complex_share = sum(1 for value in complexity_rows if value >= 50) / len(complexity_rows) if complexity_rows else None
    median_size = sorted(code_lines)[len(code_lines) // 2] if code_lines else None
    names = {PurePosixPath(rel).name.casefold() for rel in tracked}
    lint = sorted(names & _LINT_FILES)
    for rel in tracked:
        if PurePosixPath(rel).name.casefold() == "setup.cfg":
            text = _read(repo, rel, limit=200_000) or ""
            if "[flake8]" in text:
                lint.append(rel)
        if PurePosixPath(rel).name.casefold() == "tsconfig.json":
            text = _read(repo, rel, limit=200_000) or ""
            if re.search(r'"strict"\s*:\s*true', text):
                lint.append(rel + ":strict")
    comment_ratio = float(scc.get("comment_ratio") or 0.0)
    todo_count = sum(len(_TODO.findall(text)) for text in source_texts.values())
    todo_density = todo_count / max(1.0, sum(code_lines) / 1000)
    doc_score = (
        (0.4 if documentation.get("readme_present") else 0.0)
        + (0.2 if int(documentation.get("readme_chars") or 0) >= 1000 else 0.0)
        + (0.2 if documentation.get("documentation_files") else 0.0)
        + (0.2 if documentation.get("license_files") else 0.0)
    )
    comment_score = 1.0 if 0.08 <= comment_ratio <= 0.30 else (min(1.0, comment_ratio / 0.08) * 0.7 if comment_ratio < 0.08 else max(0.0, 1.0 - (comment_ratio - 0.30) / 0.40))
    file_size_score = max(0.0, 1.0 - large_share * 2.5)
    module_size_score = 1.0 if median_size is None or median_size <= 150 else (0.6 if median_size <= 300 else 0.25)
    todo_score = 1.0 / (1.0 + max(0.0, todo_density) / 5.0)
    components = [
        {"id": "file_size", "label": "Source files stay below 600 code lines", "normalized": file_size_score if source else None, "weight": 0.25, "raw": {"large_files": len(large), "source_files": len(source), "examples": [row.get("path") for row in large[:5]]}},
        {"id": "complexity", "label": "Low share of high-complexity files (scc complexity >= 50)", "normalized": (1.0 - complex_share) if complex_share is not None else None, "weight": 0.20, "raw": round(complex_share, 4) if complex_share is not None else None},
        {"id": "module_size", "label": "Median source file size manageable", "normalized": module_size_score if source else None, "weight": 0.15, "raw": median_size},
        {"id": "comments", "label": "Comment ratio in a maintainable range", "normalized": comment_score if source else None, "weight": 0.10, "raw": comment_ratio},
        {"id": "lint_type_config", "label": "Lint/type configuration present", "normalized": 1.0 if lint else 0.25, "weight": 0.15, "raw": lint},
        {"id": "todo_density", "label": "Low TODO/FIXME/HACK density per 1,000 source lines", "normalized": todo_score if source else None, "weight": 0.10, "raw": round(todo_density, 4)},
        {"id": "documentation", "label": "README, docs and licence present", "normalized": doc_score, "weight": 0.10, "raw": {"readme": documentation.get("readme_present"), "docs": len(documentation.get("documentation_files") or []), "licence": bool(documentation.get("license_files"))}},
        {"id": "dependency_management", "label": "Dependency manifest present", "normalized": 1.0 if any(classify_path(rel) == "config" and PurePosixPath(rel).name.casefold() in {"package.json", "pyproject.toml", "requirements.txt", "cargo.toml", "go.mod", "pom.xml", "composer.json", "gemfile"} for rel in tracked) else 0.3, "weight": 0.05, "raw": None},
    ]
    score, confidence = _weighted_score(components)
    if not source:
        # Without recognised source files the maintainability indicators are not measurable. Lint and
        # dependency configuration alone must not be presented as a code-quality score.
        score, confidence = None, 0.0
    limitations = []
    if complexity_rows and len(complexity_rows) < len(source):
        limitations.append("scc complexity was available for only part of the source files.")
    if not complexity_rows:
        limitations.append("Cyclomatic complexity is unavailable because scc did not supply it; the quality score omits that component.")
    if not source:
        limitations.append("No recognised source files were available for maintainability indicators.")
    limitations.append("Quality indicators are static proxies. They do not measure correctness, security or runtime behaviour.")
    return {
        "score": score,
        "confidence": confidence,
        "components": components,
        "large_file_count": len(large),
        "median_source_file_code_lines": median_size,
        "comment_ratio": comment_ratio,
        "complexity_available": bool(complexity_rows),
        "complexity_per_file_available": len(complexity_rows),
        "lint_type_configs": lint,
        "todo_fixme_count": todo_count,
        "limitations": limitations,
        "method": "Weighted static maintainability indicators with explicit normalisation. Missing components are omitted and the remaining weights are renormalised.",
    }


def _feature_rows(
    repo: Path, tracked: Sequence[str], scc: dict[str, Any], source_texts: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    routes: list[dict[str, Any]] = []
    commands: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []
    by_component: dict[str, list[str]] = defaultdict(list)
    features: list[dict[str, Any]] = []
    for rel, text in source_texts.items():
        if classify_path(rel) != "source":
            continue
        language = language_of(rel)
        found = _extract_symbols(text, language)
        for item in found:
            symbols.append({"name": item["name"], "file": rel, "line": item["line"], "language": language})
        routes.extend(_extract_routes(text, rel))
        commands.extend(_extract_cli_commands(text, rel))
        by_component[component_of(rel)].append(rel)

    for route in routes[:30]:
        features.append({
            "name": f"{route['method']} {route['path']}", "kind": "http_endpoint",
            "description": f"HTTP route declared in {route['file']}.",
            "evidence": [route["file"]], "symbols": [], "confidence": 0.9, "verified": True,
        })
    for command in commands[:20]:
        features.append({
            "name": f"CLI command {command['name']}", "kind": "cli_command",
            "description": f"CLI command declaration in {command['file']}.",
            "evidence": [command["file"]], "symbols": [command["name"]], "confidence": 0.8, "verified": True,
        })
    for component, files in sorted(by_component.items(), key=lambda item: (-len(item[1]), item[0])):
        component_symbols = [item["name"] for item in symbols if item["file"] in files][:12]
        if not files:
            continue
        features.append({
            "name": component, "kind": "module",
            "description": f"Implemented module with {len(files)} source file(s)" + (f"; representative symbols: {', '.join(component_symbols[:6])}" if component_symbols else "."),
            "evidence": sorted(files)[:12], "symbols": component_symbols, "confidence": 0.85, "verified": True,
        })
        if any(re.search(r"(?i)(model|schema|entity)$", name) for name in component_symbols):
            features.append({
                "name": f"Data model in {component}", "kind": "data_model",
                "description": f"Data/model classes detected in {component}.",
                "evidence": sorted(files)[:6], "symbols": [name for name in component_symbols if re.search(r"(?i)(model|schema|entity)$", name)][:10],
                "confidence": 0.75, "verified": True,
            })
    tests = [rel for rel in tracked if classify_path(rel) == "tests"]
    if tests:
        features.append({
            "name": "Automated test suite", "kind": "test_suite",
            "description": f"{len(tests)} test file(s) present; static test cases are counted separately.",
            "evidence": tests[:12], "symbols": [], "confidence": 0.9, "verified": True,
        })
    priority = {"http_endpoint": 0, "cli_command": 1, "data_model": 2, "module": 3, "test_suite": 4}
    features.sort(key=lambda item: (priority.get(item["kind"], 9), item["name"].casefold()))
    return features[:MAX_FEATURES], routes[:60], commands[:40], symbols[:500]


class RepositoryProfiler:
    """Build and assess normalised repository profiles without executing repository code."""

    def __init__(self, cfg: Any = None) -> None:
        self.cfg = cfg

    def build(
        self,
        repo: Path,
        *,
        repository: Optional[dict[str, Any]] = None,
        tracked: Optional[Sequence[str]] = None,
        scc: Optional[dict[str, Any]] = None,
        hygiene: Optional[dict[str, Any]] = None,
        readme: Optional[dict[str, Any]] = None,
        ci: Optional[dict[str, Any]] = None,
        commits: Optional[dict[str, Any]] = None,
    ) -> RepositoryProfile:
        repo = Path(repo)
        if not repo.is_dir():
            raise FileNotFoundError(f"repository path is not a directory: {repo}")
        tracked_files_list = list(tracked if tracked is not None else tracked_files(repo))
        repository = dict(repository or {})
        repository_name = (
            f"{repository.get('owner')}/{repository.get('name')}" if repository.get("owner") and repository.get("name")
            else str(repository.get("name") or repository.get("url") or repo.name)
        )

        # Existing collectors are reused when the pipeline has already run them.
        if scc is None:
            scc = scc_mod.analyze(repo, tracked_files_list, getattr(self.cfg, "scc_path", None))
        if readme is None:
            from argus.evidence import EvidenceStore
            readme = readme_mod.analyze(repo, tracked_files_list, EvidenceStore())
        if ci is None:
            from argus.evidence import EvidenceStore
            ci = ci_mod.analyze(repo, tracked_files_list, EvidenceStore())
        if hygiene is None:
            from argus.evidence import EvidenceStore

            # Standalone profiling may not have run the commit collector yet. History improves
            # hygiene checks (for example removed env files), but a non-Git tree must still work.
            history: list[commits_mod.Commit] = []
            try:
                history = commits_mod.parse_history(repo, default_branch(repo))
            except Exception:
                history = []
            hygiene = hygiene_mod.analyze(repo, tracked_files_list, history, EvidenceStore())

        readme_text = _read(repo, (readme or {}).get("path"), limit=2_000_000) if (readme or {}).get("path") else ""
        readme_text = readme_text or ""
        dependencies = parse_dependencies(repo, tracked_files_list)
        documentation = _documentation_profile(repo, tracked_files_list, readme)
        source_only_paths = [rel for rel in tracked_files_list if classify_path(rel) == "source"]
        source_paths = [rel for rel in tracked_files_list if classify_path(rel) in _SOURCE_CATEGORIES]
        source_paths.sort()
        scan_paths = source_paths[:MAX_SCAN_FILES]
        source_texts: dict[str, str] = {}
        digest = hashlib.sha256()
        for rel in scan_paths:
            text = _read(repo, rel)
            if text is None:
                continue
            source_texts[rel] = text
            digest.update(rel.encode("utf-8", "replace"))
            digest.update(hashlib.sha256(text.encode("utf-8", "replace")).digest())

        features, routes, commands, symbols = _feature_rows(repo, tracked_files_list, scc, source_texts)
        entry_points = _entry_points(repo, tracked_files_list, dependencies)
        architecture = _architecture_profile(tracked_files_list, dependencies, features, routes, entry_points, source_only_paths)
        testing = _testing_profile(repo, tracked_files_list, scc, dependencies, ci)
        quality = _quality_profile(repo, tracked_files_list, scc, source_texts, documentation)
        technologies = _technologies(readme, dependencies, tracked_files_list, readme_text)

        languages = []
        total_code = max(1, int((scc.get("totals") or {}).get("code", 0)))
        for row in (scc.get("languages") or [])[:20]:
            languages.append({
                "language": row.get("language"), "files": row.get("files", 0), "code": row.get("code", 0),
                "share_of_code": round(int(row.get("code", 0)) / total_code, 4),
            })
        structure = {
            "tracked_files": len(tracked_files_list),
            "source_files": len([rel for rel in tracked_files_list if classify_path(rel) == "source"]),
            "test_files": len([rel for rel in tracked_files_list if classify_path(rel) == "tests"]),
            "config_files": len([rel for rel in tracked_files_list if classify_path(rel) == "config"]),
            "documentation_files": len([rel for rel in tracked_files_list if classify_path(rel) == "docs"]),
            "ci_files": len([rel for rel in tracked_files_list if classify_path(rel) == "ci"]),
            "top_level_directories": sorted({PurePosixPath(rel).parts[0] for rel in tracked_files_list if len(PurePosixPath(rel).parts) > 1})[:30],
            "components": [
                {"component": name, "files": count}
                for name, count in sorted(Counter(component_of(rel) for rel in tracked_files_list).items(), key=lambda item: (-item[1], item[0]))[:25]
            ],
            "ecosystems": dependencies.get("ecosystems") or [],
            "entry_points": entry_points,
            "has_readme": bool((readme or {}).get("present")),
            "has_license": bool(documentation.get("license_files")),
            "has_tests": bool(testing.get("test_files")),
            "has_ci": bool((ci or {}).get("workflow_files")),
            "has_dockerfile": any(PurePosixPath(rel).name.casefold().startswith("dockerfile") for rel in tracked_files_list),
            "has_compose": any(re.match(r"(?i)(docker-)?compose.*\.ya?ml$", PurePosixPath(rel).name) for rel in tracked_files_list),
        }

        code_terms: set[str] = set()
        token_files: dict[str, list[str]] = defaultdict(list)
        for rel in tracked_files_list:
            if classify_path(rel) not in _IMPLEMENTATION_CATEGORIES:
                continue
            parts = content_tokens(rel.replace("/", " ").replace("_", " ").replace("-", " "))
            code_terms.update(parts)
            for token in parts:
                if len(token_files[token]) < 3:
                    token_files[token].append(rel)
        for item in symbols:
            if classify_path(item["file"]) not in _IMPLEMENTATION_CATEGORIES:
                continue
            for token in content_tokens(item["name"]):
                code_terms.add(token)
                if len(token_files[token]) < 3 and item["file"] not in token_files[token]:
                    token_files[token].append(item["file"])
        for scope in ("runtime", "development"):
            for name in (dependencies.get(scope) or {}):
                tokens = content_tokens(name.replace("-", " ").replace("_", " "))
                code_terms.update(tokens)
                for token in tokens:
                    if len(token_files[token]) < 3:
                        token_files[token].append((dependencies.get(scope) or {})[name].get("manifest", "manifest"))
        for route in routes:
            if classify_path(route["file"]) not in _IMPLEMENTATION_CATEGORIES:
                continue
            for token in content_tokens(route["path"]):
                code_terms.add(token)
                if len(token_files[token]) < 3 and route["file"] not in token_files[token]:
                    token_files[token].append(route["file"])
        doc_terms = set(content_tokens(readme_text))
        for rel in (documentation.get("documentation_files") or [])[:50]:
            text = _read(repo, rel, limit=200_000)
            if text:
                doc_terms.update(content_tokens(text))
        code_terms = set(sorted(code_terms)[:MAX_INDEX_TERMS])
        doc_terms = set(sorted(doc_terms)[:MAX_INDEX_TERMS])

        limitations: list[str] = []
        if not (readme or {}).get("present"):
            limitations.append("No README was present; documentation quality is not fully assessable.")
        if not source_paths:
            limitations.append("No recognised source files were found; feature, quality and task-coverage evidence is limited.")
        if len(source_paths) > MAX_SCAN_FILES:
            limitations.append(f"Source analysis sampled the first {MAX_SCAN_FILES} of {len(source_paths)} source/test files in path order.")
        if languages and len(languages) > 1:
            limitations.append(f"Repository uses {len(languages)} detected languages; task coverage may be split across languages.")
        if not testing.get("test_files"):
            limitations.append("No test files were detected.")
        if not architecture.get("patterns"):
            limitations.append("No architecture pattern was confidently inferred from paths and symbols.")
        limitations.extend(quality.get("limitations") or [])
        limitations.append("Static analysis only: repository code was not executed, dependencies were not resolved, and no runtime coverage or correctness result is claimed.")
        if hygiene is None:
            limitations.append("Hygiene collector output was unavailable for the profile.")
        coverage_ratio = 1.0 if source_paths else 0.0
        confidence = min(1.0, 0.10 + 0.20 * coverage_ratio + 0.15 * bool(features) + 0.15 * bool(documentation.get("readme_present")) + 0.15 * bool(dependencies.get("manifests")) + 0.15 * bool(testing.get("test_files")) + 0.10 * bool(architecture.get("patterns")))
        evidence_sources = ["tracked file inventory", "ARGUS scc/source classification", "manifest parsing", "symbol and route extraction", "README cross-check", "CI and documentation inventory"]
        return RepositoryProfile(
            profile_version=PROFILE_VERSION, repository=repository_name, generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            metadata={
                **{key: repository.get(key) for key in ("owner", "name", "url", "normalized_url", "kind", "default_branch", "evaluated_head", "created_at", "updated_at", "visibility", "fork", "parent", "template", "license") if repository.get(key) is not None},
                "tracked_files": len(tracked_files_list), "method": PROFILE_METHOD,
                "commits": (commits or {}).get("total"),
            },
            languages=languages, technologies=technologies, dependencies=dependencies,
            structure=structure, architecture=architecture, features=features,
            testing=testing, quality=quality, documentation=documentation,
            confidence=round(confidence, 4), confidence_level=confidence_level(confidence),
            evidence_fingerprint=digest.hexdigest() if source_texts else None,
            evidence_index={
                "code_terms": sorted(code_terms), "documentation_terms": sorted(doc_terms),
                "token_files": dict(sorted(token_files.items(), key=lambda item: item[0])),
                "symbols": symbols, "routes": routes, "cli_commands": commands,
                "source_files": source_paths[:MAX_SCAN_FILES], "scanned_files": len(source_texts),
                "truncated": len(source_paths) > MAX_SCAN_FILES,
            },
            evidence_sources=evidence_sources, limitations=list(dict.fromkeys(limitations)),
        )

    @staticmethod
    def assess_task(profile: RepositoryProfile, task: TaskDefinition) -> RepositoryProfile:
        """Attach task identity and requirement coverage using implementation evidence only."""
        updated = profile.model_copy(deep=True)
        updated.task_id = task.id
        updated.task_category = task.category or None
        index = updated.evidence_index or {}
        code_terms = set(index.get("code_terms") or [])
        doc_terms = set(index.get("documentation_terms") or [])
        token_files = index.get("token_files") or {}
        assessments = [_assess_requirement(task.id, requirement, code_terms, doc_terms, token_files) for requirement in task.requirements]
        updated.task_coverage = assessments
        assessed = [item.score for item in assessments if item.status != RequirementStatus.UNVERIFIED]
        updated.task_coverage_score = round(sum(assessed) / len(assessed), 6) if assessed else None
        if not task.requirements:
            updated.limitations = list(dict.fromkeys([*updated.limitations, "The task defines no explicit requirements; requirement fulfilment and functional completeness cannot be scored."]))
        if any(item.status == RequirementStatus.UNVERIFIED for item in assessments):
            updated.limitations = list(dict.fromkeys([*updated.limitations, "At least one requirement could not be verified from implementation evidence; documentation-only mentions are not treated as coverage."]))
        return updated


def _assess_requirement(
    task_id: str, requirement: str, code_terms: set[str], doc_terms: set[str], token_files: dict[str, list[str]],
) -> RequirementAssessment:
    requirement = re.sub(r"\s+", " ", requirement).strip()
    terms = list(dict.fromkeys(content_tokens(requirement)))
    if not terms:
        return RequirementAssessment(
            requirement_id=f"{task_id}-REQ-{hashlib.sha256(requirement.encode('utf-8')).hexdigest()[:6]}",
            requirement=requirement, status=RequirementStatus.UNVERIFIED, score=0.0, confidence=0.2,
            explanation="The requirement has no content terms that can be matched to implementation evidence.",
            limitations=["Requirement text is too generic to assess deterministically."],
        )
    weights = {term: min(1.8, 1.0 + max(0, len(term) - 4) * 0.12) for term in terms}
    ordered_code_terms = sorted(code_terms)
    ordered_doc_terms = sorted(doc_terms)
    matched: list[str] = []
    doc_matched: list[str] = []
    evidence: list[str] = []
    for term in terms:
        code_hit = next((candidate for candidate in ordered_code_terms if tokens_match(term, candidate)), None)
        if code_hit:
            matched.append(term)
            for path in token_files.get(code_hit, [])[:3]:
                if path not in evidence:
                    evidence.append(path)
            continue
        doc_hit = next((candidate for candidate in ordered_doc_terms if tokens_match(term, candidate)), None)
        if doc_hit:
            doc_matched.append(term)
    total = sum(weights.values())
    coverage = sum(weights[term] for term in matched) / total if total else 0.0
    doc_coverage = sum(weights[term] for term in doc_matched) / total if total else 0.0
    has_implementation = bool(code_terms)
    if not has_implementation:
        status, score, confidence = RequirementStatus.UNVERIFIED, 0.0, 0.2
        explanation = "No implementation vocabulary was available in the profile, so the requirement cannot be verified."
        limitations = ["Repository contains no recognised source evidence for this requirement."]
    elif coverage >= 0.70 and evidence:
        status, score, confidence = RequirementStatus.COVERED, coverage, 0.85
        explanation = f"Implementation evidence matches {len(matched)}/{len(terms)} content terms ({coverage:.0%} weighted coverage) in {len(evidence)} file(s)."
        limitations = []
    elif coverage >= 0.40 and evidence:
        status, score, confidence = RequirementStatus.PARTIAL, coverage, 0.68
        explanation = f"Partial implementation evidence matches {len(matched)}/{len(terms)} content terms ({coverage:.0%} weighted coverage)."
        limitations = ["The terminology match is partial; a human should confirm the requirement's depth and edge cases."]
    elif coverage > 0:
        status, score, confidence = RequirementStatus.MISSING, coverage, 0.55
        explanation = f"Only {coverage:.0%} weighted term coverage was found; this is insufficient to establish implementation."
        limitations = ["A weak keyword match is not evidence that the requirement is implemented."]
    elif doc_coverage > 0:
        status, score, confidence = RequirementStatus.UNVERIFIED, 0.0, 0.25
        explanation = f"Documentation mentions {len(doc_matched)}/{len(terms)} content terms, but no implementation evidence was found. Documentation alone is not coverage."
        limitations = ["Mentioned only in documentation; not counted as an implemented requirement."]
    else:
        status, score, confidence = RequirementStatus.MISSING, 0.0, 0.45
        explanation = "No implementation vocabulary matched this requirement."
        limitations = ["Absence of matching terms is evidence of a coverage gap, not proof that the feature cannot exist under different terminology."]
    return RequirementAssessment(
        requirement_id=f"{task_id}-REQ-{hashlib.sha256(requirement.encode('utf-8')).hexdigest()[:6]}",
        requirement=requirement, status=status, score=round(max(0.0, min(1.0, score)), 6),
        confidence=confidence, evidence=evidence[:10], matched_terms=matched, explanation=explanation, limitations=limitations,
    )


def build_repository_profile(
    repo: Path, *, task: Optional[TaskDefinition] = None, cfg: Any = None,
    repository: Optional[dict[str, Any]] = None, tracked: Optional[Sequence[str]] = None,
    scc: Optional[dict[str, Any]] = None, hygiene: Optional[dict[str, Any]] = None,
    readme: Optional[dict[str, Any]] = None, ci: Optional[dict[str, Any]] = None,
    commits: Optional[dict[str, Any]] = None,
) -> RepositoryProfile:
    profiler = RepositoryProfiler(cfg)
    profile = profiler.build(
        repo, repository=repository, tracked=tracked, scc=scc, hygiene=hygiene,
        readme=readme, ci=ci, commits=commits,
    )
    return RepositoryProfiler.assess_task(profile, task) if task is not None else profile
