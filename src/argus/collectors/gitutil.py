"""Safe, read-only git access. The target repository is untrusted input."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

GITHUB_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/(?P<name>[A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$"
)


class RepositoryAccessError(Exception):
    """The repository (or its history) could not be obtained. Not an evaluator bug."""


class GitError(Exception):
    pass


@dataclass
class RepoSource:
    raw: str
    kind: str  # "github" | "local"
    owner: Optional[str] = None
    name: Optional[str] = None
    url: Optional[str] = None
    path: Optional[Path] = None

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}" if self.kind == "github" else (self.name or "local")


def parse_source(raw: str) -> RepoSource:
    """Accept only https GitHub repository URLs or an existing local git directory."""
    raw = raw.strip()
    match = GITHUB_URL_RE.match(raw)
    if match:
        owner, name = match["owner"], match["name"]
        if name in {".", ".."}:
            raise ValueError(f"not a valid GitHub repository URL: {raw!r}")
        return RepoSource(raw, "github", owner, name, f"https://github.com/{owner}/{name}")
    if "://" in raw or raw.startswith(("git@", "-")):
        raise ValueError(
            f"unsupported repository reference: {raw!r} (expected https://github.com/<owner>/<repo> or a local path)"
        )
    path = Path(raw).expanduser()
    if path.is_dir():
        path = path.resolve()
        return RepoSource(raw, "local", None, path.name, None, path)
    raise ValueError(f"not a GitHub repository URL or an existing local directory: {raw!r}")


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        GIT_TERMINAL_PROMPT="0",
        GIT_LFS_SKIP_SMUDGE="1",
        GIT_ASKPASS="echo",
        GIT_OPTIONAL_LOCKS="0",
        LC_ALL="C",
    )
    return env


_SAFE = [
    "-c", "core.quotepath=false",
    "-c", "core.hooksPath=" + os.devnull,
    "-c", "core.fsmonitor=false",
    "-c", "core.symlinks=false",
    "-c", "core.longpaths=true",
    "-c", "protocol.ext.allow=never",
    "-c", "credential.helper=",
]


def git(repo: Path, *args: str, check: bool = True, timeout: float = 600) -> str:
    cmd = ["git", *_SAFE, "-C", str(repo), *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, env=_env(), timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {args[0]} timed out after {timeout}s") from exc
    out = proc.stdout.decode("utf-8", errors="replace")
    if check and proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(f"git {' '.join(args[:3])} failed ({proc.returncode}): {err[:500]}")
    return out


def clone(source: RepoSource, dest: Path, timeout: float = 1800) -> Path:
    """Full-history clone into an evaluator-owned directory. No submodules, no LFS smudge, no hooks."""
    origin = source.url if source.kind == "github" else str(source.path)
    cmd = ["git", *_SAFE, "clone", "--quiet", "--no-recurse-submodules"]
    if source.kind == "local":
        cmd.append("--no-local")
    cmd += ["--", origin, str(dest)]
    try:
        proc = subprocess.run(cmd, capture_output=True, env=_env(), timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise RepositoryAccessError(f"clone timed out after {timeout}s") from exc
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RepositoryAccessError(f"clone failed: {err[:500]}")
    if not git(dest, "rev-parse", "--verify", "--quiet", "HEAD", check=False).strip():
        raise RepositoryAccessError("repository has no commits: Git history is unavailable")
    return dest


def default_branch(repo: Path) -> str:
    ref = git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", check=False).strip()
    if ref.startswith("origin/"):
        return ref[len("origin/"):]
    return git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()


def tracked_files(repo: Path) -> list[str]:
    out = git(repo, "ls-files", "-z")
    return [p for p in out.split("\0") if p]


def read_text(repo: Path, rel: str, limit: int = 1_000_000) -> Optional[str]:
    """Read a tracked file from the working tree without following anything outside the clone."""
    path = repo / rel
    try:
        resolved = path.resolve()
        if not resolved.is_relative_to(repo.resolve()) or not resolved.is_file() or path.is_symlink():
            return None
        if resolved.stat().st_size > limit:
            return None
        data = resolved.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8000]:
        return None
    return data.decode("utf-8", errors="replace")
