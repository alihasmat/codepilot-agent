"""Phase 2 driver: on-demand issue polling.

Instead of blocking on a 5-minute timer, you drive the loop yourself:

    poll   fetch eligible issues, classify + plan each new one
    status show in-progress and completed tasks
    free   type a free-form coding task (not tied to an issue)
    quit

The timer-based polling the assignment describes is a thin wrapper over
poll here; on-demand is far nicer to develop and demo against, and we
keep the timer option available for the final submission.

Usage:
    uv run python scripts/run_loop.py
"""

from __future__ import annotations

import sys

from codepilot.config import settings
from codepilot.orchestrator_loop import Orchestrator
from codepilot.streaming import BOLD, DIM, RESET, render_stream

BANNER = f"""{BOLD}CodePilot — Phase 2 (on-demand polling + triage){RESET}
{DIM}Commands: poll | status | free | quit{RESET}
"""


def main() -> int:
    problems = settings.validate()
    if problems:
        print("Config problems, fix these first:")
        for p in problems:
            print(f"  ✗ {p}")
        return 1

    orch = Orchestrator()
    print(BANNER)

    while True:
        try:
            cmd = input(f"{BOLD}codepilot>{RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return 0

        if cmd in {"quit", "q", "exit"}:
            print("Bye.")
            return 0
        elif cmd in {"poll", "p", ""}:
            orch.process_new_issues()
        elif cmd in {"status", "s"}:
            orch.status()
        elif cmd in {"free", "f"}:
            task_text = input("Describe the task: ").strip()
            if task_text:
                config = {"configurable": {"thread_id": "free-form"}}
                events = orch.agent.stream(
                    {"messages": [{"role": "user", "content": task_text}]},
                    config=config,
                    stream_mode="values",
                )
                render_stream(events)
        else:
            print(f"{DIM}Unknown command. Try: poll | status | free | quit{RESET}")
        print()


if __name__ == "__main__":
    sys.exit(main())