"""Phase 5 driver: autonomous fix-and-verify, then approve.

Runs the full loop on one issue: retrieve files, then let the Coder and
Test Agent iterate in the sandbox (auto-applying retries) until tests
pass or retries run out. Only then is the final diff shown for approval.

Because retries apply into the sandbox, we reset the sandbox to a clean
checkout at the start so each run is reproducible.

Usage:
    uv run python scripts/run_verify.py 1
"""

from __future__ import annotations

import subprocess
import sys

from codepilot.classifier import classify_issue
from codepilot.config import settings
from codepilot.github_client import GitHubClient
from codepilot.repo_map import build_repo_map
from codepilot.retrieval import KeywordRetriever
from codepilot.verify_loop import implement_and_verify
from codepilot.workspace import RepoWorkspace

BOLD="\033[1m"; DIM="\033[2m"; CYAN="\033[36m"; GREEN="\033[32m"
YELLOW="\033[33m"; RED="\033[31m"; RESET="\033[0m"


def _reset_sandbox(workspace: RepoWorkspace) -> None:
    """Restore the clone to a pristine HEAD so retries don't stack across runs."""
    subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=workspace.path,
                   capture_output=True, text=True)
    subprocess.run(["git", "clean", "-fd", "working"], cwd=workspace.path,
                   capture_output=True, text=True)


def main() -> int:
    problems = settings.validate()
    if problems:
        for p in problems:
            print(f"  ✗ {p}")
        return 1

    gh = GitHubClient()
    workspace = RepoWorkspace()
    print(f"{DIM}Preparing repo and map ...{RESET}")
    build_repo_map(workspace, settings.repo_map_token_budget)
    _reset_sandbox(workspace)
    repo_map = build_repo_map(workspace, settings.repo_map_token_budget, force=True)
    retriever = KeywordRetriever(repo_map.entries)

    issues = gh.list_issues()
    if not issues:
        print("No eligible issues found.")
        return 0

    number = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else issues[0].number
    issue = next((i for i in issues if i.number == number), None)
    if issue is None:
        print(f"Issue #{number} not eligible.")
        return 1

    task_type = classify_issue(issue)
    task_text = f"{issue.title}\n\n{issue.body}"
    target_paths = [p for p, _ in retriever.retrieve(task_text, k=5)]

    print(f"\n{CYAN}Issue #{issue.number}{RESET} [{YELLOW}{task_type.value}{RESET}] {issue.title}")
    print(f"{DIM}Target files: {', '.join(target_paths)}{RESET}")
    print(f"{DIM}Running fix-and-verify loop (max {settings.max_coder_retries} attempts)...{RESET}\n")

    result = implement_and_verify(task_text, target_paths, workspace.path)

    for a in result.attempts:
        status = f"{GREEN}PASS{RESET}" if a.test_passed else f"{RED}FAIL{RESET}"
        print(f"{BOLD}Attempt {a.attempt}{RESET} [{status}]  files: {', '.join(a.files_changed) or 'none'}")
        print(f"  {DIM}{a.reasoning}{RESET}")
        if not a.test_passed and a.failure_summary:
            for line in a.failure_summary.splitlines()[:4]:
                print(f"  {RED}{line}{RESET}")

    if result.final_tests:
        t = result.final_tests
        print(f"\n{BOLD}Final tests:{RESET} {GREEN}{t.passed} passed{RESET}, "
              f"{RED}{t.failed} failed{RESET}, {t.errors} errors")

    if not result.success:
        print(f"\n{RED}Could not make tests pass after {len(result.attempts)} attempt(s). "
              f"Task would be marked FAILED.{RESET}")
        return 0

    # Success: show what actually changed in the sandbox, computed from git
    # (HEAD vs working tree) so it reflects every applied edit across all
    # attempts, not a proposal compared against the already-modified files.
    git_diff = subprocess.run(
        ["git", "diff", "--", ".", ":(exclude)working"],
        cwd=workspace.path, capture_output=True, text=True,
    ).stdout
    changed = subprocess.run(
        ["git", "diff", "--name-only", "--", ".", ":(exclude)working"],
        cwd=workspace.path, capture_output=True, text=True,
    ).stdout.strip()
    n_files = len([c for c in changed.splitlines() if c])

    print(f"\n{GREEN}Tests pass.{RESET} {BOLD}Final diff{RESET} ({n_files} file(s)):")
    if git_diff.strip():
        for line in git_diff.splitlines():
            color = GREEN if line.startswith("+") else RED if line.startswith("-") else DIM
            print(f"{color}{line}{RESET}")
    else:
        print(f"{DIM}(no textual changes){RESET}")

    answer = input(f"\n{BOLD}Approve this verified fix? [y/N]{RESET} ").strip().lower()
    if answer == "y":
        print(f"{GREEN}Approved. Ready for Phase 8 (branch, commit, PR).{RESET}")
    else:
        _reset_sandbox(workspace)
        print(f"{YELLOW}Discarded and sandbox reset.{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())