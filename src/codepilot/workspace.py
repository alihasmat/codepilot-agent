"""Local clone of the target repository.

Real coding agents work against a local checkout, not an API. This
module clones the polled repo into a working directory and exposes the
git primitives Phase 3 needs for cache invalidation: the current commit
SHA, and the set of files changed since a previous SHA.

The clone lives under .codepilot_cache/repo/ (gitignored). We use HTTPS
with the PAT so no SSH setup is needed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from codepilot.config import PROJECT_ROOT, settings

WORKSPACE_ROOT = PROJECT_ROOT / ".codepilot_cache" / "repo"


def _run(args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


class RepoWorkspace:
    """A local git checkout of the target repository."""

    def __init__(self, repo: str | None = None, token: str | None = None) -> None:
        self.repo_name = repo or settings.github_repo
        self._token = token or settings.github_token
        self.path = WORKSPACE_ROOT

    def _clone_url(self) -> str:
        # Embed the PAT for non-interactive HTTPS clone of a public/private repo.
        return f"https://{self._token}@github.com/{self.repo_name}.git"

    def ensure_cloned(self) -> Path:
        """Clone the repo if absent, otherwise pull the latest. Returns the path."""
        if (self.path / ".git").exists():
            _run(["git", "fetch", "--quiet"], cwd=self.path)
            _run(["git", "reset", "--hard", "origin/HEAD"], cwd=self.path)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            _run(["git", "clone", "--quiet", self._clone_url(), str(self.path)])
        return self.path

    def current_sha(self) -> str:
        return _run(["git", "rev-parse", "HEAD"], cwd=self.path)

    def changed_files_since(self, sha: str) -> set[str]:
        """Files that differ between `sha` and the current HEAD.

        Used to invalidate only the affected entries in the Repo Map cache
        rather than rebuilding the whole map on every run.
        """
        try:
            out = _run(["git", "diff", "--name-only", sha, "HEAD"], cwd=self.path)
        except subprocess.CalledProcessError:
            return set()  # unknown sha (e.g. first run); caller rebuilds fully
        return {line for line in out.splitlines() if line}