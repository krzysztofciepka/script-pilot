from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView

from scriptpilot.history import format_history_row
from scriptpilot.models import RunRecord


class HistoryScreen(ModalScreen[RunRecord | None]):
    """Modal listing recent RunRecords across all scripts."""

    DEFAULT_CSS = """
    HistoryScreen {
        align: center middle;
    }
    HistoryScreen #history-container {
        width: 80%;
        max-width: 120;
        height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    HistoryScreen ListView {
        height: 1fr;
    }
    """

    BINDINGS = [("escape", "dismiss_none", "Close")]

    def __init__(self, records: list[RunRecord]):
        super().__init__()
        self._records = records

    def compose(self) -> ComposeResult:
        with Vertical(id="history-container"):
            yield Label("[bold]Run history[/bold]  [dim](Enter to open, Esc to close)[/dim]")
            with ListView():
                for i, r in enumerate(self._records):
                    yield ListItem(Label(format_history_row(r)), name=str(i))

    def action_dismiss_none(self):
        self.dismiss(None)

    def on_list_view_selected(self, event: ListView.Selected):
        idx = int(event.item.name)
        self.dismiss(self._records[idx])
