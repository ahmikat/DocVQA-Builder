"""Safe file helpers."""
from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def safe_relative(path: Path, root: Path) -> str:
    """Path relative to root (POSIX style); refuses paths that escape root."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as e:
        raise ValueError(f"{path} is outside {root}") from e


def resolve_inside(root: Path, rel: str) -> Path:
    """Resolve a stored relative path, refusing traversal outside root."""
    p = (root / rel).resolve()
    p.relative_to(root.resolve())  # raises ValueError on escape
    return p
