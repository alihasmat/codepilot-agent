"""Semantic memory: lessons learned, retrieved by relevance.

The richest memory tier. After a task succeeds (and, from Phase 8, after a
PR merges), CodePilot asks the LLM to distill a short, general lesson from
what happened, for example "docstrings in this repo are concise
one-liners". Lessons are embedded into ChromaDB so future tasks can pull
the most relevant ones and feed them to the Coder, letting the system
improve over time.

ChromaDB's local ONNX embedder means no API key is needed for retrieval.
The persistent directory keeps lessons across runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from langchain.chat_models import init_chat_model

from codepilot.core.config import PROJECT_ROOT, settings

LESSONS_DIR = PROJECT_ROOT / ".codepilot_cache" / "lessons_chroma"

_LESSON_PROMPT = """\
A coding task just completed successfully. Distill ONE short, general, \
reusable lesson a future coding agent working on THIS repository would \
benefit from. Focus on repo-specific conventions or gotchas, not generic \
advice. One sentence, no preamble.

Task type: {task_type}
Issue: {title}
What was done: {summary}
Diff:
{diff}
"""


@dataclass
class Lesson:
    text: str
    task_type: str
    issue_number: int


class SemanticMemory:
    def __init__(self, persist_dir: Path = LESSONS_DIR) -> None:
        self.persist_dir = persist_dir
        self._collection = None

    def _col(self):
        if self._collection is None:
            import chromadb

            client = chromadb.PersistentClient(path=str(self.persist_dir))
            self._collection = client.get_or_create_collection("lessons")
        return self._collection

    def extract_and_store(
        self,
        *,
        task_type: str,
        title: str,
        summary: str,
        diff: str,
        issue_number: int,
        model: str | None = None,
    ) -> Lesson | None:
        """Ask the LLM for a lesson and store it. Returns the Lesson or None."""
        llm = init_chat_model(model or settings.model)
        prompt = _LESSON_PROMPT.format(
            task_type=task_type, title=title, summary=summary, diff=diff[:1500]
        )
        reply = llm.invoke(prompt)
        text = (reply.text if isinstance(getattr(reply, "text", None), str)
                else str(reply.content)).strip()
        if not text:
            return None

        lesson = Lesson(text=text, task_type=task_type, issue_number=issue_number)
        self._col().add(
            documents=[text],
            ids=[f"issue-{issue_number}"],
            metadatas=[{"task_type": task_type, "issue_number": issue_number}],
        )
        return lesson

    def retrieve(self, task_text: str, k: int = 3) -> list[str]:
        """Return the k most relevant lesson texts for a task, or [] if none."""
        col = self._col()
        count = col.count()
        if count == 0:
            return []
        res = col.query(query_texts=[task_text], n_results=min(k, count))
        docs = res.get("documents", [[]])[0]
        return docs