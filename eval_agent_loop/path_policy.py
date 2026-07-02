from __future__ import annotations

from pathlib import Path

from .errors import AgentLoopError


def resolve_write_path(path: str | Path, *, workspace: Path, field: str = "path") -> Path:
    root = workspace.resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    if not _is_relative_to(resolved, root):
        raise AgentLoopError(f"{field} must be inside workspace write root: {root}; got {resolved}")
    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
