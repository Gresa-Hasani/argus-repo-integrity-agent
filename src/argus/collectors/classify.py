"""Path classification: separates original source from tests, config, docs, generated and vendored content.

These are path heuristics. Anything derived from them is an estimate and is labelled as such in reports.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

VENDORED_DIRS = {"node_modules", "vendor", "third_party", "third-party", "bower_components", "site-packages", ".venv", "venv", "Pods"}
BUILD_DIRS = {"dist", "build", ".next", "target", "coverage", "__pycache__", ".nuxt", ".output", ".turbo", "obj", ".gradle", ".pytest_cache"}
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "e2e"}
DOC_DIRS = {"docs", "doc", "documentation"}
DATA_DIRS = {"data", "dataset", "datasets"}

LOCKFILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock", "poetry.lock", "Pipfile.lock",
    "uv.lock", "Cargo.lock", "composer.lock", "Gemfile.lock", "go.sum", "packages.lock.json", "pubspec.lock",
}

SOURCE_EXT = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JSX", ".ts": "TypeScript", ".tsx": "TSX", ".mjs": "JavaScript",
    ".cjs": "JavaScript", ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".go": "Go", ".rs": "Rust",
    ".c": "C", ".h": "C Header", ".cpp": "C++", ".cc": "C++", ".hpp": "C++ Header", ".cs": "C#", ".rb": "Ruby",
    ".php": "PHP", ".swift": "Swift", ".scala": "Scala", ".dart": "Dart", ".sh": "Shell", ".bash": "Shell",
    ".ps1": "PowerShell", ".sql": "SQL", ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".scss": "Sass",
    ".sass": "Sass", ".less": "LESS", ".vue": "Vue", ".svelte": "Svelte", ".r": "R", ".m": "Objective C",
    ".lua": "Lua", ".pl": "Perl", ".ex": "Elixir", ".exs": "Elixir", ".prisma": "Prisma", ".graphql": "GraphQL",
    ".proto": "Protocol Buffers", ".tf": "Terraform", ".ipynb": "Jupyter",
}
DOC_EXT = {".md": "Markdown", ".mdx": "Markdown", ".rst": "ReStructuredText", ".txt": "Plain Text", ".adoc": "AsciiDoc"}
CONFIG_EXT = {".json": "JSON", ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML", ".ini": "INI", ".cfg": "INI", ".xml": "XML", ".properties": "Properties", ".conf": "Config"}
BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp", ".svg", ".pdf", ".zip", ".tar", ".gz", ".7z", ".rar",
    ".woff", ".woff2", ".ttf", ".eot", ".otf", ".mp3", ".mp4", ".mov", ".avi", ".wav", ".exe", ".dll", ".so",
    ".dylib", ".class", ".jar", ".war", ".pyc", ".o", ".a", ".bin", ".db", ".sqlite", ".sqlite3", ".docx", ".xlsx", ".pptx",
}
MODEL_EXT = {".pt", ".pth", ".h5", ".hdf5", ".onnx", ".pkl", ".pickle", ".joblib", ".safetensors", ".ckpt", ".gguf", ".tflite", ".pb"}
DATA_EXT = {".csv", ".tsv", ".parquet", ".jsonl", ".ndjson", ".npy", ".npz", ".feather", ".arrow"}

_GENERATED_NAME = re.compile(
    r"(\.pb\.go|_pb2(_grpc)?\.py|\.g\.dart|\.generated\.[a-z]+|\.designer\.cs|\.g\.cs|-generated\.[a-z]+)$", re.I
)
_TEST_NAME = re.compile(r"(^test_.*\.py$|_test\.(py|go)$|\.(test|spec)\.[cm]?[jt]sx?$|Tests?\.(java|cs|kt)$)")
_CONFIG_NAME = re.compile(
    r"^(Dockerfile.*|docker-compose.*|Makefile|Procfile|Jenkinsfile|\..+rc(\..+)?|\.editorconfig|\.gitignore|"
    r"\.gitattributes|\.dockerignore|\.env.*|.*\.config\.[cm]?[jt]s|tsconfig.*\.json|requirements.*\.txt|"
    r"Pipfile|Gemfile|go\.mod|pom\.xml|build\.gradle(\.kts)?|settings\.gradle(\.kts)?|CMakeLists\.txt)$"
)

# Categories counted as engineering work when estimating "meaningful" LOC.
MEANINGFUL = {"source", "tests"}
# Categories that must never be presented as equivalent to original contribution.
NON_ORIGINAL = {"vendored", "build_output", "generated", "minified", "lockfile", "binary", "model_artifact", "dataset"}

ALL_CATEGORIES = [
    "source", "tests", "config", "ci", "docs", "generated", "vendored", "build_output", "minified", "lockfile",
    "dataset", "model_artifact", "binary", "other",
]


def classify_path(path: str) -> str:
    p = PurePosixPath(path.replace("\\", "/"))
    parts = p.parts
    dirs = parts[:-1]
    name = p.name
    ext = p.suffix.lower()
    dirset = set(dirs)

    if dirset & VENDORED_DIRS:
        return "vendored"
    if dirset & BUILD_DIRS or re.search(r"(^|/)bin/(Debug|Release)/", path):
        return "build_output"
    if name.endswith((".min.js", ".min.css", ".map", ".bundle.js")):
        return "minified"
    if name in LOCKFILES:
        return "lockfile"
    if "generated" in {d.lower() for d in dirs} or _GENERATED_NAME.search(name):
        return "generated"
    if "migrations" in dirset and ext in {".sql", ".py", ".cs", ".ts", ".js"}:
        return "generated"
    if ext in MODEL_EXT:
        return "model_artifact"
    if ext in DATA_EXT or (dirset & DATA_DIRS and ext in {".json", ".xml", ".txt"}):
        return "dataset"
    if ext in BINARY_EXT:
        return "binary"
    if (len(parts) >= 2 and parts[0] == ".github" and parts[1] == "workflows") or name in {".gitlab-ci.yml", "Jenkinsfile", "azure-pipelines.yml"} or ".circleci" in dirset:
        return "ci"
    if ext in SOURCE_EXT and (dirset & TEST_DIRS or _TEST_NAME.search(name)):
        return "tests"
    if _CONFIG_NAME.match(name):
        return "config"
    if ext in DOC_EXT or dirset & DOC_DIRS or name.upper().startswith(("LICENSE", "COPYING", "NOTICE")):
        return "docs"
    if ext in SOURCE_EXT:
        return "source"
    if ext in CONFIG_EXT or name.startswith("."):
        return "config"
    return "other"


def language_of(path: str) -> str:
    p = PurePosixPath(path.replace("\\", "/"))
    ext = p.suffix.lower()
    if p.name.startswith("Dockerfile"):
        return "Dockerfile"
    if p.name == "Makefile":
        return "Makefile"
    return SOURCE_EXT.get(ext) or DOC_EXT.get(ext) or CONFIG_EXT.get(ext) or "Other"


def component_of(path: str) -> str:
    parts = PurePosixPath(path.replace("\\", "/")).parts
    if len(parts) == 1:
        return "(root)"
    if parts[0] in {"src", "app", "apps", "packages", "lib"} and len(parts) > 2:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]
