from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import MarkdownViewer

from scriptpilot.help import load_help_markdown


class HelpScreen(ModalScreen[None]):
    """Modal man-page: prose chapters + auto-generated shortcuts reference."""

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    HelpScreen #help-container {
        width: 90%;
        max-width: 140;
        height: 90%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    HelpScreen MarkdownViewer {
        height: 1fr;
    }
    """

    # "?" is captured here on purpose: the App-level binding opens this
    # screen, and ModalScreen bindings take priority once it's focused, so
    # pressing "?" again closes the modal instead of stacking a new one.
    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("?", "close", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-container"):
            yield MarkdownViewer(
                markdown=load_help_markdown(),
                show_table_of_contents=True,
            )

    def action_close(self) -> None:
        self.dismiss(None)
