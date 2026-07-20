"""Create the playground repo CodePilot will practice on.

Creates a public repo under your account containing a tiny Python
project with three deliberate problems, then files one GitHub issue
per problem, labelled `ai-assignable`. Safe to run once; refuses to
run against a repo that already exists so you can't nuke real work.

Usage:
    uv run python scripts/seed_playground.py
"""

from __future__ import annotations

import sys

from github import Github, GithubException

from codepilot.config import settings

PLAYGROUND_NAME = settings.github_repo.split("/")[-1] if settings.github_repo else "codepilot-playground"

# ---------------------------------------------------------------- seed files

CALCULATOR_PY = '''\
"""A tiny calculator module. One of these functions has a bug."""


def add(a: float, b: float) -> float:
    return a + b


def subtract(a: float, b: float) -> float:
    return a - b


def divide(a: float, b: float) -> float:
    # BUG: should raise on b == 0 and should return a / b
    return a // b


def average(numbers: list[float]) -> float:
    return sum(numbers) / len(numbers)
'''

UTILS_PY = '''\
def slugify(text):
    return text.lower().strip().replace(" ", "-")


def truncate(text, limit):
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def chunk(items, size):
    return [items[i : i + size] for i in range(0, len(items), size)]
'''

TEST_CALCULATOR_PY = '''\
from app.calculator import add, divide, subtract


def test_add():
    assert add(2, 3) == 5


def test_subtract():
    assert subtract(5, 3) == 2


def test_divide():
    assert divide(7, 2) == 3.5


def test_divide_by_zero():
    import pytest

    with pytest.raises(ZeroDivisionError):
        divide(1, 0)
'''

REQUIREMENTS_TXT = "requests==2.25.0\npytest>=8.0\n"

README_MD = (
    "# codepilot-playground\n\n"
    "A deliberately imperfect Python project used as a safe target for the "
    "CodePilot coding agent. Every issue in this repo is fair game for automation.\n"
)

FILES = {
    "README.md": README_MD,
    "requirements.txt": REQUIREMENTS_TXT,
    "app/__init__.py": "",
    "app/calculator.py": CALCULATOR_PY,
    "app/utils.py": UTILS_PY,
    "tests/test_calculator.py": TEST_CALCULATOR_PY,
}

# ------------------------------------------------------------------- issues

LABELS = {
    "ai-assignable": ("1f883d", "Safe for the CodePilot agent to pick up"),
    "bug": ("d73a4a", "Something is broken"),
    "documentation": ("0075ca", "Docs need work"),
    "dependencies": ("8250df", "Dependency upgrade"),
}

ISSUES = [
    {
        "title": "divide() returns wrong results and never raises on zero",
        "body": (
            "`app/calculator.py::divide` uses floor division, so `divide(7, 2)` "
            "returns 3 instead of 3.5. It should perform true division and raise "
            "`ZeroDivisionError` when the divisor is 0.\n\n"
            "The tests in `tests/test_calculator.py` already describe the correct "
            "behaviour and currently fail."
        ),
        "labels": ["ai-assignable", "bug"],
    },
    {
        "title": "Add docstrings and type hints to app/utils.py",
        "body": (
            "`app/utils.py` has three public functions with no docstrings and no "
            "type hints. Add both, matching the style used in `app/calculator.py`."
        ),
        "labels": ["ai-assignable", "documentation"],
    },
    {
        "title": "Bump requests from 2.25.0 to a current release",
        "body": (
            "`requirements.txt` pins `requests==2.25.0`, which is years old. "
            "Update it to a recent stable version and confirm the test suite "
            "still passes."
        ),
        "labels": ["ai-assignable", "dependencies"],
    },
]


def main() -> int:
    problems = settings.validate()
    # LLM key isn't needed for seeding, so only GitHub problems block us.
    blocking = [p for p in problems if "GITHUB" in p or "GITHUB" in p.upper()]
    if blocking:
        for p in blocking:
            print(f"  ✗ {p}")
        return 1

    gh = Github(settings.github_token)
    user = gh.get_user()
    print(f"Authenticated as: {user.login}")

    # If the repo already exists, only proceed when it's empty (safe to seed).
    # This also covers the common case where your token can't CREATE repos, so
    # you made an empty one by hand at github.com/new.
    try:
        repo = user.get_repo(PLAYGROUND_NAME)
        try:
            list(repo.get_contents(""))
            has_content = True
        except GithubException:
            has_content = False  # empty repo raises when listing root
        if has_content:
            # It's fine if the only content is our own seed files (a previous
            # run that died partway, e.g. on a duplicate label). Bail only if
            # there's foreign content we don't recognize.
            root_names = {c.path for c in repo.get_contents("")}
            our_top_level = {"README.md", "requirements.txt", "app", "tests"}
            foreign = root_names - our_top_level
            if foreign:
                print(f"Repo '{PLAYGROUND_NAME}' has unexpected content: {sorted(foreign)}")
                print("Refusing to touch it. Delete it if you want a fresh playground.")
                return 1
            print(f"Resuming partially-seeded repo: {repo.full_name}")
        else:
            print(f"Using existing empty repo: {repo.full_name}")
    except GithubException:
        # Doesn't exist yet, so try to create it. Needs a token with
        # repo-creation rights (fine-grained: Administration = Read & write).
        try:
            repo = user.create_repo(
                PLAYGROUND_NAME,
                description="Practice target for the CodePilot agent (assignment project)",
                private=False,
                auto_init=False,
            )
            print(f"Created repo: {repo.full_name}")
        except GithubException as exc:
            if exc.status == 403:
                print("Your token can't create repositories (403).")
                print(f"Fix: create an EMPTY public repo named '{PLAYGROUND_NAME}' at")
                print("https://github.com/new (no README/license), then re-run this script.")
                return 1
            raise

    for path, content in FILES.items():
        try:
            repo.get_contents(path)
            print(f"  = {path} (already present)")
        except GithubException:
            repo.create_file(path, f"seed: add {path}", content)
            print(f"  + {path}")

    created_labels = 0
    for name, (color, desc) in LABELS.items():
        try:
            repo.create_label(name=name, color=color, description=desc)
            created_labels += 1
        except GithubException as exc:
            if exc.status == 422:  # already exists (GitHub seeds some by default)
                continue
            raise
    print(f"  + {created_labels} label(s) created ({len(LABELS) - created_labels} already existed)")

    existing_titles = {i.title for i in repo.get_issues(state="all")}
    for issue in ISSUES:
        if issue["title"] in existing_titles:
            print(f"  = issue already exists: {issue['title']}")
            continue
        created = repo.create_issue(
            title=issue["title"], body=issue["body"], labels=issue["labels"]
        )
        print(f"  + issue #{created.number}: {created.title}")

    print("\nDone. Set GITHUB_REPO in your .env to:")
    print(f"  GITHUB_REPO={repo.full_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())