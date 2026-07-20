"""The Skills system.

Every task type gets a specialized playbook. Until now the Coder used one
generic prompt for everything; a documentation change shouldn't be
approached like a bug fix, and a dependency bump has its own rhythm.

A Skill is structured data (not free text) so it's inspectable and
testable: a name, plain-language instructions, ordered workflow steps,
example prompts that fit the type, and forbidden actions that keep the
Coder from doing the wrong thing (e.g. changing behavior during a
docs-only task). The Orchestrator selects a skill from the Phase 2
classifier's output, so this slots onto existing machinery.

There is exactly one skill per TaskType, so selection is a direct lookup
with no fallback ambiguity.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from codepilot.task import TaskType


@dataclass(frozen=True)
class Skill:
    name: str
    task_type: TaskType
    instructions: str
    workflow_steps: list[str] = field(default_factory=list)
    example_prompts: list[str] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=list)

    def as_prompt_block(self) -> str:
        """Render the skill as a text block to prepend to the Coder's task."""
        steps = "\n".join(f"  {i}. {s}" for i, s in enumerate(self.workflow_steps, 1))
        forbidden = "\n".join(f"  - {f}" for f in self.forbidden_actions)
        return (
            f"ACTIVE SKILL: {self.name}\n"
            f"{self.instructions}\n\n"
            f"Workflow:\n{steps}\n\n"
            f"Do NOT:\n{forbidden}"
        )


BUG_FIX_SKILL = Skill(
    name="bug_fix",
    task_type=TaskType.BUG_FIX,
    instructions=(
        "Fix broken behavior with the smallest change that makes the failing "
        "tests pass. Reproduce the fault mentally from the failing test before "
        "editing, and change only what the fault requires."
    ),
    workflow_steps=[
        "Read the failing test(s) to learn the expected behavior.",
        "Locate the exact function or line producing the wrong result.",
        "Make the minimal edit that satisfies the test.",
        "Leave unrelated code, comments, and formatting untouched.",
    ],
    example_prompts=[
        "divide() returns wrong results and never raises on zero",
        "off-by-one error in pagination offset",
    ],
    forbidden_actions=[
        "Rewrite or refactor code unrelated to the bug.",
        "Delete or weaken existing tests to make them pass.",
        "Add new dependencies.",
    ],
)

FEATURE_ADDITION_SKILL = Skill(
    name="feature_addition",
    task_type=TaskType.FEATURE_ADDITION,
    instructions=(
        "Add the requested functionality following the codebase's existing "
        "patterns. Keep the change focused on what the issue asks for and add "
        "tests for the new behavior where the project already has tests."
    ),
    workflow_steps=[
        "Identify where the new behavior belongs from the repo structure.",
        "Implement the feature matching nearby code's style and conventions.",
        "Add or extend tests to cover the new behavior.",
        "Keep the public interface minimal and consistent with existing APIs.",
    ],
    example_prompts=[
        "add a modulo() function to the calculator",
        "support CSV export in the report generator",
    ],
    forbidden_actions=[
        "Introduce scope beyond what the issue requests.",
        "Break or change existing behavior or signatures.",
        "Add heavy dependencies for a small feature.",
    ],
)

DEPENDENCY_UPDATE_SKILL = Skill(
    name="dependency_update",
    task_type=TaskType.DEPENDENCY_UPDATE,
    instructions=(
        "Update the dependency version as requested, editing only the "
        "declaration file (e.g. requirements.txt). Do not touch application "
        "code unless the version bump strictly requires it, and rely on the "
        "test suite to confirm nothing broke."
    ),
    workflow_steps=[
        "Find the dependency declaration and its current pin.",
        "Change the version to the requested target.",
        "Only if tests then fail, make the minimal code change the new "
        "version requires.",
    ],
    example_prompts=[
        "bump requests from 2.25.0 to a current release",
        "upgrade pydantic to v2",
    ],
    forbidden_actions=[
        "Run package installers (blocked by guardrails anyway).",
        "Refactor code that the upgrade doesn't force.",
        "Change unrelated dependency versions.",
    ],
)

DOCUMENTATION_SKILL = Skill(
    name="documentation",
    task_type=TaskType.DOCUMENTATION,
    instructions=(
        "Add or improve documentation only. This includes docstrings, type "
        "hints, comments, and README text. You must not change runtime "
        "behavior in any way; the diff should be behavior-neutral."
    ),
    workflow_steps=[
        "Read the target file to understand each function's actual behavior.",
        "Add accurate docstrings and type hints matching the code's style.",
        "Keep every executable line byte-for-byte unchanged.",
    ],
    example_prompts=[
        "add docstrings and type hints to app/utils.py",
        "document the public API in the README",
    ],
    forbidden_actions=[
        "Change any executable statement or control flow.",
        "Rename functions, arguments, or variables.",
        "Add or remove behavior while 'just' documenting.",
    ],
)

CONFIG_CHANGE_SKILL = Skill(
    name="config_change",
    task_type=TaskType.CONFIG_CHANGE,
    instructions=(
        "Make the requested configuration or tooling change with precision. "
        "Config edits are high-blast-radius, so change exactly the setting "
        "named and nothing adjacent. Note that many config files are "
        "guardrail-protected and cannot be edited by the Coder."
    ),
    workflow_steps=[
        "Locate the specific setting the issue names.",
        "Change only that setting to the requested value.",
        "Verify the change doesn't alter unrelated configuration.",
    ],
    example_prompts=[
        "increase the test timeout in the pytest settings",
        "enable strict mode in the linter config",
    ],
    forbidden_actions=[
        "Edit secrets, CI workflow files, or lockfiles (guardrail-protected).",
        "Change settings the issue did not mention.",
        "Reformat the whole config file.",
    ],
)

# One skill per task type. Direct mapping, no fallback needed since the
# classifier's output space is exactly these five.
SKILLS: dict[TaskType, Skill] = {
    TaskType.BUG_FIX: BUG_FIX_SKILL,
    TaskType.FEATURE_ADDITION: FEATURE_ADDITION_SKILL,
    TaskType.DEPENDENCY_UPDATE: DEPENDENCY_UPDATE_SKILL,
    TaskType.DOCUMENTATION: DOCUMENTATION_SKILL,
    TaskType.CONFIG_CHANGE: CONFIG_CHANGE_SKILL,
}


def select_skill(task_type: TaskType) -> Skill:
    """Return the skill for a task type. Total over TaskType, so no KeyError."""
    return SKILLS[task_type]