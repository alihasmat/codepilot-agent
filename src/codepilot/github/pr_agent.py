"""The PR Agent.

Once a fix is verified and approved, this turns the sandbox changes into a
real pull request: create a branch named from the issue, commit with a
structured message, push, and open the PR via the GitHub API with a body
describing what was done. Branch/commit/push run as git in the sandbox
(which already holds the approved changes); only the PR object is created
through the API.

If the branch can't be pushed cleanly (e.g. it already exists remotely),
the agent reports the problem rather than forcing, so a conflict becomes a
FAILED task instead of a destructive overwrite.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from codepilot.github.github_client import GitHubClient, IssueSummary
from codepilot.core.task import TaskType


@dataclass
class PRResult:
    success: bool
    branch: str
    pr_url: str | None
    message: str


def _slugify(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].rstrip("-")


def branch_name(issue: IssueSummary, task_type: TaskType) -> str:
    """e.g. codepilot/bug_fix/issue-1-divide-returns-wrong-results"""
    return f"codepilot/{task_type.value}/issue-{issue.number}-{_slugify(issue.title)}"


def commit_message(issue: IssueSummary, task_type: TaskType, summary: str) -> str:
    type_prefix = {
        TaskType.BUG_FIX: "fix",
        TaskType.FEATURE_ADDITION: "feat",
        TaskType.DEPENDENCY_UPDATE: "chore",
        TaskType.DOCUMENTATION: "docs",
        TaskType.CONFIG_CHANGE: "chore",
    }.get(task_type, "chore")
    return (
        f"{type_prefix}: {issue.title}\n\n"
        f"{summary}\n\n"
        f"Resolves #{issue.number}\n\n"
        f"Automated by CodePilot."
    )


def pr_body(issue: IssueSummary, task_type: TaskType, summary: str, tests_line: str) -> str:
    return (
        f"## What this does\n\n{summary}\n\n"
        f"## Issue\n\nResolves #{issue.number}: {issue.title}\n\n"
        f"## Verification\n\n{tests_line}\n\n"
        f"## Task type\n\n`{task_type.value}`\n\n"
        f"---\n*This PR was generated automatically by CodePilot and is "
        f"awaiting human review.*"
    )


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def open_pr_for_task(
    *,
    issue: IssueSummary,
    task_type: TaskType,
    summary: str,
    tests_line: str,
    sandbox_root: Path,
    github: GitHubClient,
    base_branch: str,
) -> PRResult:
    """Branch, commit, push the sandbox changes and open a PR. """
    branch = branch_name(issue, task_type)

    # Create and switch to the branch.
    created = _git(["checkout", "-b", branch], sandbox_root)
    if created.returncode != 0:
        # Branch may already exist locally from a prior run; switch to it.
        sw = _git(["checkout", branch], sandbox_root)
        if sw.returncode != 0:
            return PRResult(False, branch, None,
                            f"Could not create or switch to branch: {created.stderr.strip()}")

    # Stage changes, but never compiled/cache artifacts. Running the test
    # suite generates app/__pycache__/*.pyc and .pytest_cache; if those get
    # committed they cause spurious merge conflicts (bytecode differs per run)
    # and pollute the PR. We exclude them explicitly at stage time.
    _git([
        "add", "-A", "--",
        ".",
        ":(exclude)working",
        ":(exclude)__pycache__",
        ":(exclude)**/__pycache__",
        ":(exclude)*.pyc",
        ":(exclude)**/*.pyc",
        ":(exclude).pytest_cache",
        ":(exclude)**/.pytest_cache",
        ":(exclude).chroma",
        ":(exclude).codepilot_cache",
    ], sandbox_root)
    msg = commit_message(issue, task_type, summary)
    committed = _git(["commit", "-m", msg], sandbox_root)
    if committed.returncode != 0 and "nothing to commit" in (committed.stdout + committed.stderr):
        return PRResult(False, branch, None, "No staged changes to commit.")

    # Push. A non-zero here usually means the branch exists remotely (conflict).
    pushed = _git(["push", "-u", "origin", branch], sandbox_root)
    if pushed.returncode != 0:
        return PRResult(
            False, branch, None,
            f"Push failed (branch may already exist remotely). "
            f"Reporting as conflict rather than forcing: {pushed.stderr.strip()}",
        )

    # Open the PR via the API.
    try:
        labels = ["ai-generated", task_type.value.replace("_", "-")]
        url = github.open_pull_request(
            head_branch=branch,
            base_branch=base_branch,
            title=commit_message(issue, task_type, summary).splitlines()[0],
            body=pr_body(issue, task_type, summary, tests_line),
            labels=None,  # labels may not exist on the repo; skip to avoid errors
        )
        return PRResult(True, branch, url, "PR opened successfully.")
    except Exception as exc:  # noqa: BLE001
        return PRResult(False, branch, None, f"Branch pushed but PR creation failed: {exc}")