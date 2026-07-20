"""Human-readable streaming for a deep agent.

A deep agent's .stream() emits raw state updates: message chunks, tool
calls, tool results. Dumped as-is they're an unreadable wall of objects.
This module turns that stream into something a person can follow in a
terminal, and it's the same rendering logic the Phase 9 TUI will reuse
(just pointed at a widget instead of stdout).
"""

from __future__ import annotations

from typing import Iterable

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

# ANSI colours. Kept tiny and dependency-free.
DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def _render_todos(args: dict) -> str:
    """Pretty-print a write_todos call as a checklist."""
    todos = args.get("todos", [])
    lines = [f"{BOLD}Plan:{RESET}"]
    status_mark = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
    for todo in todos:
        content = todo.get("content", todo) if isinstance(todo, dict) else todo
        status = todo.get("status", "pending") if isinstance(todo, dict) else "pending"
        lines.append(f"  {status_mark.get(status, '[ ]')} {content}")
    return "\n".join(lines)


def render_stream(events: Iterable[dict]) -> None:
    """Consume a deep agent stream and print it as it arrives.

    We stream with stream_mode="values", so each event is the full state
    dict. We track the last message we've already printed to avoid
    reprinting the growing history on every tick.
    """
    seen = 0
    for event in events:
        messages: list[BaseMessage] = event.get("messages", [])
        for msg in messages[seen:]:
            _print_message(msg)
        seen = len(messages)


def _print_message(msg: BaseMessage) -> None:
    if isinstance(msg, AIMessage):
        # Text the model produced (its reasoning / narration).
        text = msg.text if isinstance(getattr(msg, "text", None), str) else ""
        if text.strip():
            print(f"{CYAN}[Orchestrator]{RESET} {text.strip()}")
        # Any tool calls it decided to make.
        for call in msg.tool_calls or []:
            name = call.get("name", "?")
            args = call.get("args", {})
            if name == "write_todos":
                print(f"{YELLOW}{_render_todos(args)}{RESET}")
            else:
                print(f"{DIM}[tool call] {name}({args}){RESET}")
    elif isinstance(msg, ToolMessage):
        # Result handed back from a tool. In Phase 1 the only tool is
        # write_todos, whose result is just an ack, so we keep it quiet.
        content = str(msg.content).strip()
        if content and content.lower() not in {"", "null", "none"}:
            print(f"{GREEN}[tool result] {content[:200]}{RESET}")