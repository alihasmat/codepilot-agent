"""Central configuration for CodePilot.

Everything the app needs from the environment is read here, once,
so no other module ever calls os.getenv directly. That gives us a
single place to validate settings and fail loudly at startup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root, wherever we're run from.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    # LLM. deepagents accepts a LangChain model string like
    # "anthropic:claude-sonnet-4-5" or "openai:gpt-4o".
    model: str = field(default_factory=lambda: os.getenv("CODEPILOT_MODEL", "anthropic:claude-sonnet-4-5"))

    # GitHub
    github_token: str = field(default_factory=lambda: os.getenv("GITHUB_TOKEN", ""))
    github_repo: str = field(default_factory=lambda: os.getenv("GITHUB_REPO", ""))  # "youruser/codepilot-playground"

    # Behaviour knobs used in later phases (defined now so config is stable)
    poll_interval_minutes: int = field(default_factory=lambda: int(os.getenv("POLL_INTERVAL_MINUTES", "5")))
    repo_map_token_budget: int = field(default_factory=lambda: int(os.getenv("REPO_MAP_TOKEN_BUDGET", "4000")))
    max_coder_retries: int = 3

    def validate(self) -> list[str]:
        """Return a list of human-readable problems. Empty list means healthy."""
        problems: list[str] = []
        provider = self.model.split(":", 1)[0]
        key_env = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "google_genai": "GOOGLE_API_KEY",
        }.get(provider)
        if key_env is None:
            problems.append(f"Unknown model provider '{provider}' in CODEPILOT_MODEL")
        elif not os.getenv(key_env):
            problems.append(f"{key_env} is not set (required by model '{self.model}')")
        if not self.github_token:
            problems.append("GITHUB_TOKEN is not set")
        if not self.github_repo or "/" not in self.github_repo:
            problems.append("GITHUB_REPO must look like 'owner/repo'")
        return problems


settings = Settings()