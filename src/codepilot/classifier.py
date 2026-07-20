"""Classify a GitHub issue into one of CodePilot's task types.

The task type decides which Skill the Orchestrator loads (Phase 6) and,
later, which subagent chain runs. We ask the LLM for a single-word
classification rather than pattern-matching issue text, because issue
wording varies wildly and a small structured call is both cheap and far
more reliable. We force a constrained output and validate it, falling
back to a safe default if the model returns anything unexpected.
"""

from __future__ import annotations

from langchain.chat_models import init_chat_model

from codepilot.config import settings
from codepilot.github_client import IssueSummary
from codepilot.task import TaskType

_CLASSIFY_PROMPT = """\
You are triaging a software issue. Classify it into exactly ONE category:

- bug_fix: something is broken and should work differently
- feature_addition: new functionality is requested
- dependency_update: upgrading, bumping, or changing a dependency/package version
- documentation: docstrings, README, comments, type hints, or docs
- config_change: build config, CI, settings, or tooling configuration

Respond with ONLY the category name, nothing else.

Issue title: {title}
Issue body: {body}
Labels: {labels}
"""

_VALID = {t.value for t in TaskType}


def classify_issue(issue: IssueSummary, model: str | None = None) -> TaskType:
    llm = init_chat_model(model or settings.model)
    prompt = _CLASSIFY_PROMPT.format(
        title=issue.title,
        body=issue.body[:1500],  # cap body so a huge issue can't blow the prompt
        labels=", ".join(issue.labels) or "none",
    )
    reply = llm.invoke(prompt)
    raw = (reply.text if isinstance(getattr(reply, "text", None), str) else str(reply.content)).strip().lower()

    # The model should return a bare category, but be defensive: find the
    # first valid category token appearing in the reply.
    for token in raw.replace(",", " ").split():
        if token in _VALID:
            return TaskType(token)
    for category in _VALID:
        if category in raw:
            return TaskType(category)

    # Nothing matched. Default to bug_fix as the most conservative pipeline
    # (it writes a failing test first, so it can't silently do harm).
    return TaskType.BUG_FIX