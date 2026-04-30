from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Button, Input, Label


class EnvRow(Widget):
    """A single environment-variable row: KEY + VALUE + remove button."""

    DEFAULT_CSS = """
    EnvRow {
        layout: horizontal;
        height: 3;
        margin-bottom: 1;
    }
    EnvRow Input {
        width: 1fr;
        margin-right: 1;
    }
    EnvRow Button {
        width: 8;
    }
    """

    def __init__(self, key: str = "", value: str = ""):
        super().__init__()
        self._key = key
        self._value = value

    def compose(self) -> ComposeResult:
        yield Input(value=self._key, placeholder="KEY", id="env-key")
        yield Input(value=self._value, placeholder="VALUE", id="env-value")
        yield Button("X", variant="error", id="env-remove")

    def to_pair(self) -> tuple[str, str] | None:
        """Return (key, value), or None if the key is empty."""
        key = self.query_one("#env-key", Input).value.strip()
        if not key:
            return None
        value = self.query_one("#env-value", Input).value
        return key, value


class EnvEditor(Widget):
    """Editor for a dict of script environment variables."""

    DEFAULT_CSS = """
    EnvEditor {
        height: auto;
        padding: 1;
        border: solid $primary;
        margin-top: 1;
    }
    EnvEditor #env-list {
        height: auto;
    }
    EnvEditor #add-env-btn {
        margin-top: 1;
    }
    """

    def __init__(self, env: dict[str, str] | None = None):
        super().__init__()
        self._initial = list((env or {}).items())

    def compose(self) -> ComposeResult:
        yield Label("[bold]Environment Variables[/bold]")
        yield Label(
            "[dim]Non-secret per-script overrides. "
            "Real secrets belong in ~/.scriptpilot/.env[/dim]"
        )
        with Vertical(id="env-list"):
            for k, v in self._initial:
                yield EnvRow(k, v)
        yield Button("+ Add Env Var", id="add-env-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "add-env-btn":
            self.query_one("#env-list", Vertical).mount(EnvRow())
        elif event.button.id == "env-remove":
            event.button.parent.remove()

    def get_env(self) -> dict[str, str]:
        """Collect all rows with a non-empty key into a dict."""
        out: dict[str, str] = {}
        for row in self.query(EnvRow):
            pair = row.to_pair()
            if pair:
                out[pair[0]] = pair[1]
        return out
