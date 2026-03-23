from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, RichLog, Static

from scriptpilot.models import Script


class MainPanel(Widget):
    """Right panel showing script details or execution output."""

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

    def compose(self) -> ComposeResult:
        yield Label(
            "No scripts yet. Press [n] to create one or [g] to generate with AI.",
            id="welcome",
        )
        yield Static(id="details")
        yield RichLog(id="output-log", max_lines=10000, wrap=True)
        yield Static(id="status-bar")

    def on_mount(self):
        self._show_welcome()

    def _show_welcome(self):
        self.query_one("#welcome").display = True
        self.query_one("#details").display = False
        self.query_one("#output-log").display = False
        self.query_one("#status-bar").display = False

    def show_script_details(self, script: Script):
        """Display script metadata."""
        self.query_one("#welcome").display = False
        self.query_one("#output-log").display = False
        self.query_one("#status-bar").display = False

        details = self.query_one("#details", Static)
        args_text = ", ".join(a.name for a in script.args) if script.args else "none"
        details.update(
            f"[bold]{script.name}[/bold]\n"
            f"{script.description}\n\n"
            f"Type: {script.type}  |  Timeout: {script.timeout}s  |  Args: {args_text}"
        )
        details.display = True

    def show_running(self, script: Script):
        """Switch to execution output mode."""
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

    def append_output(self, line: str):
        """Add a line to the output log."""
        log = self.query_one("#output-log", RichLog)
        log.write(line)

    def show_finished(self, exit_code: int, duration: float, timed_out: bool):
        """Show completion status."""
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
