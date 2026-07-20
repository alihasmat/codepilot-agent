"""Episodic memory: a persistent record of past task sessions.

After each task finishes, CodePilot writes a short episode: which issue,
what type, which files, the approach, and the outcome. On future tasks it
can recall "last time I touched utils.py, here's what happened."

Stored as a JSON file under .codepilot_cache so it's transparent and
survives across runs. For a portfolio project a readable JSON log is
clearer than a database, and recall is a simple filter over recent
episodes rather than a similarity search (that's semantic memory's job).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from codepilot.core.config import PROJECT_ROOT

EPISODES_PATH = PROJECT_ROOT / ".codepilot_cache" / "episodes.json"


@dataclass
class Episode:
    issue_number: int
    title: str
    task_type: str
    files: list[str]
    outcome: str  # "success" | "failed"
    summary: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EpisodicMemory:
    def __init__(self, path: Path = EPISODES_PATH) -> None:
        self.path = path
        self._episodes: list[Episode] = self._load()

    def _load(self) -> list[Episode]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text())
            return [Episode(**e) for e in data]
        except (json.JSONDecodeError, TypeError):
            return []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([asdict(e) for e in self._episodes], indent=2))

    def record(self, episode: Episode) -> None:
        self._episodes.append(episode)
        self._save()

    def recall_for_files(self, files: list[str], limit: int = 3) -> list[Episode]:
        """Most recent episodes that touched any of the given files."""
        fileset = set(files)
        hits = [e for e in reversed(self._episodes) if fileset & set(e.files)]
        return hits[:limit]

    def recall_for_type(self, task_type: str, limit: int = 3) -> list[Episode]:
        hits = [e for e in reversed(self._episodes) if e.task_type == task_type]
        return hits[:limit]

    def all(self) -> list[Episode]:
        return list(self._episodes)