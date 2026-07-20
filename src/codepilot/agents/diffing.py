"""Diff preview and gated application of edits.

Propose-and-stop's core: render an edit proposal as a unified diff the
user can read, then, only if approved, write the changes into the
sandbox. The diff is written to working/proposed_diff.txt (per the
assignment) as well as returned for display.

Every path is re-checked against the guardrails at apply time, not just
at propose time, so nothing slips through if the proposal is replayed.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from codepilot.agents.coder import EditProposal
from codepilot.agents.guardrails import assert_path_allowed

WORKING_DIRNAME = "working"
DIFF_FILENAME = "proposed_diff.txt"


@dataclass
class DiffResult:
    text: str
    files_changed: int
    diff_path: Path


def _file_diff(rel_path: str, old: str, new: str) -> list[str]:
    return list(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
        )
    )


def build_diff(proposal: EditProposal, sandbox_root: Path) -> DiffResult:
    """Compute a unified diff for all allowed edits and persist it."""
    chunks: list[str] = []
    changed = 0
    for edit in proposal.edits:
        abs_path = sandbox_root / edit.path
        old = abs_path.read_text(encoding="utf-8", errors="ignore") if abs_path.exists() else ""
        if old == edit.new_content:
            continue  # no-op edit
        chunks.extend(_file_diff(edit.path, old, edit.new_content))
        changed += 1

    text = "".join(chunks) if chunks else "(no changes proposed)"

    working = sandbox_root / WORKING_DIRNAME
    working.mkdir(parents=True, exist_ok=True)
    diff_path = working / DIFF_FILENAME
    diff_path.write_text(text, encoding="utf-8")

    return DiffResult(text=text, files_changed=changed, diff_path=diff_path)


def apply_edits(proposal: EditProposal, sandbox_root: Path) -> list[str]:
    """Write approved edits into the sandbox. Returns the paths written.

    Re-validates every path. This is the ONLY function that mutates repo
    files, which keeps the write surface tiny and auditable.
    """
    written: list[str] = []
    for edit in proposal.edits:
        assert_path_allowed(edit.path)  # defense in depth
        abs_path = sandbox_root / edit.path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(edit.new_content, encoding="utf-8")
        written.append(edit.path)
    return written