"""Git helpers: commits, dirty state, archives of old commits.

All functions shell out to ``git`` in the repo root (read-only except
``commit_paths``, which makes a path-limited commit of paths the caller owns).
"""

from __future__ import annotations

import datetime
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

from totto_suite import config


class GitError(RuntimeError):
    pass


def _git(*args: str, repo: Path | None = None, check: bool = True) -> str:
    repo = Path(repo or config.REPO_ROOT)
    env = dict(os.environ)
    env.setdefault("GIT_PAGER", "cat")
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if check and proc.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout


def head_commit(repo: Path | None = None) -> str:
    return _git("rev-parse", "HEAD", repo=repo).strip()


def resolve(rev: str, repo: Path | None = None) -> str:
    """Returns the full sha of ``rev`` (raises GitError if unknown)."""
    return _git("rev-parse", "--verify", f"{rev}^{{commit}}", repo=repo).strip()


def commit_exists(sha: str, repo: Path | None = None) -> bool:
    """True if ``sha`` is a commit reachable from HEAD (i.e. in ``git log``)."""
    try:
        full = resolve(sha, repo=repo)
    except GitError:
        return False
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", full, "HEAD"],
        cwd=Path(repo or config.REPO_ROOT),
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def commit_time(sha: str, repo: Path | None = None) -> str:
    """Committer time of ``sha`` as ISO-8601 UTC (``...Z``)."""
    ts = int(_git("show", "-s", "--format=%ct", sha, repo=repo).strip())
    return iso_utc(datetime.datetime.fromtimestamp(ts, datetime.timezone.utc))


def commit_subject(sha: str, repo: Path | None = None) -> str:
    return _git("show", "-s", "--format=%s", sha, repo=repo).strip()


def list_commits(repo: Path | None = None) -> list[dict]:
    """All commits reachable from HEAD, newest first: sha, short, time, subject."""
    out = _git("log", "--format=%H%x00%h%x00%ct%x00%s", repo=repo)
    commits = []
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, short, ct, subject = line.split("\x00", 3)
        commits.append(
            {
                "commit": sha,
                "short": short,
                "time": iso_utc(
                    datetime.datetime.fromtimestamp(int(ct), datetime.timezone.utc)
                ),
                "subject": subject,
            }
        )
    return commits


def short(sha: str | None) -> str:
    return (sha or "")[:7]


def dirty_paths(repo: Path | None = None) -> list[str]:
    """Repo-relative paths with uncommitted changes (tracked or untracked)."""
    out = _git(
        "status", "--porcelain=v1", "-z", "--untracked-files=all", repo=repo
    )
    paths = []
    entries = out.split("\x00")
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if not entry:
            continue
        status, path = entry[:2], entry[3:]
        paths.append(path)
        if "R" in status or "C" in status:
            i += 1  # skip the rename/copy source path
    return sorted(set(paths))


def _under(path: str, prefix: str) -> bool:
    prefix = prefix.rstrip("/") + "/"
    return path == prefix.rstrip("/") or path.startswith(prefix)


def split_dirty(
    paths: list[str],
    agent_path: str = "cxas_app",
    include_suite: bool = True,
) -> dict:
    """Splits dirty paths into those that can change results and the rest.

    Relevant: anything under ``agent_path`` plus (if ``include_suite``) the
    suite inputs ``cxas_app/ totto_suite/ tests/ evals/`` excluding
    ``evals/history/`` (output). Everything else is unrelated.
    """
    relevant, unrelated = [], []
    for p in paths:
        is_rel = _under(p, agent_path)
        if not is_rel and include_suite:
            is_rel = any(_under(p, x) for x in config.RELEVANT_PREFIXES) and not any(
                _under(p, x) for x in config.IRRELEVANT_PREFIXES
            )
        (relevant if is_rel else unrelated).append(p)
    return {"relevant": sorted(relevant), "unrelated": sorted(unrelated)}


def dirty_state(
    agent_path: str = "cxas_app", include_suite: bool = True, repo: Path | None = None
) -> dict:
    """Returns {dirty, dirty_paths_relevant, dirty_paths_unrelated, suite_dirty}."""
    paths = dirty_paths(repo=repo)
    split = split_dirty(paths, agent_path=agent_path, include_suite=include_suite)
    suite_paths = [
        p for p in paths if _under(p, "totto_suite") or _under(p, "tests")
    ]
    return {
        "dirty": bool(split["relevant"]),
        "dirty_paths_relevant": split["relevant"],
        "dirty_paths_unrelated": split["unrelated"],
        "suite_dirty": bool(suite_paths),
        "suite_dirty_paths": sorted(suite_paths),
    }


def archive_subdir(commit: str, subdir: str, dest: Path, repo: Path | None = None) -> Path:
    """Extracts ``<commit>:<subdir>`` into ``dest`` (via ``git archive``).

    Returns the extracted directory (``dest/<subdir>``); it does not exist if
    the commit has no such directory.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    repo = Path(repo or config.REPO_ROOT)
    with tempfile.TemporaryFile() as tmp:
        proc = subprocess.run(
            ["git", "archive", "--format=tar", commit, "--", subdir],
            cwd=repo,
            stdout=tmp,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0:
            err = proc.stderr.decode(errors="replace")
            if "did not match any files" in err or "pathspec" in err:
                return dest / subdir
            raise GitError(f"git archive {commit} {subdir} failed: {err.strip()}")
        tmp.seek(0)
        with tarfile.open(fileobj=tmp, mode="r:") as tar:
            tar.extractall(dest, filter="data")
    return dest / subdir


def commit_paths(message: str, paths: list[str], repo: Path | None = None) -> str:
    """Path-limited commit of ``paths`` (``git add`` + ``git commit -- paths``).

    Only the given paths are committed; anything else staged by other people
    stays untouched in the index. Returns the new commit sha.
    """
    if not paths:
        raise ValueError("commit_paths needs at least one path")
    _git("add", "--", *paths, repo=repo)
    _git("commit", "-m", message, "--", *paths, repo=repo)
    return head_commit(repo=repo)


def iso_utc(dt: datetime.datetime | None = None) -> str:
    """ISO-8601 UTC with ``Z`` suffix and microseconds dropped."""
    dt = dt or datetime.datetime.now(datetime.timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
