"""Shared pipeline orchestration.

Both the CLI (run_verify.py) and the TUI (Phase 9) need the same sequence:
retrieve -> classify -> load skill -> recall memory -> fix-and-verify ->
gates -> PR -> record memory. Rather than duplicate that in two drivers,
it lives here as run_pipeline(), parameterized by callbacks:

  log(msg)         -> surface progress (prints to stdout, or a TUI panel)
  approve(reason)  -> ask a human to approve a gate (input(), or a TUI modal)

This keeps the orchestration testable and lets the TUI be a thin skin over
proven logic, which is exactly why the TUI is built last.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from codepilot.classifier import classify_issue
from codepilot.gates import (
    gate_file_count, gate_pr_to_main, gate_push,
)
from codepilot.github_client import GitHubClient, IssueSummary
from codepilot.memory_episodic import Episode, EpisodicMemory
from codepilot.memory_semantic import SemanticMemory
from codepilot.pr_agent import open_pr_for_task
from codepilot.repo_map import build_repo_map
from codepilot.retrieval import KeywordRetriever
from codepilot.skills import select_skill
from codepilot.verify_loop import implement_and_verify
from codepilot.workspace import RepoWorkspace

LogFn = Callable[[str], None]
ApproveFn = Callable[[str], bool]


@dataclass
class PipelineOutcome:
    issue_number: int
    verified: bool
    pr_url: str | None = None
    branch: str | None = None
    message: str = ""


def _reset_sandbox(workspace: RepoWorkspace, base: str) -> None:
    subprocess.run(["git", "checkout", base], cwd=workspace.path, capture_output=True, text=True)
    subprocess.run(["git", "reset", "--hard", f"origin/{base}"], cwd=workspace.path, capture_output=True, text=True)
    subprocess.run(["git", "clean", "-fd", "working"], cwd=workspace.path, capture_output=True, text=True)


def run_pipeline(
    issue: IssueSummary,
    workspace: RepoWorkspace,
    gh: GitHubClient,
    retriever: KeywordRetriever,
    *,
    log: LogFn,
    approve: ApproveFn,
    auto_approve_fix: bool = False,
) -> PipelineOutcome:
    """Run one issue through the full pipeline, reporting via callbacks."""
    task_type = classify_issue(issue)
    skill = select_skill(task_type)
    task_text = f"{issue.title}\n\n{issue.body}"
    target_paths = [p for p, _ in retriever.retrieve(task_text, k=5)]

    log(f"Classified as {task_type.value}; skill '{skill.name}' active.")
    log(f"Target files: {', '.join(target_paths)}")

    semantic = SemanticMemory()
    episodic = EpisodicMemory()
    lessons = semantic.retrieve(task_text, k=3)
    if lessons:
        log(f"Recalled {len(lessons)} lesson(s) from past work.")
        for l in lessons:
            log(f"  lesson: {l}")

    task_with_memory = task_text
    if lessons:
        task_with_memory += "\n\nLessons from past work:\n" + "\n".join(f"- {l}" for l in lessons)

    log("Running fix-and-verify loop...")
    result = implement_and_verify(
        task_with_memory, target_paths, workspace.path,
        skill_block=skill.as_prompt_block(),
    )

    for a in result.attempts:
        status = "PASS" if a.test_passed else "FAIL"
        log(f"Attempt {a.attempt} [{status}]: {a.reasoning}")
        if not a.test_passed and a.failure_summary:
            log(f"  {a.failure_summary[:120]}")

    if not result.success:
        log("Could not verify a fix. Task marked FAILED.")
        return PipelineOutcome(issue.number, verified=False, message="verification failed")

    # Compute the diff for review.
    git_diff = subprocess.run(
        ["git", "diff", "--", ".", ":(exclude)working"],
        cwd=workspace.path, capture_output=True, text=True,
    ).stdout
    changed = subprocess.run(
        ["git", "diff", "--name-only", "--", ".", ":(exclude)working"],
        cwd=workspace.path, capture_output=True, text=True,
    ).stdout.strip()
    changed_files = [c for c in changed.splitlines() if c]
    n_files = len(changed_files)

    log(f"Tests pass. {n_files} file(s) changed. Diff ready for review.")

    # Approve the fix itself (unless auto-approving in a demo).
    if not auto_approve_fix:
        if not approve(f"Approve the verified fix for issue #{issue.number}?\n\n{git_diff}"):
            _reset_sandbox(workspace, gh.default_branch)
            return PipelineOutcome(issue.number, verified=True, message="fix not approved")

    # HITL gates before touching the remote.
    base = gh.default_branch
    for gate in (gate_file_count(n_files), gate_push(), gate_pr_to_main(base, base)):
        if gate.required and not approve(f"Gate: {gate.reason}. Proceed?"):
            _reset_sandbox(workspace, base)
            return PipelineOutcome(issue.number, verified=True, message=f"gate declined: {gate.reason}")

    # Record memory.
    summary = result.attempts[-1].reasoning if result.attempts else "change applied"
    episodic.record(Episode(
        issue_number=issue.number, title=issue.title, task_type=task_type.value,
        files=changed_files, outcome="success", summary=summary,
    ))
    lesson = semantic.extract_and_store(
        task_type=task_type.value, title=issue.title, summary=summary,
        diff=git_diff, issue_number=issue.number,
    )
    if lesson:
        log(f"Lesson learned: {lesson.text}")

    # Open the PR.
    log("Creating branch, committing, pushing, opening PR...")
    tests_line = (
        f"{result.final_tests.passed} passed, {result.final_tests.failed} failed (pre-existing)"
        if result.final_tests else "verified by CodePilot"
    )
    pr = open_pr_for_task(
        issue=issue, task_type=task_type, summary=summary, tests_line=tests_line,
        sandbox_root=workspace.path, github=gh, base_branch=base,
    )
    _reset_sandbox(workspace, base)

    if pr.success:
        log(f"PR opened: {pr.pr_url}")
        return PipelineOutcome(issue.number, verified=True, pr_url=pr.pr_url,
                               branch=pr.branch, message="PR opened")
    log(f"PR not opened: {pr.message}")
    return PipelineOutcome(issue.number, verified=True, message=pr.message)