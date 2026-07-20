"""The Orchestrator's polling and triage loop (Phase 2).

On demand (not on a fixed timer), this polls GitHub for eligible issues,
classifies each, uses the Phase 1 agent to draft a plan, and walks each
task through the state machine as far as the pipeline currently reaches.

Phases 3-8 don't exist yet, so after planning we advance a task to
EXPLORING and stop there, clearly marking the boundary. As later phases
land, they slot in at these seams without changing the loop's shape.
"""

from __future__ import annotations

from codepilot.github.classifier import classify_issue
from codepilot.github.github_client import GitHubClient
from codepilot.orchestration.orchestrator import build_orchestrator
from codepilot.core.streaming import BOLD, CYAN, DIM, GREEN, RESET, YELLOW, render_stream
from codepilot.core.task import Task, TaskState


class Orchestrator:
    def __init__(self) -> None:
        self.github = GitHubClient()
        self.agent = build_orchestrator()
        # Issues currently mid-flight. The assignment requires tracking these
        # so a poll never picks up something already being worked.
        self.in_progress: dict[int, Task] = {}
        # Finished tasks kept for the session so the TUI/logs can show history.
        self.completed: list[Task] = []

    # ---------------------------------------------------------------- polling

    def poll_once(self) -> list[Task]:
        """Fetch eligible issues and create Task records for new ones."""
        exclude = set(self.in_progress) | {t.issue.number for t in self.completed}
        issues = self.github.list_issues(exclude_numbers=exclude)
        new_tasks = [Task(issue=i) for i in issues]
        print(f"{DIM}Polled {self.github.repo_name}: {len(new_tasks)} new eligible issue(s).{RESET}")
        return new_tasks

    # ------------------------------------------------------------- triage one

    def triage(self, task: Task) -> None:
        """Classify one task and record it as in-progress."""
        task.task_type = classify_issue(task.issue)
        self.in_progress[task.issue.number] = task
        print(
            f"{CYAN}Issue #{task.issue.number}{RESET} "
            f"[{YELLOW}{task.task_type.value}{RESET}] {task.issue.title}"
        )

    # -------------------------------------------------------------- plan one

    def plan(self, task: Task) -> None:
        """Have the Orchestrator agent draft an implementation plan.

        We pass only the issue text, never file contents (context
        engineering rule: file bodies come later, on demand, in Phase 3).
        """
        task.transition_to(TaskState.EXPLORING)
        prompt = (
            f"A GitHub issue has been assigned to you.\n\n"
            f"Title: {task.issue.title}\n"
            f"Type: {task.task_type.value}\n"
            f"Body:\n{task.issue.body}\n\n"
            f"Draft an implementation plan for this issue using write_todos."
        )
        config = {"configurable": {"thread_id": f"issue-{task.issue.number}"}}
        events = self.agent.stream(
            {"messages": [{"role": "user", "content": prompt}]},
            config=config,
            stream_mode="values",
        )
        render_stream(events)

    # -------------------------------------------------------------- run loop

    def process_new_issues(self) -> None:
        """One full on-demand cycle: poll, then triage + plan each new issue."""
        tasks = self.poll_once()
        if not tasks:
            print(f"{DIM}Nothing new to do.{RESET}")
            return
        for task in tasks:
            print()
            self.triage(task)
            self.plan(task)
            # Phase boundary: everything past EXPLORING (repo mapping,
            # coding, testing, PR) arrives in later phases.
            task.add_note("Reached Phase 2 boundary: planned, awaiting Repo Explorer (Phase 3).")
            print(
                f"{GREEN}Issue #{task.issue.number} planned. "
                f"State: {task.state.value}. Parked at Phase 2 boundary.{RESET}"
            )

    def status(self) -> None:
        print(f"{BOLD}In progress:{RESET} {len(self.in_progress)} | "
              f"{BOLD}Completed:{RESET} {len(self.completed)}")
        for num, task in self.in_progress.items():
            ttype = task.task_type.value if task.task_type else "unclassified"
            print(f"  #{num} [{ttype}] {task.state.value} — {task.issue.title}")