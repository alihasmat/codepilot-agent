"""Relevant-file retrieval, two strategies.

Given a task description, return the top-K files most likely to matter.
The assignment requires two interchangeable strategies:

  keyword   fast, matches task words against file paths + summaries
  embedding slower, semantic similarity over file-content chunks in ChromaDB

Both implement the same retrieve(task, k) interface so the Orchestrator
can pick either one. ChromaDB's default embedder is a local ONNX model
(all-MiniLM-L6-v2), so embedding search needs no API key.
"""

from __future__ import annotations

import re
from pathlib import Path

from codepilot.repo_map import FileEntry


class KeywordRetriever:
    """Score files by overlap between task words and each file's summary."""

    def __init__(self, entries: list[FileEntry]) -> None:
        self.entries = entries

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return set(re.findall(r"[a-z0-9_]+", text.lower()))

    def retrieve(self, task: str, k: int = 10) -> list[tuple[str, float]]:
        task_words = self._tokens(task)
        # Words that appear in almost any coding task carry no signal about
        # WHICH file matters, so we don't let them drive ranking.
        stop = {"add", "fix", "the", "and", "to", "a", "in", "of", "for", "on",
                "type", "hints", "docstrings", "docstring", "update", "change",
                "returns", "return", "code", "function", "functions", "file"}
        signal_words = task_words - stop

        scored: list[tuple[str, float]] = []
        for e in self.entries:
            path_tokens = self._tokens(e.path)
            symbol_tokens = {s.lower() for s in e.symbols}
            desc_tokens = self._tokens(e.description)

            # Strongest signal: a task word that is literally the file's name
            # or an exported symbol. Weakest: incidental description overlap.
            path_hits = sum(3 for w in signal_words if w in path_tokens)
            symbol_hits = sum(4 for w in signal_words if w in symbol_tokens)
            desc_hits = sum(1 for w in signal_words if w in desc_tokens)

            score = path_hits + symbol_hits + desc_hits
            if score > 0:
                scored.append((e.path, float(score)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]


class EmbeddingRetriever:
    """Semantic search over file-content chunks stored in ChromaDB."""

    def __init__(self, entries: list[FileEntry], repo_root: Path, persist_dir: Path) -> None:
        self.entries = entries
        self.repo_root = repo_root
        self.persist_dir = persist_dir
        self._collection = None

    def _ensure_index(self):
        import chromadb

        client = chromadb.PersistentClient(path=str(self.persist_dir))
        collection = client.get_or_create_collection("repo_files")

        # Only index files not already present (keyed by path).
        existing = set(collection.get().get("ids", []))
        docs, ids, metadatas = [], [], []
        for e in self.entries:
            if e.path in existing:
                continue
            abs_path = self.repo_root / e.path
            try:
                content = abs_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            # One chunk per file keeps this simple; large files get truncated.
            # (Chunking per-function is a reasonable later refinement.)
            docs.append(f"{e.path}\n{e.description}\n{content[:2000]}")
            ids.append(e.path)
            metadatas.append({"path": e.path, "language": e.language})
        if docs:
            collection.add(documents=docs, ids=ids, metadatas=metadatas)
        self._collection = collection
        return collection

    def retrieve(self, task: str, k: int = 10) -> list[tuple[str, float]]:
        collection = self._ensure_index()
        n = min(k, max(1, collection.count()))
        result = collection.query(query_texts=[task], n_results=n)
        paths = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        # Convert distance to a similarity-ish score (lower distance = better).
        return [(p, 1.0 / (1.0 + d)) for p, d in zip(paths, distances)]