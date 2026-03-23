from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, TextArea

from scriptpilot.models import Script, ScriptArg
from scriptpilot.widgets.arg_editor import ArgEditor

SCRIPT_TYPES = [("Bash", "bash"), ("Python", "python"), ("JavaScript", "js")]

TEXTUAL_LANGUAGES = {"bash": "bash", "python": "python", "js": "javascript"}


class ScriptSaved(Message):
    """Posted when a script is saved."""

    def __init__(self, script: Script):
        super().__init__()
        self.script = script


class EditScreen(ModalScreen[Script | None]):
    """Modal screen for creating or editing a script."""

    DEFAULT_CSS = """
    EditScreen {
        align: center middle;
    }
    EditScreen #edit-container {
        width: 80%;
        max-width: 100;
        height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    EditScreen Input {
        margin-bottom: 1;
    }
    EditScreen Select {
        margin-bottom: 1;
    }
    EditScreen TextArea {
        height: 1fr;
        margin-bottom: 1;
    }
    EditScreen #button-bar {
        height: 3;
        align: right middle;
    }
    EditScreen #button-bar Button {
        margin-left: 1;
    }
    """

    def __init__(self, script: Script | None = None):
        super().__init__()
        self._script = script

    def compose(self) -> ComposeResult:
        s = self._script
        title = "Edit Script" if s else "New Script"
        with Vertical(id="edit-container"):
            yield Label(f"[bold]{title}[/bold]")
            yield Label("Name:")
            yield Input(value=s.name if s else "", id="name-input")
            yield Label("Description:")
            yield Input(value=s.description if s else "", id="desc-input")
            yield Label("Type:")
            yield Select(
                SCRIPT_TYPES,
                value=s.type if s else "bash",
                id="type-select",
            )
            yield Label("Timeout (seconds):")
            yield Input(
                value=str(s.timeout) if s else "60",
                id="timeout-input",
            )
            yield Label("Script Content:")
            lang = TEXTUAL_LANGUAGES.get(s.type, "python") if s else "bash"
            yield TextArea(
                s.content if s else "",
                id="content-area",
                language=lang,
            )
            yield ArgEditor(s.args if s else [])
            with Horizontal(id="button-bar"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Save", id="save-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "save-btn":
            self._save()

    def _save(self):
        name = self.query_one("#name-input", Input).value.strip()
        desc = self.query_one("#desc-input", Input).value.strip()
        script_type = self.query_one("#type-select", Select).value
        content = self.query_one("#content-area", TextArea).text
        timeout_str = self.query_one("#timeout-input", Input).value.strip()
        args = self.query_one(ArgEditor).get_args()

        if not name:
            self.notify("Script name is required", severity="error")
            return
        if not content.strip():
            self.notify("Script content is required", severity="error")
            return

        try:
            timeout = int(timeout_str)
        except ValueError:
            timeout = 60

        if self._script:
            self._script.name = name
            self._script.description = desc
            self._script.type = script_type
            self._script.content = content
            self._script.timeout = timeout
            self._script.args = args
            self.dismiss(self._script)
        else:
            script = Script(
                name=name,
                description=desc,
                type=script_type,
                content=content,
                timeout=timeout,
                args=args,
            )
            self.dismiss(script)
