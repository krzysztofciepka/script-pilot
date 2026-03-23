from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Select, Switch

from scriptpilot.models import ScriptArg

ARG_TYPES = [("string", "string"), ("boolean", "boolean"), ("integer", "integer")]


class ArgRow(Widget):
    """A single argument definition row."""

    DEFAULT_CSS = """
    ArgRow {
        layout: horizontal;
        height: 3;
        margin-bottom: 1;
    }
    ArgRow Input {
        width: 1fr;
        margin-right: 1;
    }
    ArgRow Select {
        width: 16;
        margin-right: 1;
    }
    ArgRow Switch {
        width: 12;
        margin-right: 1;
    }
    ArgRow Button {
        width: 8;
    }
    """

    def __init__(self, arg: ScriptArg | None = None):
        super().__init__()
        self._arg = arg

    def compose(self) -> ComposeResult:
        yield Input(
            value=self._arg.name if self._arg else "",
            placeholder="Name",
            id="arg-name",
        )
        yield Select(
            ARG_TYPES,
            value=self._arg.type if self._arg else "string",
            id="arg-type",
        )
        yield Label("Req:")
        yield Switch(value=self._arg.required if self._arg else True, id="arg-required")
        yield Input(
            value=str(self._arg.default) if self._arg and self._arg.default is not None else "",
            placeholder="Default",
            id="arg-default",
        )
        yield Button("X", variant="error", id="arg-remove")

    def to_script_arg(self) -> ScriptArg | None:
        """Convert this row to a ScriptArg, or None if name is empty."""
        name = self.query_one("#arg-name", Input).value.strip()
        if not name:
            return None
        arg_type = self.query_one("#arg-type", Select).value
        required = self.query_one("#arg-required", Switch).value
        default_str = self.query_one("#arg-default", Input).value.strip()

        default = None
        if default_str:
            if arg_type == "boolean":
                default = default_str.lower() in ("true", "1", "yes")
            elif arg_type == "integer":
                default = int(default_str) if default_str.isdigit() else None
            else:
                default = default_str

        return ScriptArg(name=name, type=arg_type, required=required, default=default)


class ArgEditor(Widget):
    """Editor for a list of script arguments."""

    DEFAULT_CSS = """
    ArgEditor {
        height: auto;
        padding: 1;
        border: solid $primary;
    }
    ArgEditor #arg-list {
        height: auto;
    }
    ArgEditor #add-arg-btn {
        margin-top: 1;
    }
    """

    def __init__(self, args: list[ScriptArg] | None = None):
        super().__init__()
        self._initial_args = args or []

    def compose(self) -> ComposeResult:
        yield Label("[bold]Arguments[/bold]")
        with Vertical(id="arg-list"):
            for arg in self._initial_args:
                yield ArgRow(arg)
        yield Button("+ Add Argument", id="add-arg-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "add-arg-btn":
            self.query_one("#arg-list", Vertical).mount(ArgRow())
        elif event.button.id == "arg-remove":
            event.button.parent.remove()

    def get_args(self) -> list[ScriptArg]:
        """Collect all valid argument definitions."""
        args = []
        for row in self.query(ArgRow):
            arg = row.to_script_arg()
            if arg:
                args.append(arg)
        return args
