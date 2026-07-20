"""Phase 4 driver: propose-and-stop coding on a real issue.

Full inner loop for one issue: poll -> pick -> retrieve target files ->
Coder proposes edits -> show unified diff -> you approve -> apply into
the sandbox. Nothing is committed or pushed (that's Phase 8); this only
writes into the local clone so you can inspect the result.

Usage:
    uv run python scripts/run_coder.py            # lists issues, you pick
    uv run python scripts/run_coder.py 1          # go straight to issue #1
"""

from __future__ import annotations

import sys

from codepilot.classifier import classify_issue
from codepilot.coder import propose_edits
from codepilot.config import settings
from codepilot.diffing import apply_edits, build_diff
from codepilot.github_client import GitHubClient
from codepilot.repo_map import build_repo_map
from codepilot.retrieval import KeywordRetriever
from codepilot.workspace import RepoWorkspace

BOLD = "\033[1m"; DIM = "\033[2m"; CYAN = "\033[36m"
GREEN = "\033[32m"; YELLOW = "\033[33m"; RED = "\033[31m"; RESET = "\033[0m"


def main() -> int:
    problems = settings.validate()
    if problems:
        for p in problems:
            print(f"  ✗ {p}")
        return 1

    gh = GitHubClient()
    workspace = RepoWorkspace()
    print(f"{DIM}Preparing repo and map ...{RESET}")
    repo_map = build_repo_map(workspace, settings.repo_map_token_budget)
    retriever = KeywordRetriever(repo_map.entries)

    issues = gh.list_issues()
    if not issues:
        print("No eligible issues found.")
        return 0

    # Pick an issue
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        number = int(sys.argv[1])
        issue = next((i for i in issues if i.number == number), None)
        if issue is None:
            print(f"Issue #{number} not in the eligible list.")
            return 1
    else:
        print(f"\n{BOLD}Eligible issues:{RESET}")
        for i in issues:
            print(f"  #{i.number}  {i.title}")
        raw = input(f"\n{BOLD}Pick an issue number:{RESET} ").strip()
        issue = next((i for i in issues if str(i.number) == raw), None)
        if issue is None:
            print("Not a valid choice.")
            return 1

    # Classify + retrieve
    task_type = classify_issue(issue)
    task_text = f"{issue.title}\n\n{issue.body}"
    ranked = retriever.retrieve(task_text, k=5)
    target_paths = [p for p, _ in ranked]

    print(f"\n{CYAN}Issue #{issue.number}{RESET} [{YELLOW}{task_type.value}{RESET}] {issue.title}")
    print(f"{DIM}Target files: {', '.join(target_paths) or '(none found)'}{RESET}")

    # Propose
    print(f"{DIM}Coder is reading files and proposing edits ...{RESET}")
    proposal = propose_edits(task_text, target_paths, workspace.path)

    print(f"\n{BOLD}Coder reasoning:{RESET} {proposal.reasoning}")
    if proposal.rejected:
        for path, reason in proposal.rejected:
            print(f"{RED}Blocked edit to {path}: {reason}{RESET}")

    diff = build_diff(proposal, workspace.path)
    if diff.files_changed == 0:
        print(f"{YELLOW}No applicable changes proposed.{RESET}")
        return 0

    print(f"\n{BOLD}Proposed diff{RESET} ({diff.files_changed} file(s)):")
    for line in diff.text.splitlines():
        color = GREEN if line.startswith("+") else RED if line.startswith("-") else DIM
        print(f"{color}{line}{RESET}")
    print(f"{DIM}Diff saved to {diff.diff_path}{RESET}")

    # Gate
    answer = input(f"\n{BOLD}Apply these changes to the sandbox? [y/N]{RESET} ").strip().lower()
    if answer == "y":
        written = apply_edits(proposal, workspace.path)
        print(f"{GREEN}Applied to: {', '.join(written)}{RESET}")
        print(f"{DIM}Inspect them in {workspace.path}{RESET}")
    else:
        print(f"{YELLOW}Discarded. Nothing was written.{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())