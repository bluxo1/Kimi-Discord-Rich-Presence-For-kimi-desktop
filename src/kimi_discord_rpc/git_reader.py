"""Read the current git branch without running git.

No subprocess, no shell, no network: the branch name comes from parsing
``.git/HEAD``, which removes shell-injection as a category of bug. Anything
unexpected results in ``None`` rather than an exception -- a missing branch
should never take the presence loop down.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_HEX40 = re.compile(r"^[0-9a-fA-F]{40}$")
_HEX_ANY = re.compile(r"^[0-9a-fA-F]{7,64}$")
# Guard against a hostile/garbage HEAD file ending up in the presence text.
_SAFE_REF = re.compile(r"^[\w./+-]{1,128}$")

# Depth limit when walking up towards the repository root.
_MAX_PARENTS = 64


@dataclass(frozen=True)
class BranchInfo:
    name: str
    detached: bool
    git_dir: Path


def find_git_dir(start: Path) -> Path | None:
    """Walk up from ``start`` looking for a ``.git`` directory or file."""
    try:
        current = Path(start).expanduser().resolve()
    except (OSError, RuntimeError):
        return None
    if not current.exists():
        return None
    if current.is_file():
        current = current.parent

    for _ in range(_MAX_PARENTS):
        candidate = current / ".git"
        if candidate.is_dir():
            return candidate
        if candidate.is_file():
            resolved = _resolve_git_file(candidate)
            if resolved is not None:
                return resolved
        if current.parent == current:
            break
        current = current.parent
    return None


def _resolve_git_file(git_file: Path) -> Path | None:
    """Handle worktrees/submodules, where ``.git`` is a file pointing elsewhere."""
    try:
        text = git_file.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    target = text[len("gitdir:") :].strip()
    if not target:
        return None
    path = Path(target)
    if not path.is_absolute():
        path = (git_file.parent / path).resolve()
    return path if path.is_dir() else None


def read_branch(work_dir: str | Path | None) -> BranchInfo | None:
    """Return the checked-out branch for ``work_dir``, or ``None``.

    ``None`` covers every "no branch to show" case: no directory, not a repo,
    an unreadable or malformed HEAD. Callers just hide the field.
    """
    if not work_dir:
        return None
    git_dir = find_git_dir(Path(work_dir))
    if git_dir is None:
        return None

    head = git_dir / "HEAD"
    try:
        text = head.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not text:
        return None

    if text.startswith("ref:"):
        ref = text[len("ref:") :].strip()
        if not _SAFE_REF.match(ref):
            return None
        # Strip only the refs/heads/ prefix -- branch names legitimately
        # contain slashes (feat/auth-v2), so splitting on "/" would truncate them.
        prefix = "refs/heads/"
        name = ref[len(prefix) :] if ref.startswith(prefix) else ref
        if not name:
            return None
        return BranchInfo(name=name, detached=False, git_dir=git_dir)

    # Detached HEAD: HEAD holds a raw commit id.
    if _HEX40.match(text):
        return BranchInfo(name=text[:7], detached=True, git_dir=git_dir)
    first = text.split()[0] if text.split() else ""
    if _HEX_ANY.match(first):
        return BranchInfo(name=first[:7], detached=True, git_dir=git_dir)
    return None


def branch_label(info: BranchInfo | None) -> str | None:
    """Human-facing branch string, e.g. ``feat/auth-v2`` or ``detached @a1b2c3d``."""
    if info is None:
        return None
    if info.detached:
        return f"detached @{info.name}"
    return info.name
