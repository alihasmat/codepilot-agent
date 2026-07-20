"""Phase 3 driver: build the Repo Map and test retrieval.

Clones the target repo, builds (or loads from cache) the Repo Map,
prints it, then runs both retrieval strategies against a task so you can
compare keyword vs embedding results.

Usage:
    uv run python scripts/run_explorer.py
    uv run python scripts/run_explorer.py --rebuild      # ignore cache
    uv run python scripts/run_explorer.py "fix divide bug"   # custom task
"""

from __future__ import annotations

import sys

from codepilot.config import settings
from codepilot.repo_map import CACHE_PATH, build_repo_map
from codepilot.retrieval import EmbeddingRetriever, KeywordRetriever
from codepilot.workspace import WORKSPACE_ROOT, RepoWorkspace

BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def main() -> int:
    problems = [p for p in settings.validate() if "GITHUB" in p.upper()]
    if problems:
        for p in problems:
            print(f"  ✗ {p}")
        return 1

    args = sys.argv[1:]
    force = "--rebuild" in args
    args = [a for a in args if a != "--rebuild"]
    task = args[0] if args else "divide() returns wrong results and never raises on zero"

    workspace = RepoWorkspace()
    print(f"{DIM}Cloning/updating {workspace.repo_name} into {WORKSPACE_ROOT} ...{RESET}")
    repo_map = build_repo_map(workspace, settings.repo_map_token_budget, force=force)

    from codepilot.tokens import count_tokens
    print(f"\n{BOLD}Repo Map{RESET} (sha {repo_map.sha[:8]}, "
          f"{len(repo_map.entries)} files, "
          f"{count_tokens(repo_map.rendered)} tokens, budget {settings.repo_map_token_budget}):")
    print(DIM + repo_map.rendered + RESET)
    print(f"{DIM}Cached at {CACHE_PATH}{RESET}")

    print(f"\n{BOLD}Task:{RESET} {task}")

    kw = KeywordRetriever(repo_map.entries)
    print(f"\n{CYAN}Keyword retrieval (top 5):{RESET}")
    for path, score in kw.retrieve(task, k=5):
        print(f"  {score:5.1f}  {path}")

    emb = EmbeddingRetriever(repo_map.entries, workspace.path, WORKSPACE_ROOT.parent / "chroma")
    print(f"\n{YELLOW}Embedding retrieval (top 5):{RESET}")
    try:
        for path, score in emb.retrieve(task, k=5):
            print(f"  {score:5.3f}  {path}")
    except Exception as e:
        print(f"  {DIM}(embedding index building, first run downloads a small model)... {e}{RESET}")

    return 0


if __name__ == "__main__":
    sys.exit(main())