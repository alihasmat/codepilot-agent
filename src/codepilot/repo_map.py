"""The Repo Map: a compressed, queryable picture of the repository.

A real repo has too many files to fit in any context window. The Repo
Map summarizes each file down to its path, language, exported symbols,
and a one-line description, then packs as many summaries as fit inside a
token budget (default 4000). Subagents read this map to decide which
files to open, instead of the Orchestrator stuffing file bodies into
prompts.

For Python files we extract symbols precisely using the ast module. For
other languages we fall back to lightweight regex, which is good enough
for a one-line summary. The map is cached to disk keyed by commit SHA so
we only rebuild when files actually change.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from codepilot.tokens import count_tokens
from codepilot.workspace import RepoWorkspace

# Directories and files never worth mapping.
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".codepilot_cache", "dist", "build"}
_SKIP_SUFFIXES = {".pyc", ".lock", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2"}

_LANG_BY_SUFFIX = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".jsx": "javascript",
    ".tsx": "typescript", ".md": "markdown", ".txt": "text", ".json": "json",
    ".toml": "toml", ".yaml": "yaml", ".yml": "yaml", ".cfg": "config", ".sh": "shell",
}

CACHE_PATH = RepoWorkspace().path.parent / "repo_map.json"


@dataclass
class FileEntry:
    path: str
    language: str
    symbols: list[str]
    description: str


def _language_of(path: Path) -> str:
    return _LANG_BY_SUFFIX.get(path.suffix.lower(), "other")


def _python_symbols(source: str) -> tuple[list[str], str]:
    """Top-level function/class names and a one-line description for Python."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], "python file (unparseable)"
    symbols = [
        n.name for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    doc = ast.get_docstring(tree)
    if doc:
        description = doc.strip().splitlines()[0][:100]
    elif symbols:
        description = f"defines {', '.join(symbols[:4])}"
    else:
        description = "python module"
    return symbols, description


def _generic_symbols(source: str, language: str) -> tuple[list[str], str]:
    """Best-effort symbol extraction for non-Python files."""
    symbols: list[str] = []
    if language in {"javascript", "typescript"}:
        symbols = re.findall(r"(?:function|class|const|export\s+(?:function|class|const))\s+([A-Za-z_$][\w$]*)", source)
    first_line = next((l.strip() for l in source.splitlines() if l.strip()), "")
    description = (first_line[:100] or f"{language} file")
    # dedupe while preserving order
    seen: set[str] = set()
    symbols = [s for s in symbols if not (s in seen or seen.add(s))]
    return symbols[:8], description


def _summarize_file(abs_path: Path, rel_path: str) -> FileEntry | None:
    language = _language_of(abs_path)
    try:
        source = abs_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    if language == "python":
        symbols, description = _python_symbols(source)
    else:
        symbols, description = _generic_symbols(source, language)
    return FileEntry(path=rel_path, language=language, symbols=symbols, description=description)


def _walk(root: Path) -> list[FileEntry]:
    entries: list[FileEntry] = []
    root = root.resolve()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(root)
        # Check skip-dirs against the path RELATIVE to the repo root, so an
        # ancestor of the root (like .codepilot_cache) can't skip everything.
        if any(part in _SKIP_DIRS for part in rel_path.parts):
            continue
        if path.suffix.lower() in _SKIP_SUFFIXES:
            continue
        rel = str(rel_path)
        entry = _summarize_file(path, rel)
        if entry is not None:
            entries.append(entry)
    return entries


def _render_entry(entry: FileEntry) -> str:
    syms = f" [{', '.join(entry.symbols)}]" if entry.symbols else ""
    return f"{entry.path} ({entry.language}){syms}: {entry.description}"


def render_map(entries: list[FileEntry], token_budget: int) -> str:
    """Render entries as text, packing as many as fit under the budget.

    Directory-shallow, high-signal files (source code) are kept before
    docs/config so that if we must truncate, we drop the least useful
    entries first.
    """
    def priority(e: FileEntry) -> int:
        return {"python": 0, "typescript": 1, "javascript": 1}.get(e.language, 2)

    ordered = sorted(entries, key=lambda e: (priority(e), e.path))
    lines: list[str] = ["# Repo Map", ""]
    used = count_tokens("\n".join(lines))
    truncated = 0
    for entry in ordered:
        line = _render_entry(entry)
        cost = count_tokens(line) + 1
        if used + cost > token_budget:
            truncated += 1
            continue
        lines.append(line)
        used += cost
    if truncated:
        lines.append(f"\n# ({truncated} more files omitted to stay within {token_budget} tokens)")
    return "\n".join(lines)


@dataclass
class RepoMap:
    sha: str
    entries: list[FileEntry]
    rendered: str

    def to_cache(self, path: Path = CACHE_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "sha": self.sha,
            "entries": [asdict(e) for e in self.entries],
            "rendered": self.rendered,
        }
        path.write_text(json.dumps(payload, indent=2))

    @classmethod
    def from_cache(cls, path: Path = CACHE_PATH) -> "RepoMap | None":
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return cls(
            sha=data["sha"],
            entries=[FileEntry(**e) for e in data["entries"]],
            rendered=data["rendered"],
        )


def build_repo_map(
    workspace: RepoWorkspace,
    token_budget: int,
    *,
    force: bool = False,
) -> RepoMap:
    """Build (or load from cache) the Repo Map for the current checkout.

    Cache invalidation: if a cached map exists and its SHA matches the
    current HEAD, reuse it. If the SHA differs but no mapped files changed,
    also reuse. Otherwise rebuild.
    """
    workspace.ensure_cloned()
    current = workspace.current_sha()
    cached = None if force else RepoMap.from_cache()

    if cached is not None:
        if cached.sha == current:
            return cached
        changed = workspace.changed_files_since(cached.sha)
        mapped = {e.path for e in cached.entries}
        if changed and changed.isdisjoint(mapped):
            # Files changed, but none that we'd mapped: cache still valid.
            cached.sha = current
            cached.to_cache()
            return cached

    entries = _walk(workspace.path)
    rendered = render_map(entries, token_budget)
    repo_map = RepoMap(sha=current, entries=entries, rendered=rendered)
    repo_map.to_cache()
    return repo_map