"""Safety guardrails for the Coder agent.

Phase 4 is the first time CodePilot can write files and run commands, so
these guardrails exist before any of that capability is wired up. They
are plain, deterministic functions: given a command or a file path,
decide whether it's allowed. Keeping them out of the LLM means safety
doesn't depend on the model's cooperation, and it means every rule is
unit-testable.

Two checks:
  - is_command_allowed: blocks destructive or exfiltrating shell commands
  - is_path_allowed: blocks writes to protected files and anything outside
    the sandbox
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

# Commands that are never allowed, matched against the first token or as a
# substring for the more dangerous patterns. The assignment names rm -rf,
# curl, wget, and pip install specifically; we add a few obvious siblings.
_BLOCKED_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\brm\s+-\w*r\w*f?\b|\brm\s+-\w*f\w*r?\b"), "recursive/forced delete"),
    (re.compile(r"\bcurl\b"), "network fetch (curl)"),
    (re.compile(r"\bwget\b"), "network fetch (wget)"),
    (re.compile(r"\bpip\s+install\b"), "package install (pip)"),
    (re.compile(r"\bnpm\s+(install|i)\b"), "package install (npm)"),
    (re.compile(r"\buv\s+(add|pip)\b"), "package install (uv)"),
    (re.compile(r"\bsudo\b"), "privilege escalation"),
    (re.compile(r"\bgit\s+push\b"), "git push (gated separately in Phase 8)"),
    (re.compile(r">\s*/|>>\s*/"), "redirect to an absolute path"),
    (re.compile(r"\bchmod\b|\bchown\b"), "permission change"),
    (re.compile(r"\b(mkfs|dd|shutdown|reboot|kill|pkill)\b"), "system-level command"),
    (re.compile(r"[;&|`$]"), "shell metacharacters (chaining/substitution)"),
]

# Files the Coder must never modify, matched against the sandbox-relative path.
_PROTECTED_GLOBS = [
    ".git", ".git/*", "*/.git/*",
    ".github/*", "*.yml", "*.yaml",          # CI config
    "*.env", ".env", ".env.*",               # secrets
    "*.pem", "*.key", "id_rsa*",             # keys
    "pyproject.toml", "poetry.lock", "uv.lock",  # project/deps (dep bumps edit requirements.txt, not these)
    "Dockerfile", "docker-compose*",
]


class GuardrailViolation(RuntimeError):
    """Raised when a command or path is rejected. Carries a human-readable
    reason so the Coder loop can log exactly why it stopped."""


def is_command_allowed(command: str) -> tuple[bool, str]:
    """Return (allowed, reason). A blocked command returns (False, why)."""
    stripped = command.strip()
    if not stripped:
        return False, "empty command"
    for pattern, reason in _BLOCKED_PATTERNS:
        if pattern.search(stripped):
            return False, f"blocked: {reason}"
    return True, "ok"


def _matches_glob(rel_path: str, glob: str) -> bool:
    return Path(rel_path).match(glob)


def is_path_allowed(rel_path: str) -> tuple[bool, str]:
    """Return (allowed, reason) for writing to a sandbox-relative path.

    Rejects paths that climb out of the sandbox (.. or absolute) and any
    path matching a protected glob.
    """
    p = rel_path.strip()
    if not p:
        return False, "empty path"
    if p.startswith("/") or p.startswith("~"):
        return False, "absolute path (must stay inside sandbox)"
    # Normalize and check for escape via ..
    parts = Path(p).parts
    if ".." in parts:
        return False, "path escapes the sandbox (..)"
    for glob in _PROTECTED_GLOBS:
        if _matches_glob(p, glob):
            return False, f"protected file pattern: {glob}"
    return True, "ok"


def assert_command_allowed(command: str) -> None:
    ok, reason = is_command_allowed(command)
    if not ok:
        raise GuardrailViolation(f"Command rejected: {command!r} ({reason})")


def assert_path_allowed(rel_path: str) -> None:
    ok, reason = is_path_allowed(rel_path)
    if not ok:
        raise GuardrailViolation(f"Path rejected: {rel_path!r} ({reason})")