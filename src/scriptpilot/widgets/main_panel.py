from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from rich.markup import escape
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, RichLog, Static

from scriptpilot import clipboard
from scriptpilot.clipboard import ClipboardUnavailable
from scriptpilot.models import OutputLine, RunRecord, Script
from scriptpilot.screens.json_view import JsonViewScreen
from scriptpilot.screens.save_prompt import SavePromptScreen


def _try_parse_json(stdout: str) -> object | None:
    """Try to parse stdout as JSON.

    First attempt: the whole string (handles pretty-printed multi-line).
    Second attempt: the last non-empty line (handles status-line-then-JSON).
    Returns the parsed value or None.
    """
    if not stdout.strip():
        return None
    candidates = [stdout]
    last = _last_nonempty_line(stdout)
    if last and last != stdout:
        candidates.append(last)
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _last_nonempty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line
    return ""


def _safe_name(name: str) -> str:
    """Filesystem-safe filename stem; falls back to 'output' if empty."""
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-")
    return cleaned or "output"


def _ts_filename() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")


class MainPanel(Widget):
    """Right panel showing script details or execution output."""

    BINDINGS = [
        ("o", "save_output", "Save"),
        ("y", "copy_output", "Copy"),
        ("J", "view_json", "JSON"),
    ]

    DEFAULT_CSS = """
    MainPanel {
        height: 1fr;
        padding: 1 2;
    }
    MainPanel #welcome {
        content-align: center middle;
        height: 1fr;
    }
    MainPanel #details {
        height: auto;
    }
    MainPanel #output-log {
        height: 1fr;
        border: solid $primary;
        margin-top: 1;
    }
    MainPanel #status-bar {
        height: 1;
        dock: bottom;
    }
    """

    def __init__(self):
        super().__init__()
        self._displayed_run: RunRecord | None = None
        self._is_running: bool = False

    def compose(self) -> ComposeResult:
        yield Label(
            "No scripts yet. Press \\[n] to create one or \\[g] to generate with AI.",
            id="welcome",
        )
        yield Static(id="details")
        yield RichLog(id="output-log", max_lines=10000, wrap=True, markup=True)
        yield Static(id="status-bar")

    def on_mount(self):
        self._show_welcome()

    def _show_welcome(self):
        self.query_one("#welcome").display = True
        self.query_one("#details").display = False
        self.query_one("#output-log").display = False
        self.query_one("#status-bar").display = False

    def show_script_details(self, script: Script, last_run: RunRecord | None = None):
        """Display script metadata (header). Called on selection."""
        self.query_one("#welcome").display = False
        self.query_one("#output-log").display = False
        self.query_one("#status-bar").display = False
        self._displayed_run = None
        self._is_running = False

        details = self.query_one("#details", Static)
        args_text = ", ".join(a.name for a in script.args) if script.args else "none"
        text = (
            f"[bold]{script.name}[/bold]\n"
            f"{script.description}\n\n"
            f"Type: {script.type}  |  Timeout: {script.timeout}s  |  Args: {args_text}"
        )
        if last_run:
            text += (
                f"\n\n[dim]Last run: {last_run.timestamp}  |  "
                f"Exit: {last_run.exit_code}  |  "
                f"Duration: {last_run.duration:.1f}s[/dim]"
            )
        details.update(text)
        details.display = True

    def show_running(self, script: Script):
        """Switch to live execution output mode."""
        self.query_one("#welcome").display = False
        details = self.query_one("#details", Static)
        details.update(f"[bold]Running:[/bold] {script.name}")
        details.display = True

        log = self.query_one("#output-log", RichLog)
        log.clear()
        log.display = True

        status = self.query_one("#status-bar", Static)
        status.update("[yellow]Running...[/yellow]")
        status.display = True

        self._displayed_run = None
        self._is_running = True

    def append_output(self, line: OutputLine):
        """Add a single line to the output log, styled by stream."""
        log = self.query_one("#output-log", RichLog)
        text = escape(line.line)
        if line.stream == "stderr":
            log.write(f"[red]{text}[/red]")
        else:
            log.write(text)

    def show_finished_run(self, run: RunRecord):
        """Render a finished run (just-finished or selected from history)."""
        self.query_one("#welcome").display = False
        self._displayed_run = run
        self._is_running = False

        log = self.query_one("#output-log", RichLog)
        log.clear()
        for line in run.lines:
            self.append_output(line)
        log.display = True

        status = self.query_one("#status-bar", Static)
        if run.cancelled:
            status.update(
                f"[yellow]Cancelled by user[/yellow]  Duration: {run.duration:.1f}s"
            )
        elif run.timed_out:
            status.update(f"[red]Timed out after {run.duration:.1f}s[/red]")
        elif run.exit_code == 0:
            status.update(
                f"[green]Exit code: {run.exit_code}[/green]  "
                f"Duration: {run.duration:.1f}s"
            )
        else:
            status.update(
                f"[red]Exit code: {run.exit_code}[/red]  "
                f"Duration: {run.duration:.1f}s"
            )
        status.display = True

    def show_finished(self, exit_code: int, duration: float, timed_out: bool):
        """Update status bar after a live run completes (legacy entry-point)."""
        status = self.query_one("#status-bar", Static)
        if timed_out:
            status.update(f"[red]Timed out after {duration:.1f}s[/red]")
        elif exit_code == 0:
            status.update(
                f"[green]Exit code: {exit_code}[/green]  Duration: {duration:.1f}s"
            )
        else:
            status.update(
                f"[red]Exit code: {exit_code}[/red]  Duration: {duration:.1f}s"
            )

    def show_error(self, message: str):
        """Show an error in the output area."""
        self.query_one("#welcome").display = False
        details = self.query_one("#details", Static)
        details.update(f"[red]{message}[/red]")
        details.display = True

    # -------- bindings --------

    def action_save_output(self):
        if self._displayed_run is None or self._is_running:
            return
        run = self._displayed_run
        default_path = (
            Path.home() / ".scriptpilot" / "outputs"
            / f"{_safe_name(run.script_name)}-{_ts_filename()}.txt"
        )

        def on_path(path: Path | None):
            if path is None:
                return
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(run.combined_text())
            except OSError as e:
                self.notify(str(e), severity="error")
                return
            self.notify(f"Saved to {path}")

        self.app.push_screen(SavePromptScreen(default_path), callback=on_path)

    def action_copy_output(self):
        if self._displayed_run is None or self._is_running:
            return
        try:
            clipboard.copy(self._displayed_run.combined_text())
            self.notify("Copied")
        except ClipboardUnavailable as e:
            self.notify(str(e), severity="warning")

    def action_view_json(self):
        if self._displayed_run is None or self._is_running:
            return
        text = self._displayed_run.stdout_text().strip()
        if not text:
            self.notify("No stdout to parse", severity="warning")
            return
        parsed = _try_parse_json(text)
        if parsed is None:
            self.notify("Output is not JSON", severity="warning")
            return
        self.app.push_screen(JsonViewScreen(parsed))
