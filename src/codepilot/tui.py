"""CodePilot TUI (Phase 9).

A Textual app that wraps the whole pipeline in four panels:
  - Issues: eligible GitHub issues; select one to work it
  - Agent Log: streaming progress from the running pipeline
  - Status: per-issue state and outcomes
  - Approval modal: pops up for the fix and each HITL gate

The pipeline is blocking (LLM, git, pytest), so it runs on a worker
thread via @work(thread=True). The worker talks to the UI through
call_from_thread, and gate approvals block the worker on a threading
Event that the modal sets. This is why the TUI came last: it's a skin
over the proven run_pipeline() function, not new logic.

Run:
    uv run python scripts/run_tui.py
"""

from __future__ import annotations

import threading

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Label, ListItem, ListView, RichLog, Static

from codepilot.config import settings
from codepilot.github_client import GitHubClient, IssueSummary
from codepilot.pipeline import run_pipeline
from codepilot.repo_map import build_repo_map
from codepilot.retrieval import KeywordRetriever
from codepilot.workspace import RepoWorkspace


class ApprovalModal(ModalScreen[bool]):
    """Blocking yes/no approval. Returns True/False to the worker."""

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self.prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="approval-box"):
            yield Static(self.prompt[:2000], id="approval-text")
            with Horizontal(id="approval-buttons"):
                yield Button("Approve (y)", variant="success", id="yes")
                yield Button("Reject (n)", variant="error", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def on_key(self, event) -> None:
        if event.key == "y":
            self.dismiss(True)
        elif event.key == "n":
            self.dismiss(False)


class CodePilotApp(App):
    CSS = """
    #main { height: 1fr; }
    #left { width: 40%; border: round $primary; }
    #right { width: 60%; border: round $accent; }
    #status { height: 8; border: round $warning; }
    #approval-box { width: 80%; height: auto; max-height: 80%; border: thick $primary;
                    background: $surface; padding: 1 2; }
    #approval-buttons { height: auto; align: center middle; margin-top: 1; }
    Button { margin: 0 1; }
    ListView { height: 1fr; }
    """
    BINDINGS = [("q", "quit", "Quit"), ("r", "refresh", "Refresh issues")]

    def __init__(self) -> None:
        super().__init__()
        self.gh = GitHubClient()
        self.workspace = RepoWorkspace()
        self.retriever: KeywordRetriever | None = None
        self.issues: list[IssueSummary] = []
        self._approval_result: bool = False
        self._approval_event = threading.Event()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Label("Eligible Issues (Enter to work)")
                yield ListView(id="issues")
            with Vertical(id="right"):
                yield Label("Agent Log")
                yield RichLog(id="log", highlight=True, markup=True, wrap=True)
        yield Static("Status: initializing...", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "CodePilot"
        self.sub_title = self.gh.repo_name
        self.prepare()

    @work(thread=True)
    def prepare(self) -> None:
        """One-time repo prep + issue load, off the UI thread."""
        self.call_from_thread(self._set_status, "Cloning repo and building map...")
        repo_map = build_repo_map(self.workspace, settings.repo_map_token_budget)
        self.retriever = KeywordRetriever(repo_map.entries)
        self.issues = self.gh.list_issues()
        self.call_from_thread(self._populate_issues)
        self.call_from_thread(self._set_status, f"Ready. {len(self.issues)} eligible issue(s).")

    def _populate_issues(self) -> None:
        lv = self.query_one("#issues", ListView)
        lv.clear()
        for issue in self.issues:
            lv.append(ListItem(Label(f"#{issue.number}  {issue.title}")))

    def _set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(f"Status: {text}")

    def _log(self, msg: str) -> None:
        self.query_one("#log", RichLog).write(msg)

    def action_refresh(self) -> None:
        self.prepare()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is None or idx >= len(self.issues):
            return
        issue = self.issues[idx]
        self._log(f"[bold cyan]Working issue #{issue.number}: {issue.title}[/]")
        self.work_issue(issue)

    # ---- approval bridge: worker thread <-> UI modal ----
    def _ask_approval(self, prompt: str) -> bool:
        """Called FROM the worker thread. Blocks until the modal answers."""
        self._approval_event.clear()

        def show() -> None:
            def done(result: bool) -> None:
                self._approval_result = bool(result)
                self._approval_event.set()
            self.push_screen(ApprovalModal(prompt), done)

        self.call_from_thread(show)
        self._approval_event.wait()
        return self._approval_result

    @work(thread=True)
    def work_issue(self, issue: IssueSummary) -> None:
        if self.retriever is None:
            self.call_from_thread(self._log, "Not ready yet; still preparing.")
            return
        self.call_from_thread(self._set_status, f"Working issue #{issue.number}...")
        outcome = run_pipeline(
            issue, self.workspace, self.gh, self.retriever,
            log=lambda m: self.call_from_thread(self._log, m),
            approve=self._ask_approval,
        )
        status = outcome.pr_url or outcome.message
        self.call_from_thread(self._set_status, f"Issue #{issue.number}: {status}")
        if outcome.pr_url:
            self.call_from_thread(self._log, f"[bold green]Done: {outcome.pr_url}[/]")


def main() -> int:
    problems = settings.validate()
    if problems:
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    CodePilotApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())