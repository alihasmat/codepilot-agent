"""Working memory: the scratchpad for a single task.

This is the short-lived context an agent needs while working one issue:
what the issue is, its type, which files are in play, what's been tried,
and how tests responded. It lives only for the duration of the task.

Your Task dataclass (Phase 2) already holds most of this; WorkingMemory
formalizes it into something each agent receives, and gives a compact
text rendering that can be dropped into a prompt without dumping raw
objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from codepilot.core.task import Task


@dataclass
class WorkingMemory:
    task: Task
    target_files: list[str] = field(default_factory=list)
    attempts_summary: list[str] = field(default_factory=list)
    retrieved_lessons: list[str] = field(default_factory=list)

    def record_attempt(self, note: str) -> None:
        self.attempts_summary.append(note)

    def as_context(self) -> str:
        """Render as a compact prompt block. Only includes non-empty sections."""
        lines = [
            f"Issue #{self.task.issue.number}: {self.task.issue.title}",
            f"Type: {self.task.task_type.value if self.task.task_type else 'unknown'}",
            f"State: {self.task.state.value}",
        ]
        if self.target_files:
            lines.append(f"Files in play: {', '.join(self.target_files)}")
        if self.retrieved_lessons:
            lines.append("Relevant lessons from past work:")
            lines.extend(f"  - {l}" for l in self.retrieved_lessons)
        if self.attempts_summary:
            lines.append("Attempts so far:")
            lines.extend(f"  - {a}" for a in self.attempts_summary)
        return "\n".join(lines)