from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Switch

from scriptpilot.argv import ArgValidationError, build_argv, validate_and_coerce
from scriptpilot.models import Script, ScriptArg


class RunScreen(ModalScreen[list[str] | None]):
    """Modal for collecting argument values before script execution."""

    DEFAULT_CSS = """
    RunScreen {
        align: center middle;
    }
    RunScreen #run-container {
        width: 60%;
        max-width: 80;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    RunScreen .arg-row {
        height: 3;
        margin-bottom: 1;
    }
    RunScreen .arg-row Label {
        width: 20;
    }
    RunScreen .arg-row Input {
        width: 1fr;
    }
    RunScreen #button-bar {
        height: 3;
        align: right middle;
    }
    RunScreen #button-bar Button {
        margin-left: 1;
    }
    """

    def __init__(self, script: Script):
        super().__init__()
        self._script = script

    def compose(self) -> ComposeResult:
        with Vertical(id="run-container"):
            yield Label(f"[bold]Run: {self._script.name}[/bold]")
            yield Label("")
            if any(a.type == "path" for a in self._script.args):
                yield Label(
                    "[dim]relative paths resolve against cwd[/dim]",
                    id="path-hint",
                )
            for i, arg in enumerate(self._script.args):
                req = "*" if arg.required else ""
                with Horizontal(classes="arg-row"):
                    yield Label(f"{arg.name}{req}:")
                    if arg.type == "boolean":
                        default_val = bool(arg.default) if arg.default is not None else False
                        yield Switch(value=default_val, id=f"arg-{i}")
                    elif arg.type == "choice":
                        options = [(c, c) for c in (arg.choices or [])]
                        if arg.default is not None:
                            initial = arg.default
                        elif arg.required and arg.choices:
                            initial = arg.choices[0]
                        else:
                            initial = Select.BLANK
                        yield Select(
                            options,
                            value=initial,
                            allow_blank=not arg.required,
                            id=f"arg-{i}",
                        )
                    else:
                        default_str = str(arg.default) if arg.default is not None else ""
                        placeholder = "path" if arg.type == "path" else arg.type
                        yield Input(
                            value=default_str,
                            placeholder=placeholder,
                            id=f"arg-{i}",
                        )
            with Horizontal(id="button-bar"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Run", id="run-btn", variant="success")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "run-btn":
            self._collect_and_run()

    def _collect_and_run(self):
        raw_values: list[str | bool] = []
        for i, arg in enumerate(self._script.args):
            widget_id = f"arg-{i}"
            if arg.type == "boolean":
                raw_values.append(self.query_one(f"#{widget_id}", Switch).value)
            elif arg.type == "choice":
                v = self.query_one(f"#{widget_id}", Select).value
                raw_values.append("" if v is Select.BLANK else v)
            else:
                raw_values.append(
                    self.query_one(f"#{widget_id}", Input).value.strip()
                )

        validated: list[str | bool] = []
        for i, (arg, raw) in enumerate(zip(self._script.args, raw_values)):
            try:
                validated.append(validate_and_coerce(arg, raw))
            except ArgValidationError as e:
                self.notify(e.message, severity="error")
                self.query_one(f"#arg-{i}").focus()
                return

        argv = build_argv(self._script, validated)
        self.dismiss(argv)
