"""Phase 1 driver: a plain terminal loop over the Orchestrator agent.

Type a coding task, watch the Orchestrator restate it and produce a plan
via write_todos. No GitHub, no subagents, no file access yet. This is the
smallest possible harness that proves the agent core works end to end.

Usage:
    uv run python scripts/run_orchestrator.py
"""

from __future__ import annotations

import sys
import uuid

from codepilot.core.config import settings
from codepilot.orchestration.orchestrator import build_orchestrator
from codepilot.core.streaming import BOLD, DIM, RESET, render_stream

BANNER = f"""{BOLD}CodePilot Orchestrator — Phase 1 (planning only){RESET}
{DIM}Type a coding task and watch it plan. Commands: /new (fresh session), /quit.{RESET}
Example: Fix the divide() bug in app/calculator.py so it does true division.
"""


def main() -> int:
    problems = settings.validate()
    if problems:
        print("Config problems, fix these first:")
        for p in problems:
            print(f"  ✗ {p}")
        return 1

    agent = build_orchestrator()
    print(BANNER)

    # A thread_id groups messages into one conversation. Reset it with /new.
    thread_id = str(uuid.uuid4())

    while True:
        try:
            task = input(f"{BOLD}task>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return 0

        if not task:
            continue
        if task in {"/quit", "/q", "/exit"}:
            print("Bye.")
            return 0
        if task == "/new":
            thread_id = str(uuid.uuid4())
            print(f"{DIM}Started a fresh session.{RESET}")
            continue

        config = {"configurable": {"thread_id": thread_id}}
        events = agent.stream(
            {"messages": [{"role": "user", "content": task}]},
            config=config,
            stream_mode="values",
        )
        render_stream(events)
        print()  # blank line between turns


if __name__ == "__main__":
    sys.exit(main())