"""README technical-claim extraction and deterministic cross-check against repository evidence."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from argus.collectors.classify import classify_path
from argus.collectors.gitutil import read_text
from argus.evidence import EvidenceStore

# name: (README pattern, manifest/infra-text pattern, tracked-path pattern, source-code pattern)
_T = {
    "PostgreSQL": (r"postgres(?:ql)?", r"postgres|psycopg|asyncpg|\bpg\b|pgx|npgsql", None, r"postgres(?:ql)?://|psycopg|asyncpg|from ['\"]pg['\"]|provider\s*=\s*\"postgresql\""),
    "MySQL": (r"mysql|mariadb", r"mysql|mariadb|pymysql", None, r"mysql://|pymysql|mysql2|provider\s*=\s*\"mysql\""),
    "MongoDB": (r"mongo(?:db)?", r"mongo|mongoose|pymongo|motor", None, r"mongodb(\+srv)?://|mongoose|pymongo|MongoClient"),
    "SQLite": (r"sqlite", r"sqlite|better-sqlite3", r"\.sqlite3?$|\.db$", r"sqlite3?|provider\s*=\s*\"sqlite\""),
    "Redis": (r"redis", r"redis|ioredis", None, r"redis://|import redis|from redis|ioredis|createClient"),
    "FastAPI": (r"fastapi", r"fastapi", None, r"from fastapi|import fastapi|FastAPI\("),
    "Flask": (r"flask", r"\bflask\b", None, r"from flask|import flask|Flask\("),
    "Django": (r"django", r"django", r"(^|/)manage\.py$", r"from django|import django"),
    "Express": (r"express(?:\.js)?", r"\"express\"", None, r"require\(['\"]express['\"]\)|from ['\"]express['\"]"),
    "Next.js": (r"next\.?js", r"\"next\"", r"(^|/)next\.config\.", r"from ['\"]next[/'\"]"),
    "React": (r"react(?:\.js)?", r"\"react\"", None, r"from ['\"]react['\"]"),
    "Vue": (r"vue(?:\.js)?", r"\"vue\"", r"\.vue$", r"from ['\"]vue['\"]"),
    "Angular": (r"angular", r"@angular/core", r"(^|/)angular\.json$", r"@angular/"),
    "Svelte": (r"svelte(?:kit)?", r"\"svelte\"", r"\.svelte$", None),
    "Tailwind CSS": (r"tailwind(?:\s?css)?", r"tailwindcss", r"(^|/)tailwind\.config\.", r"@tailwind|@import ['\"]tailwindcss"),
    "TypeScript": (r"typescript", r"\"typescript\"", r"\.tsx?$", None),
    "Prisma": (r"prisma", r"prisma", r"\.prisma$", r"@prisma/client|PrismaClient"),
    "GraphQL": (r"graphql", r"graphql|apollo", r"\.graphql$", r"gql`|graphql"),
    "Docker": (r"docker(?!\s*-?compose)", None, r"(^|/)Dockerfile[^/]*$", None),
    "Docker Compose": (r"docker[\s-]?compose", None, r"(^|/)(docker-)?compose[^/]*\.ya?ml$", None),
    "Kubernetes": (r"kubernetes|k8s|helm", None, r"(^|/)(k8s|kubernetes|helm|charts)/", r"apiVersion:\s*(apps/)?v1"),
    "Terraform": (r"terraform", None, r"\.tf$", None),
    "GitHub Actions / CI": (r"github actions|ci/cd|\bci\b|continuous integration", None, r"^\.github/workflows/[^/]+\.ya?ml$", None),
    "Automated tests": (r"unit tests?|automated tests?|test suite|pytest|jest|vitest|test coverage", None, r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]*\.py$|\.(test|spec)\.[cm]?[jt]sx?$|_test\.go$", None),
    "PyTorch": (r"pytorch|\btorch\b", r"\btorch\b", None, r"import torch|from torch"),
    "TensorFlow": (r"tensorflow|keras", r"tensorflow|keras", None, r"import tensorflow|from tensorflow|from keras|import keras"),
    "scikit-learn": (r"scikit[- ]learn|sklearn", r"scikit-learn|sklearn", None, r"from sklearn|import sklearn"),
    "LangChain": (r"langchain|langgraph", r"langchain|langgraph", None, r"from langchain|from langgraph|from ['\"]@?langchain"),
    "OpenAI API": (r"openai|gpt-?[345]", r"openai", None, r"from openai|import openai|from ['\"]openai['\"]|api\.openai\.com"),
    "Anthropic / Claude API": (r"anthropic|claude", r"anthropic", None, r"import anthropic|from anthropic|@anthropic-ai/sdk|api\.anthropic\.com"),
    "Ollama": (r"ollama", r"ollama", None, r"ollama|:11434"),
    "Vector search": (r"vector (?:search|database|db|store)|embeddings?|qdrant|pinecone|chroma|faiss|pgvector|weaviate|milvus", r"qdrant|pinecone|chromadb|faiss|pgvector|weaviate|milvus|sentence-transformers", None, r"qdrant|pinecone|chromadb|faiss|pgvector|weaviate|milvus|embedding"),
    "Authentication": (r"authentication|\bauth\b|jwt|oauth|login", r"jsonwebtoken|pyjwt|python-jose|passlib|bcrypt|next-auth|passport|authlib|oauthlib|django-allauth|clerk|supabase", None, r"jwt|oauth|bcrypt|passlib|next-auth|passport|authenticate"),
    "Kafka": (r"kafka", r"kafka", None, r"kafka"),
    "RabbitMQ": (r"rabbitmq", r"rabbitmq|pika|amqp", None, r"amqp://|pika|amqplib"),
    "Celery": (r"celery", r"celery", None, r"from celery|import celery"),
    "WebSocket": (r"websockets?|socket\.io", r"websocket|socket\.io|\"ws\"", None, r"WebSocket|socket\.io|websockets"),
    "Firebase": (r"firebase", r"firebase", r"(^|/)firebase\.json$", r"firebase"),
    "Supabase": (r"supabase", r"supabase", None, r"supabase"),
    "Stripe": (r"stripe", r"stripe", None, r"stripe"),
    "AWS": (r"\baws\b|amazon web services|\bs3\b|lambda", r"boto3|aws-sdk|@aws-sdk", None, r"boto3|aws-sdk|amazonaws\.com"),
    "Spring Boot": (r"spring ?boot", r"spring-boot", None, r"@SpringBootApplication|org\.springframework"),
    ".NET": (r"\.net\b|asp\.net|c#", None, r"\.(csproj|sln)$", None),
    "Go": (r"\bgolang\b|\bgo (?:1\.\d+|backend|server|service)", None, r"(^|/)go\.mod$", None),
    "Rust": (r"\brust\b", None, r"(^|/)Cargo\.toml$", None),
}
_MANIFESTS = {
    "package.json", "requirements.txt", "pyproject.toml", "setup.py", "Pipfile", "Cargo.toml", "go.mod", "pom.xml",
    "build.gradle", "build.gradle.kts", "composer.json", "Gemfile", "environment.yml",
}
_ML_CLAIM = re.compile(
    r"(?i)(?:(\d{2,3}(?:\.\d+)?)\s?%\s*(?:test |validation |val )?(accuracy|precision|recall|f1(?:[- ]score)?|auc|map))|"
    r"(?:(accuracy|precision|recall|f1(?:[- ]score)?|auc)\s*(?:of|:|=|is)?\s*(\d{2,3}(?:\.\d+)?\s?%|0\.\d{2,4}))"
)


_HEDGE = re.compile(
    r"(?i)\b(no|not|n't|without|never|planned?|plan to|todo|to-do|future|roadmap|will|would|could|can|may|might|should|optional(ly)?|"
    r"alternativ\w*|instead of|rather than|soon|upcoming|wip|consider\w*|if you|you can|e\.g\.|for example|such as|learn more|deploy(ing|ment)? on)\b"
)


def find_readme(tracked: list[str]) -> Optional[str]:
    candidates = [f for f in tracked if re.match(r"^readme(\.(md|rst|txt|mdx))?$", f, re.I)]
    return sorted(candidates, key=len)[0] if candidates else None


def analyze(repo: Path, tracked: list[str], store: EvidenceStore) -> dict[str, Any]:
    src = "readme"
    readme_path = find_readme(tracked)
    if not readme_path:
        return {"present": False, "claims": [], "ml_claims": [], "evidence": {}}
    text = read_text(repo, readme_path, limit=2_000_000) or ""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]

    manifest_text = ""
    for f in tracked:
        name = PurePosixPath(f).name
        if classify_path(f) != "vendored" and (name in _MANIFESTS or name.startswith(("Dockerfile", "docker-compose", "compose.")) or name.endswith((".csproj",))):
            manifest_text += "\n" + (read_text(repo, f, limit=500_000) or "")
    code_text_parts = []
    budget = 15_000_000
    for f in tracked:
        if classify_path(f) in {"source", "tests", "config", "ci"} and PurePosixPath(f).name not in _MANIFESTS:
            content = read_text(repo, f, limit=300_000)
            if content:
                code_text_parts.append(content)
                budget -= len(content)
                if budget <= 0:
                    break
    code_text = "\n".join(code_text_parts)

    claims = []
    claim_ev = []
    for tech, (readme_re, manifest_re, path_re, code_re) in _T.items():
        pattern = re.compile(rf"(?i)(?<![A-Za-z0-9])(?:{readme_re})(?![A-Za-z0-9])")
        mentions = [s[:240] for s in sentences if pattern.search(s)]
        if not mentions:
            continue
        declared = bool(manifest_re and re.search(manifest_re, manifest_text, re.I))
        paths = [f for f in tracked if path_re and re.search(path_re, f)][:4]
        used = bool(code_re and re.search(code_re, code_text, re.I))
        supports = []
        if declared:
            supports.append("declared in a dependency manifest or container definition")
        if paths:
            supports.append("matching files tracked: " + ", ".join(paths))
        if used:
            supports.append("usage pattern found in source/config")
        strong = declared or bool(paths)
        if strong and (used or not code_re):
            status = "VERIFIED"
        elif strong or used:
            status = "PARTIALLY_VERIFIED"
        else:
            status = "NOT_VERIFIED"
            # For technologies whose presence is fully determined by tracked files (a Dockerfile, a workflow,
            # test files, ...), an assertive mention with no such file is evidence AGAINST the claim.
            # Hedged, negated or planned mentions stay NOT_VERIFIED.
            file_determined = bool(path_re) and not manifest_re and not code_re
            assertive = [s for s in mentions if not _HEDGE.search(s)]
            if file_determined and assertive:
                status = "CONTRADICTED"
                supports.append("no matching file is tracked, and the README states it without qualification")
        claim = {"technology": tech, "readme_mentions": mentions[:3], "supporting_evidence": supports, "status": status}
        claim["evidence_id"] = store.add("readme_claim", src, f"README mentions {tech}: {status}", claim)
        claim_ev.append(claim["evidence_id"])
        claims.append(claim)

    ml_claims = []
    for m in _ML_CLAIM.finditer(text):
        ml_claims.append({"claim": text[max(0, m.start() - 60): m.end() + 40].replace("\n", " ").strip()[:200]})
    readme_ev = store.add(
        "readme", src, f"{readme_path}: {len(text)} chars, {len(claims)} technology claim(s) detected",
        {"path": readme_path, "chars": len(text), "lines": text.count("\n") + 1, "headings": re.findall(r"(?m)^#{1,3}\s+(.+)$", text)[:30], "excerpt": text[:5000]},
    )
    return {
        "present": True,
        "path": readme_path,
        "chars": len(text),
        "is_minimal": len(text.strip()) < 200,
        "claims": claims,
        "claim_status_counts": {s: sum(1 for c in claims if c["status"] == s) for s in ("VERIFIED", "PARTIALLY_VERIFIED", "NOT_VERIFIED", "CONTRADICTED")},
        "ml_claims": ml_claims[:10],
        "method": "Keyword-detected technology mentions cross-checked against manifests, tracked paths and source patterns. Statuses are deterministic and cannot be overridden by the model. CONTRADICTED is assigned only when presence is fully determined by tracked files, none exist, and the README states the technology without qualification.",
        "evidence": {"readme": readme_ev, "claims": claim_ev},
    }
