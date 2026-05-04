from __future__ import annotations

from rich.json import JSON

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static


class JsonViewScreen(ModalScreen[None]):
    """Display parsed JSON via rich.json.JSON."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
    ]

    DEFAULT_CSS = """
    JsonViewScreen {
        align: center middle;
    }
    JsonViewScreen #jv-container {
        width: 80%;
        max-width: 120;
        height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    JsonViewScreen #jv-content {
        height: 1fr;
    }
    """

    def __init__(self, parsed: object):
        super().__init__()
        self._parsed = parsed

    def compose(self) -> ComposeResult:
        with Vertical(id="jv-container"):
            yield Label("[bold]JSON output[/bold] ([dim]q to close[/dim])")
            yield Static(JSON.from_data(self._parsed), id="jv-content")

    def action_close(self):
        self.dismiss(None)
