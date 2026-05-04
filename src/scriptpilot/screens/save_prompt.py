from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class SavePromptScreen(ModalScreen[Path | None]):
    """Prompt for a save path. Returns Path on submit, None on cancel."""

    DEFAULT_CSS = """
    SavePromptScreen {
        align: center middle;
    }
    SavePromptScreen #save-container {
        width: 80;
        height: auto;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    SavePromptScreen #save-buttons {
        height: 3;
        align: right middle;
        margin-top: 1;
    }
    SavePromptScreen #save-buttons Button {
        margin-left: 1;
    }
    """

    def __init__(self, default_path: Path):
        super().__init__()
        self._default = default_path

    def compose(self) -> ComposeResult:
        with Vertical(id="save-container"):
            yield Label("[bold]Save output to:[/bold]")
            yield Input(value=str(self._default), id="save-path")
            with Horizontal(id="save-buttons"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Save", id="save-btn", variant="success")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "save-btn":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted):
        self._submit()

    def _submit(self):
        raw = self.query_one("#save-path", Input).value.strip()
        if not raw:
            self.notify("Path is required", severity="error")
            return
        self.dismiss(Path(raw).expanduser())
