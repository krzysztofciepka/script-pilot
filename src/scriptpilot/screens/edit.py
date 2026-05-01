from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll, Horizontal
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RichLog, Select, TextArea

from scriptpilot.models import Script, ScriptArg
from scriptpilot.widgets.arg_editor import ArgEditor
from scriptpilot.widgets.env_editor import EnvEditor
from scriptpilot.editor import edit_file, EditorError
from scriptpilot.tempscript import materialize_draft
from scriptpilot.executor import execute_script, InterpreterNotFoundError, ScriptCwdError
from scriptpilot.screens.run import RunScreen

SCRIPT_TYPES = [("Bash", "bash"), ("Python", "python"), ("JavaScript", "js")]

TEXTUAL_LANGUAGES = {"bash": "bash", "python": "python", "js": "javascript"}


class ScriptSaved(Message):
    """Posted when a script is saved."""

    def __init__(self, script: Script):
        super().__init__()
        self.script = script


class EditScreen(ModalScreen[Script | None]):
    """Modal screen for creating or editing a script."""

    BINDINGS = [
        ("E", "edit_in_external", "Editor"),
    ]

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
    EditScreen #edit-scroll {
        height: 1fr;
    }
    EditScreen Input {
        margin-bottom: 1;
    }
    EditScreen Select {
        margin-bottom: 1;
    }
    EditScreen #content-area {
        min-height: 10;
        height: 1fr;
        margin-bottom: 1;
    }
    EditScreen #scratch-output {
        display: none;
        height: 8;
        border: solid $accent;
        margin-bottom: 1;
    }
    EditScreen #scratch-output.visible {
        display: block;
    }
    EditScreen .editor-hint {
        color: $text-muted;
        margin-bottom: 1;
    }
    EditScreen #button-bar {
        height: 3;
        align: right middle;
        dock: bottom;
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
            with VerticalScroll(id="edit-scroll"):
                yield Label(f"[bold]{title}[/bold]")
                yield Label("Name:")
                yield Input(value=s.name if s else "", id="name-input")
                yield Label("Description:")
                yield Input(value=s.description if s else "", id="desc-input")
                yield Label("Type:")
                yield Select(
                    SCRIPT_TYPES,
                    value=s.type if s else "bash",
                    allow_blank=False,
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
                yield Label("[dim]Press E to edit in $EDITOR[/dim]", classes="editor-hint")
                yield RichLog(id="scratch-output", highlight=True, markup=True)
                yield Label("Working Directory:")
                yield Input(
                    value=s.cwd if (s and s.cwd) else "",
                    placeholder="~ (default: home)",
                    id="cwd-input",
                )
                yield ArgEditor(s.args if s else [])
                yield EnvEditor(s.env if s else {})
            with Horizontal(id="button-bar"):
                yield Button("Run", id="run-btn")
                yield Button("Cancel", id="cancel-btn")
                yield Button("Save", id="save-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "save-btn":
            self._save()
        elif event.button.id == "run-btn":
            self._scratch_run()

    def action_edit_in_external(self):
        text_area = self.query_one("#content-area", TextArea)
        type_select = self.query_one("#type-select", Select)
        script_type = type_select.value
        tmp = materialize_draft(text_area.text, script_type)
        try:
            edit_file(self.app, self.app._config, tmp)
            text_area.load_text(tmp.read_text())
        except EditorError as e:
            self.notify(str(e), severity="error")
        finally:
            tmp.unlink(missing_ok=True)

    def _collect_form(self) -> Script | None:
        """Read the form into a Script. Returns None if validation fails (already notified)."""
        name = self.query_one("#name-input", Input).value.strip()
        desc = self.query_one("#desc-input", Input).value.strip()
        script_type = self.query_one("#type-select", Select).value
        content = self.query_one("#content-area", TextArea).text
        timeout_str = self.query_one("#timeout-input", Input).value.strip()
        args = self.query_one(ArgEditor).get_args()
        cwd_str = self.query_one("#cwd-input", Input).value.strip() or None
        env = self.query_one(EnvEditor).get_env()

        if not name:
            self.notify("Script name is required", severity="error")
            return None
        if not content.strip():
            self.notify("Script content is required", severity="error")
            return None

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
            self._script.cwd = cwd_str
            self._script.env = env
            return self._script

        return Script(
            name=name,
            description=desc,
            type=script_type,
            content=content,
            timeout=timeout,
            args=args,
            cwd=cwd_str,
            env=env,
        )

    def _save(self):
        script = self._collect_form()
        if script is not None:
            self.dismiss(script)

    def _scratch_run(self):
        draft = self._collect_form()
        if draft is None:
            return

        if draft.args:
            def on_args(values: list[str] | None):
                if values is not None:
                    self._scratch_execute(draft, values)

            self.app.push_screen(RunScreen(draft), callback=on_args)
        else:
            self._scratch_execute(draft, None)

    def _scratch_execute(self, draft: Script, arg_values: list[str] | None):
        log = self.query_one("#scratch-output", RichLog)
        log.add_class("visible")
        log.clear()
        log.write(f"[bold]$ running draft '{draft.name}'[/bold]")

        tmp = materialize_draft(draft.content, draft.type)

        async def run():
            try:
                result = await execute_script(
                    draft,
                    arg_values=arg_values,
                    on_output=log.write,
                    script_path=tmp,
                    python_command=self.app._config.python_command,
                )
                tag = "red" if result.exit_code != 0 else "green"
                status = "timed out" if result.timed_out else f"exit {result.exit_code}"
                log.write(f"[{tag}]— {status} in {result.duration:.2f}s[/]")
            except (InterpreterNotFoundError, ScriptCwdError) as e:
                log.write(f"[red]error:[/red] {e}")
                self.notify(str(e), severity="error")
            except Exception as e:
                log.write(f"[red]error:[/red] {e}")
                self.notify(str(e), severity="error")
            finally:
                tmp.unlink(missing_ok=True)

        self.run_worker(run(), name="scratch-execute", exclusive=True)
