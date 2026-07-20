"""Phase 0 smoke test. Run this until every check is green.

Checks, in order:
  1. Python version
  2. All Phase 1+ imports (deepagents, GitHub toolkit, chromadb, textual)
  3. Environment variables
  4. GitHub auth + playground repo reachable + issues visible
  5. LLM responds to a one-token ping
  6. create_deep_agent() instantiates

Usage:
    uv run python scripts/smoke_test.py
"""

from __future__ import annotations

import sys

PASS = "  ✓"
FAIL = "  ✗"
failures = 0


def check(label: str, fn):
    global failures
    try:
        detail = fn()
        print(f"{PASS} {label}" + (f"  ({detail})" if detail else ""))
    except Exception as exc:  # noqa: BLE001 - a smoke test should catch everything
        failures += 1
        print(f"{FAIL} {label}: {type(exc).__name__}: {exc}")


# 1. Python version -----------------------------------------------------------
def _python():
    major, minor = sys.version_info[:2]
    assert (major, minor) >= (3, 11), f"need Python 3.11+, got {major}.{minor}"
    return f"{major}.{minor}"


check("Python version", _python)


# 2. Imports ------------------------------------------------------------------
def _imports():
    import warnings

    warnings.filterwarnings("ignore", category=DeprecationWarning)
    import chromadb  # noqa: F401
    import deepagents
    import textual  # noqa: F401
    from langchain_community.agent_toolkits.github.toolkit import GitHubToolkit  # noqa: F401

    return f"deepagents {getattr(deepagents, '__version__', '?')}"


check("Imports (deepagents, github toolkit, chromadb, textual)", _imports)


# 3. Environment --------------------------------------------------------------
def _env():
    from codepilot.core.config import settings

    problems = settings.validate()
    assert not problems, "; ".join(problems)
    return settings.model


check("Environment variables", _env)


# 4. GitHub -------------------------------------------------------------------
def _github():
    from github import Github

    from codepilot.core.config import settings

    gh = Github(settings.github_token)
    login = gh.get_user().login
    repo = gh.get_repo(settings.github_repo)
    issues = list(repo.get_issues(state="open"))
    return f"user={login}, repo={repo.full_name}, open issues={len(issues)}"


check("GitHub auth and playground repo", _github)


# 5. LLM ping -----------------------------------------------------------------
def _llm():
    from langchain.chat_models import init_chat_model

    from codepilot.core.config import settings

    model = init_chat_model(settings.model)
    reply = model.invoke("Reply with exactly one word: pong")
    text = reply.text() if callable(getattr(reply, "text", None)) else str(reply.content)
    assert "pong" in text.lower(), f"unexpected reply: {text!r}"
    return settings.model


check("LLM responds", _llm)


# 6. deepagents agent instantiates -------------------------------------------
def _agent():
    from deepagents import create_deep_agent

    from codepilot.core.config import settings

    agent = create_deep_agent(
        model=settings.model,
        system_prompt="You are a placeholder agent used only for a smoke test.",
    )
    # We don't invoke it (that costs tokens); building the graph is the test.
    assert agent is not None
    return "graph compiled"


check("create_deep_agent() builds", _agent)

print()
if failures:
    print(f"{failures} check(s) failed. Fix the first failure and re-run.")
    sys.exit(1)
print("All green. Phase 0 complete, you're ready for Phase 1.")