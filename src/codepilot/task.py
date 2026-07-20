"""Task lifecycle for CodePilot.

The Orchestrator drives each issue through a fixed set of states. This
state machine is owned by ordinary Python, NOT by the language model.
An LLM will happily claim it's "done" when it isn't; deterministic code
decides what state a task is in, and only legal transitions are allowed.

State flow (from the assignment):
    TRIAGED -> EXPLORING -> IMPLEMENTING -> TESTING -> PR_OPENED -> DONE
Any state may also go to FAILED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from codepilot.github_client import IssueSummary


class TaskState(str, Enum):
    TRIAGED = "TRIAGED"
    EXPLORING = "EXPLORING"
    IMPLEMENTING = "IMPLEMENTING"
    TESTING = "TESTING"
    PR_OPENED = "PR_OPENED"
    DONE = "DONE"
    FAILED = "FAILED"


# Which states each state is allowed to move to. Anything not listed is a bug.
_ALLOWED: dict[TaskState, set[TaskState]] = {
    TaskState.TRIAGED: {TaskState.EXPLORING, TaskState.FAILED},
    TaskState.EXPLORING: {TaskState.IMPLEMENTING, TaskState.FAILED},
    TaskState.IMPLEMENTING: {TaskState.TESTING, TaskState.FAILED},
    TaskState.TESTING: {TaskState.IMPLEMENTING, TaskState.PR_OPENED, TaskState.FAILED},
    TaskState.PR_OPENED: {TaskState.DONE, TaskState.FAILED},
    TaskState.DONE: set(),
    TaskState.FAILED: set(),
}

TERMINAL = {TaskState.DONE, TaskState.FAILED}


class IllegalTransition(RuntimeError):
    """Raised when code tries to move a task into a state it can't reach.
    Catching these early surfaces orchestration logic bugs loudly instead
    of letting a task drift into an impossible state."""


class TaskType(str, Enum):
    BUG_FIX = "bug_fix"
    FEATURE_ADDITION = "feature_addition"
    DEPENDENCY_UPDATE = "dependency_update"
    DOCUMENTATION = "documentation"
    CONFIG_CHANGE = "config_change"


@dataclass
class Task:
    """The working record for one issue as it moves through the pipeline.

    This is also the seed of Phase 7's working memory: as later phases add
    a repo map, relevant files, diffs and test results, they hang off this
    same object rather than living in scattered globals.
    """

    issue: IssueSummary
    task_type: TaskType | None = None
    state: TaskState = TaskState.TRIAGED
    history: list[TaskState] = field(default_factory=lambda: [TaskState.TRIAGED])
    notes: list[str] = field(default_factory=list)
    retry_count: int = 0

    def transition_to(self, new_state: TaskState) -> None:
        if new_state not in _ALLOWED[self.state]:
            raise IllegalTransition(
                f"Issue #{self.issue.number}: cannot go {self.state.value} -> {new_state.value}"
            )
        self.state = new_state
        self.history.append(new_state)

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL

    def add_note(self, note: str) -> None:
        self.notes.append(note)