"""The Orchestrator agent.

In Phase 1 this is a single deep agent with one job: take a coding task
described in plain English and produce a concrete implementation plan
using the built-in write_todos tool. It has no GitHub access and spawns
no subagents yet; both arrive in later phases.

Keeping the agent construction in its own module means later phases can
import build_orchestrator() and extend it (adding tools, subagents,
memory) without rewriting the driver loop.
"""

from __future__ import annotations

from deepagents import create_deep_agent
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph

from codepilot.core.config import settings

# The system prompt is the agent's job description. In Phase 1 we deliberately
# steer it toward planning rather than doing, because it has no tools to act
# with yet. Later phases will expand this prompt as real capabilities land.
ORCHESTRATOR_SYSTEM_PROMPT = """\
You are the Orchestrator of CodePilot, an autonomous coding assistant that \
behaves like a careful junior software engineer.

Right now you are in planning mode. You have a virtual filesystem with file \
tools (ls, read_file), but no repository has been loaded into it yet, so it is \
empty. That is expected at this stage. Later phases will populate it with a \
real repository to work on.

For every task the user gives you:
1. Restate the task in one sentence so the user can confirm you understood it.
2. Use the write_todos tool to record a short, ordered checklist of the steps \
you would take to complete it, written against the real files the task refers \
to (for example "read app/calculator.py to locate the divide function"). Assume \
those files will exist once a repo is loaded; plan as if they are there.
3. Note any assumptions you are making and anything you would need to proceed.

Rules:
- The filesystem is empty because no repo is loaded, NOT because the files the \
user mentions don't exist. Do not treat a missing file as a reason to stop.
- NEVER create, fabricate, or offer to create sample/placeholder source files \
(for example a fake app/utils.py). You plan against real code; you do not \
invent it. If a file isn't loaded yet, simply plan to read it once it is.
- Prefer small, surgical steps over vague large ones.
- If a task is genuinely ambiguous, state what you would clarify rather than \
guessing silently.
- Be concise. The user is watching your reasoning stream in a terminal.
"""


def build_orchestrator(model: str | None = None) -> CompiledStateGraph:
    """Construct the Orchestrator deep agent.

    The write_todos planning tool is provided automatically by deepagents'
    TodoListMiddleware, so we don't pass it explicitly. summarization keeps
    long conversations from overflowing the context window, which matters
    once tasks get chatty in later phases; harmless to enable now.
    """
    return create_deep_agent(
        model=model or settings.model,
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        checkpointer=InMemorySaver(),
    )