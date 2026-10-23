"""Task definitions, deterministic task similarity, assignment and equivalence grouping.

This module is the task-identity layer. It never inspects repository quality: it only decides
whether a repository was associated with a task and whether two task descriptions describe the
same work. The caller's explicit assignment is authoritative; semantic matching is a fallback and
is always reported as inferred with a confidence and a threshold.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations
from typing import Any, Iterable, Optional, Sequence

from argus.models import RepositoryProfile, TaskAssignment, TaskGroup

TASK_SIMILARITY_METHOD = (
    "Deterministic text similarity over normalised content tokens and character n-grams: "
    "query-term coverage, TF cosine, character 4-gram Dice and sequence ratio. "
    "No repository name, language or framework participates in task identity."
)

DEFAULT_RELEVANCE_THRESHOLD = 0.62
DEFAULT_TASK_SIMILARITY_THRESHOLD = 0.70

_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "also", "am", "an", "and", "any",
    "are", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but",
    "by", "can", "could", "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from",
    "further", "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him", "himself",
    "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me", "more", "most",
    "my", "myself", "no", "nor", "not", "now", "of", "off", "on", "once", "only", "or", "other", "our",
    "ours", "ourselves", "out", "over", "own", "same", "she", "should", "so", "some", "such", "than",
    "that", "the", "their", "theirs", "them", "themselves", "then", "there", "these", "they", "this",
    "those", "through", "to", "too", "under", "until", "up", "very", "was", "we", "were", "what", "when",
    "where", "which", "while", "who", "whom", "why", "will", "with", "would", "you", "your", "yours",
    "yourself", "yourselves", "must", "shall", "may", "might", "using", "use", "used", "include",
    "includes", "including", "provide", "provides", "support", "supports", "implement", "implements",
    "implemented", "allow", "allows", "enable", "enables", "able", "via", "per", "etc", "e.g", "eg",
}

_SHORT_TECHNICAL = {"ai", "api", "app", "cli", "db", "ci", "ml", "ui", "ux", "sql", "jwt", "orm", "sdk", "http"}

_SUFFIXES = (
    "ational", "tional", "ization", "isation", "ations", "ation", "ators", "ator", "ments", "ment",
    "ings", "ing", "iest", "ier", "ies", "ied", "ers", "er", "ed", "es", "s",
)

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_WORD = re.compile(r"[A-Za-z0-9_]+")


def normalized_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", value.lower()).strip()


def stem_token(token: str) -> str:
    """Small, deterministic suffix stemmer. It is intentionally conservative; it is not a claim of linguistics."""
    token = token.lower()
    if len(token) <= 3:
        return token
    for suffix in _SUFFIXES:
        if not token.endswith(suffix) or len(token) - len(suffix) < 4:
            continue
        base = token[: -len(suffix)]
        if suffix in {"ies", "ied"}:
            base += "y"
        elif suffix == "es" and base.endswith(("s", "x", "z", "ch", "sh")):
            # keep the plural-looking stem stable for both forms
            base = token[:-2]
        return base
    return token


def token_stream(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    tokens: list[str] = []
    for raw in _WORD.findall(text):
        for part in _CAMEL.split(raw):
            part = part.lower().strip("_")
            if not part:
                continue
            if part in _SHORT_TECHNICAL or (len(part) >= 3 and part not in _STOPWORDS):
                tokens.append(stem_token(part))
    return tokens


def content_tokens(text: str) -> list[str]:
    return token_stream(text)


def _ngrams(tokens: Sequence[str], n: int = 4) -> set[str]:
    result = set()
    for token in tokens:
        padded = f"^{token}$"
        if len(padded) <= n:
            result.add(padded)
        else:
            result.update(padded[i: i + n] for i in range(len(padded) - n + 1))
    return result


def _dice(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return 2.0 * len(left & right) / (len(left) + len(right))


def _fuzzy_token_match(left: str, right: str) -> bool:
    if left == right:
        return True
    if min(len(left), len(right)) >= 5 and (left.startswith(right) or right.startswith(left)):
        return True
    if min(len(left), len(right)) >= 7:
        return SequenceMatcher(None, left, right, autojunk=False).ratio() >= 0.90
    return False


def tokens_match(left: str, right: str) -> bool:
    """Public deterministic term matcher used by profile requirement coverage."""
    return _fuzzy_token_match(left, right)


def _term_weight(token: str) -> float:
    return min(1.8, 1.0 + max(0, len(token) - 4) * 0.12)


def query_coverage(query: str, document: str) -> float:
    """Share of the query's content terms present in the document (order independent)."""
    q = Counter(content_tokens(query))
    d = set(content_tokens(document))
    if not q or not d:
        return 0.0
    total = sum(_term_weight(t) * count for t, count in q.items())
    hit = sum(
        _term_weight(t) * count
        for t, count in q.items()
        if any(_fuzzy_token_match(t, candidate) for candidate in d)
    )
    return max(0.0, min(1.0, hit / total)) if total else 0.0


def tf_cosine(left: str, right: str) -> float:
    a, b = Counter(content_tokens(left)), Counter(content_tokens(right))
    if not a or not b:
        return 0.0

    def vector(counter: Counter) -> dict[str, float]:
        return {token: 1.0 + math.log(count) for token, count in counter.items()}

    va, vb = vector(a), vector(b)
    dot = sum(value * vb.get(token, 0.0) for token, value in va.items())
    norm_a = sum(value * value for value in va.values()) ** 0.5
    norm_b = sum(value * value for value in vb.values()) ** 0.5
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def text_similarity(left: str, right: str) -> float:
    """Symmetric deterministic similarity in [0, 1] with no hidden model or embedding."""
    if not (left or "").strip() or not (right or "").strip():
        return 0.0
    coverage = (query_coverage(left, right) + query_coverage(right, left)) / 2
    cosine = tf_cosine(left, right)
    chars = _dice(_ngrams(token_stream(left)), _ngrams(token_stream(right)))
    fuzzy = SequenceMatcher(None, normalized_text(left)[:800], normalized_text(right)[:800], autojunk=False).ratio()
    return round(max(0.0, min(1.0, 0.45 * coverage + 0.25 * cosine + 0.20 * chars + 0.10 * fuzzy)), 6)


def requirement_similarity(left: Sequence[str], right: Sequence[str]) -> float:
    if not left or not right:
        return 0.0
    forward = [max(text_similarity(item, candidate) for candidate in right) for item in left]
    backward = [max(text_similarity(item, candidate) for candidate in left) for item in right]
    return round((sum(forward) / len(forward) + sum(backward) / len(backward)) / 2, 6)


def task_similarity(left: "TaskDefinition", right: "TaskDefinition") -> dict[str, Any]:
    """Compare two task definitions, not repositories and not technology stacks."""
    components: dict[str, float] = {"description": text_similarity(left.description, right.description)}
    components["requirements"] = requirement_similarity(left.requirements, right.requirements)
    components["title"] = text_similarity(left.title or left.id.replace("_", " "), right.title or right.id.replace("_", " "))
    components["category"] = 1.0 if left.category and right.category and left.category.strip().casefold() == right.category.strip().casefold() else 0.0
    weights = {"description": 0.55, "requirements": 0.33, "title": 0.07, "category": 0.05}
    if not left.requirements or not right.requirements:
        weights.pop("requirements")
    if not (left.title or right.title):
        weights.pop("title")
    if not (left.category and right.category):
        weights.pop("category")
    total = sum(weights.values())
    score = sum(components[key] * weight for key, weight in weights.items()) / total if total else 0.0
    return {
        "score": round(max(0.0, min(1.0, score)), 6),
        "components": {key: round(value, 6) for key, value in components.items()},
        "method": TASK_SIMILARITY_METHOD,
    }


def _profile_text(profile: RepositoryProfile) -> str:
    parts: list[str] = []
    for feature in profile.features:
        parts.extend(str(feature.get(key, "")) for key in ("name", "description", "kind"))
        parts.extend(str(value) for value in feature.get("symbols", []) or [])
        parts.extend(str(value) for value in feature.get("evidence", []) or [])
    for technology in profile.technologies:
        parts.extend(str(technology.get(key, "")) for key in ("name", "category", "evidence"))
    deps = profile.dependencies or {}
    for key in ("runtime", "development"):
        for name in (deps.get(key) or {}):
            parts.append(str(name))
    structure = profile.structure or {}
    parts.extend(str(value) for value in structure.get("components", []) or [])
    parts.extend(str(value) for value in structure.get("ecosystems", []) or [])
    parts.extend(str(value) for value in structure.get("entry_points", []) or [])
    architecture = profile.architecture or {}
    parts.extend(str(value) for value in architecture.get("patterns", []) or [])
    parts.extend(str(value) for value in architecture.get("entry_points", []) or [])
    documentation = profile.documentation or {}
    parts.extend(str(value) for value in documentation.get("headings", []) or [])
    parts.append(str(documentation.get("summary", "")))
    for language in profile.languages:
        parts.append(str(language.get("language", "")))
    return "\n".join(part for part in parts if part)


def task_affinity(profile: RepositoryProfile, task: "TaskDefinition") -> dict[str, Any]:
    """How well the repository's observed content supports this task identity.

    This is classification evidence, not requirement fulfilment. A README-only match can raise
    affinity but never counts as implemented coverage.
    """
    corpus = _profile_text(profile)
    components = {
        "description": text_similarity(task.description, corpus),
        "requirements": (
            sum(query_coverage(item, corpus) for item in task.requirements) / len(task.requirements)
            if task.requirements else 0.0
        ),
        "title": text_similarity(task.title or task.id.replace("_", " "), corpus),
    }
    weights = {"description": 0.55, "requirements": 0.35, "title": 0.10}
    if not task.requirements:
        weights.pop("requirements")
    if not task.title:
        weights.pop("title")
    total = sum(weights.values())
    score = sum(components[key] * weight for key, weight in weights.items()) / total if total else 0.0
    return {
        "score": round(max(0.0, min(1.0, score)), 6),
        "components": {key: round(value, 6) for key, value in components.items()},
        "method": "Task description and requirements compared with profile features, paths, symbols, dependencies and documentation headings.",
    }


@dataclass(frozen=True)
class TaskDefinition:
    id: str
    description: str
    title: str = ""
    category: str = ""
    requirements: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    source: str = "configured"

    def __post_init__(self) -> None:
        task_id = (self.id or "").strip()
        description = re.sub(r"\s+", " ", (self.description or "").strip())
        if not description:
            raise ValueError("a task requires a non-empty description")
        if not task_id:
            digest = hashlib.sha256((description + "|" + "|".join(self.requirements)).encode("utf-8")).hexdigest()[:10]
            task_id = f"task-{digest}"
        cleaned = tuple(dict.fromkeys(re.sub(r"\s+", " ", item).strip() for item in self.requirements if item and item.strip()))
        object.__setattr__(self, "id", task_id)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "title", re.sub(r"\s+", " ", (self.title or "").strip()))
        object.__setattr__(self, "category", re.sub(r"\s+", " ", (self.category or "").strip()))
        object.__setattr__(self, "requirements", cleaned)
        object.__setattr__(self, "aliases", tuple(dict.fromkeys(item.strip() for item in self.aliases if item and item.strip())))

    @classmethod
    def from_mapping(cls, value: Any, *, source: str = "configured") -> "TaskDefinition":
        if isinstance(value, cls):
            return value
        if not isinstance(value, dict):
            raise ValueError("a task definition must be an object with id, description and optional requirements")

        def strings(raw: Any) -> tuple[str, ...]:
            if isinstance(raw, str):
                return (raw.strip(),) if raw.strip() else ()
            return tuple(str(item) for item in (raw or []))

        return cls(
            id=str(value.get("id") or value.get("task_id") or ""),
            description=str(value.get("description") or value.get("task") or ""),
            title=str(value.get("title") or ""),
            category=str(value.get("category") or ""),
            requirements=strings(value.get("requirements")),
            aliases=strings(value.get("aliases")),
            source=str(value.get("source") or source),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "category": self.category,
            "description": self.description, "requirements": list(self.requirements),
            "aliases": list(self.aliases), "source": self.source,
        }


def _assignment_key(value: str) -> str:
    value = (value or "").strip().rstrip("/")
    match = re.match(r"(?i)^https?://github\.com/([^/]+)/([^/#?]+?)(?:\.git)?$", value)
    if match:
        return f"{match.group(1)}/{match.group(2)}".casefold()
    if "://" in value:
        return value.casefold()
    return value.casefold()


class TaskCatalog:
    """A validated set of task definitions plus optional per-repository explicit assignments."""

    def __init__(self, tasks: Iterable[TaskDefinition], assignments: Optional[dict[str, str]] = None) -> None:
        self.tasks = list(tasks)
        by_id: dict[str, TaskDefinition] = {}
        for task in self.tasks:
            if task.id in by_id:
                raise ValueError(f"duplicate task id: {task.id}")
            by_id[task.id] = task
        self.by_id = by_id
        self.assignments: dict[str, str] = {}
        self.short_assignments: dict[str, str] = {}
        for key, task_id in (assignments or {}).items():
            task_id = str(task_id).strip()
            if task_id not in by_id:
                raise ValueError(f"task assignment for {key!r} references unknown task {task_id!r}")
            normalized = _assignment_key(str(key))
            self.assignments[normalized] = task_id
            if "/" not in normalized:
                self.short_assignments[normalized] = task_id

    @classmethod
    def from_config(cls, cfg: Any) -> "TaskCatalog":
        raw_definitions = list(getattr(cfg, "task_definitions", None) or [])
        tasks: list[TaskDefinition] = []
        if raw_definitions:
            tasks = [TaskDefinition.from_mapping(item) for item in raw_definitions]
        elif getattr(cfg, "task_description", ""):
            tasks = [TaskDefinition(
                id=str(getattr(cfg, "task_id", "") or ""),
                description=str(cfg.task_description),
                title=str(getattr(cfg, "task_title", "") or ""),
                category=str(getattr(cfg, "task_category", "") or ""),
                requirements=tuple(getattr(cfg, "task_requirements", None) or ()),
            )]
        return cls(tasks, dict(getattr(cfg, "task_assignments", None) or {}))

    @property
    def configured(self) -> bool:
        return bool(self.tasks)

    def task_for(self, repository: str, url: Optional[str] = None) -> Optional[TaskDefinition]:
        for candidate in (url, repository):
            if not candidate:
                continue
            key = _assignment_key(candidate)
            if key in self.assignments:
                return self.by_id[self.assignments[key]]
            short = key.rsplit("/", 1)[-1]
            if short and short in self.short_assignments:
                return self.by_id[self.short_assignments[short]]
        if len(self.tasks) == 1:
            return self.tasks[0]
        return None

    def assignment_for(self, repository: str, url: Optional[str] = None) -> Optional[tuple[TaskDefinition, bool]]:
        for candidate in (url, repository):
            if not candidate:
                continue
            key = _assignment_key(candidate)
            if key in self.assignments:
                return self.by_id[self.assignments[key]], True
            short = key.rsplit("/", 1)[-1]
            if short and short in self.short_assignments:
                return self.by_id[self.short_assignments[short]], True
        if len(self.tasks) == 1:
            return self.tasks[0], False
        return None

    def to_payload(self) -> dict[str, Any]:
        return {"definitions": [task.to_dict() for task in self.tasks], "assignments": dict(self.assignments)}


def catalog_from_mapping(payload: Optional[dict[str, Any]]) -> TaskCatalog:
    payload = payload or {}
    definitions = [TaskDefinition.from_mapping(item) for item in (payload.get("definitions") or payload.get("tasks") or [])]
    return TaskCatalog(definitions, dict(payload.get("assignments") or {}))


def validate_task_payload(payload: Optional[dict[str, Any]]) -> TaskCatalog:
    """Build and validate a task payload; raises ValueError with a user-facing message."""
    try:
        return catalog_from_mapping(payload)
    except ValueError:
        raise
    except Exception as exc:  # malformed nested data
        raise ValueError(f"invalid task configuration: {type(exc).__name__}: {exc}") from exc


def assign_task(profile: RepositoryProfile, catalog: TaskCatalog, threshold: float = DEFAULT_RELEVANCE_THRESHOLD) -> Optional[TaskAssignment]:
    """Assign a profile to the caller's task or infer it from observed repository content."""
    if not catalog.configured:
        return None
    explicit = catalog.assignment_for(profile.repository, profile.metadata.get("url"))
    if explicit is not None:
        task, was_explicit = explicit
        affinity = task_affinity(profile, task)
        return TaskAssignment(
            task_id=task.id, title=task.title, category=task.category, description=task.description,
            requirements=list(task.requirements), relation="EXPLICIT", relevance=1.0, confidence=1.0,
            method="caller-assigned task" if was_explicit else "single configured task applied to every repository",
            explanation=(
                f"The task was supplied by the caller. Observed-content corroboration is {affinity['score']:.0%}; "
                "it is recorded as context, not used to override the assignment."
            ),
            corroboration=affinity["score"],
            limitations=[] if affinity["score"] >= 0.35 else [
                "The caller supplied this task, but the repository profile contains little wording or structure from the task description. "
                "The assignment stands; task coverage is assessed independently from implementation evidence."
            ],
        )

    ranked = sorted(((task_affinity(profile, task), task) for task in catalog.tasks), key=lambda item: (-item[0]["score"], item[1].id))
    if not ranked:
        return None
    affinity, task = ranked[0]
    score = affinity["score"]
    if score >= threshold:
        relation = "SEMANTIC"
        confidence = min(0.95, 0.45 + 0.55 * (score - threshold) / max(1e-9, 1 - threshold))
        limitations = ["Task identity was inferred from repository content, not supplied by the caller."]
    elif score >= threshold * 0.78:
        relation = "UNCERTAIN"
        confidence = max(0.15, score * 0.7)
        limitations = ["Task relevance is below the configured confidence threshold; the repository is excluded from peer scoring."]
    else:
        relation = "UNRELATED"
        confidence = max(0.05, score * 0.5)
        limitations = ["No configured task is sufficiently supported by the repository profile; comparative scoring is not performed."]
    return TaskAssignment(
        task_id=task.id, title=task.title, category=task.category, description=task.description,
        requirements=list(task.requirements), relation=relation, relevance=round(score, 6), confidence=round(confidence, 6),
        method="inferred by deterministic task-content similarity",
        explanation=(
            f"Best match is task '{task.id}' at {score:.0%} affinity "
            f"(description {affinity['components'].get('description', 0):.0%}, "
            f"requirements {affinity['components'].get('requirements', 0):.0%}, "
            f"title {affinity['components'].get('title', 0):.0%}); threshold is {threshold:.0%}."
        ),
        limitations=limitations,
    )


def group_tasks(tasks: Sequence[TaskDefinition], threshold: float = DEFAULT_TASK_SIMILARITY_THRESHOLD) -> list[TaskGroup]:
    """Merge task definitions that describe the same work. Repositories are never grouped by stack."""
    tasks = list(tasks)
    parent = {task.id: task.id for task in tasks}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a

    pair_rows: list[dict[str, Any]] = []
    for left, right in combinations(sorted(tasks, key=lambda task: task.id), 2):
        comparison = task_similarity(left, right)
        row = {
            "a": left.id, "b": right.id, "similarity": comparison["score"],
            "equivalent": comparison["score"] >= threshold,
            "components": comparison["components"],
        }
        pair_rows.append(row)
        if row["equivalent"]:
            union(left.id, right.id)

    clusters: dict[str, list[TaskDefinition]] = {}
    for task in tasks:
        clusters.setdefault(find(task.id), []).append(task)
    rows = []
    for members in clusters.values():
        member_ids = sorted(task.id for task in members)
        representative = sorted(
            members,
            key=lambda task: (-len(task.requirements), -len(task.description), task.id),
        )[0]
        requirements: list[str] = []
        for task in sorted(members, key=lambda item: item.id):
            requirements.extend(task.requirements)
        rows.append(TaskGroup(
            task_id=member_ids[0], task_ids=member_ids,
            title=representative.title, category=representative.category,
            description=representative.description, requirements=list(dict.fromkeys(requirements)),
            pair_similarities=[
                row for row in pair_rows if row["a"] in member_ids and row["b"] in member_ids
            ],
        ))
    return sorted(rows, key=lambda group: group.task_id)


def task_group_for(task_id: str, groups: Sequence[TaskGroup]) -> Optional[TaskGroup]:
    for group in groups:
        if task_id in group.task_ids:
            return group
    return None
