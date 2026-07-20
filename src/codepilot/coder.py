"""The Coder agent (propose-and-stop).

Given a task and the files retrieval identified, the Coder reads those
files from the sandbox and proposes edits. Crucially, in propose-and-stop
mode it does NOT write anything: it returns a structured proposal (which
file, the full new content, and a rationale). Our code turns that into a
diff for human approval. Nothing touches disk until approved.

We ask the model for strict JSON so the proposal is machine-checkable,
then validate every proposed path against the guardrails before a diff
is even shown.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from langchain.chat_models import init_chat_model

from codepilot.config import settings
from codepilot.guardrails import is_path_allowed

_CODER_SYSTEM = """\
You are the Coder agent in an autonomous coding assistant. You fix issues \
with small, surgical edits.

You will be given a task and the current contents of one or more files. \
Propose the minimal edits that resolve the task. Do not rewrite whole files \
when a few lines suffice, but DO return the complete new content of each file \
you change (not a diff), so the change can be applied deterministically.

Respond with ONLY a JSON object, no prose, no markdown fences, in this shape:
{
  "reasoning": "one or two sentences explaining the fix",
  "edits": [
    {"path": "app/example.py", "new_content": "<full new file content>"}
  ]
}

Rules:
- Only edit files you were shown. Never invent new files unless the task \
explicitly requires creating one.
- Keep changes minimal and focused on the task.
- Preserve existing style, imports, and formatting.
- If you cannot resolve the task from the files shown, return an empty edits \
list and explain why in reasoning.
"""


@dataclass
class FileEdit:
    path: str
    new_content: str


@dataclass
class EditProposal:
    reasoning: str
    edits: list[FileEdit]
    rejected: list[tuple[str, str]]  # (path, reason) for guardrail-blocked edits


def _read_files(sandbox_root: Path, paths: list[str]) -> dict[str, str]:
    contents: dict[str, str] = {}
    for rel in paths:
        abs_path = sandbox_root / rel
        try:
            contents[rel] = abs_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            contents[rel] = ""  # missing file; the model is told it's empty
    return contents


def _build_prompt(task: str, file_contents: dict[str, str]) -> str:
    blocks = []
    for path, content in file_contents.items():
        blocks.append(f"--- FILE: {path} ---\n{content}")
    files_section = "\n\n".join(blocks) if blocks else "(no files provided)"
    return f"TASK:\n{task}\n\nCURRENT FILES:\n{files_section}"


def _extract_json(text: str) -> str:
    """Pull the first balanced {...} object out of a possibly-chatty reply.

    Models sometimes wrap the JSON in prose or fences despite instructions.
    Rather than fail, we find the outermost object by scanning braces.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # strip a ```json ... ``` fence
        inner = cleaned.split("```", 2)
        if len(inner) >= 2:
            cleaned = inner[1]
            if cleaned.lstrip().startswith("json"):
                cleaned = cleaned.lstrip()[4:]
    start = cleaned.find("{")
    if start == -1:
        return cleaned  # let json.loads raise a clear error
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(cleaned)):
        c = cleaned[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
        elif c == '"':
            in_str = not in_str
        elif not in_str:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return cleaned[start : i + 1]
    return cleaned[start:]  # unbalanced; json.loads will report the problem


def _parse_proposal(raw: str) -> tuple[str, list[FileEdit]]:
    data = json.loads(_extract_json(raw))
    reasoning = str(data.get("reasoning", "")).strip()
    edits = [
        FileEdit(path=e["path"], new_content=e["new_content"])
        for e in data.get("edits", [])
        if "path" in e and "new_content" in e
    ]
    return reasoning, edits


def propose_edits(
    task: str,
    target_paths: list[str],
    sandbox_root: Path,
    model: str | None = None,
    skill_block: str | None = None,
) -> EditProposal:
    """Ask the Coder for edits, validate them against guardrails, return a proposal.

    No files are written. Guardrail-blocked edits are moved to `rejected`
    with a reason and never shown as an applicable diff. If a skill_block is
    given (a rendered Skill playbook), it's prepended to the system prompt so
    the Coder follows the task-type-specific rules.
    """
    file_contents = _read_files(sandbox_root, target_paths)
    prompt = _build_prompt(task, file_contents)

    system = _CODER_SYSTEM if not skill_block else f"{skill_block}\n\n{_CODER_SYSTEM}"

    llm = init_chat_model(model or settings.model)
    reply = llm.invoke([
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ])
    raw = reply.text if isinstance(getattr(reply, "text", None), str) else str(reply.content)

    try:
        reasoning, edits = _parse_proposal(raw)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        return EditProposal(
            reasoning=f"Could not parse a valid edit proposal ({exc}).",
            edits=[],
            rejected=[],
        )

    allowed: list[FileEdit] = []
    rejected: list[tuple[str, str]] = []
    for edit in edits:
        ok, reason = is_path_allowed(edit.path)
        if ok:
            allowed.append(edit)
        else:
            rejected.append((edit.path, reason))

    return EditProposal(reasoning=reasoning, edits=allowed, rejected=rejected)