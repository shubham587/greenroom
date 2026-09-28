"""Prompts live as files, and their version is the git hash of the file.

Two reasons. A prompt change shows up as a readable diff rather than a blob
inside a Python string, and `prompt_version` costs nothing: phase 8 has to
attribute every score to the prompt that produced it, and git already
computes exactly that identity for free. No registry, no version table.
"""

from __future__ import annotations

import hashlib
import subprocess
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).parent / "prompts"


@lru_cache(maxsize=32)
def load(name: str) -> str:
    return (DIR / f"{name}.md").read_text().strip()


@lru_cache(maxsize=32)
def version(name: str) -> str:
    """The git blob hash of the prompt file - what git itself would call it.

    Computed from the file on disk, not from HEAD, so an uncommitted edit
    produces a different version rather than silently reusing the old one.
    """
    path = DIR / f"{name}.md"
    try:
        out = subprocess.run(
            ["git", "hash-object", str(path)],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return out.stdout.strip()[:12]
    except Exception:
        # git missing or not a repo: same identity rule, computed by hand
        body = path.read_bytes()
        header = f"blob {len(body)}\0".encode()
        return hashlib.sha1(header + body).hexdigest()[:12]  # noqa: S324 - git's own scheme
