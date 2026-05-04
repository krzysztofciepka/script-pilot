from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, Label

from scriptpilot.models import OutputLine, RunRecord, Script, ScriptArg
from scriptpilot.storage import ScriptStore
from scriptpilot.history import HistoryStore
from scriptpilot.executor import execute_script, InterpreterNotFoundError, ScriptCwdError
from scriptpilot.editor import edit_file, EditorError
from scriptpilot.widgets.script_list import ScriptList, ScriptSelected
from scriptpilot.widgets.main_panel import MainPanel
from scriptpilot.screens.edit import EditScreen
from scriptpilot.screens.run import RunScreen
from scriptpilot.screens.prompt import PromptScreen


class MainScreen(Screen):
    """Main three-panel screen."""

    BINDINGS = [
        ("n", "new_script", "New"),
        ("e", "edit_script", "Edit"),
        ("E", "edit_in_external", "Editor"),
        ("d", "delete_script", "Delete"),
        ("r", "run_script", "Run"),
        ("p", "prompt_script", "Prompt"),
        ("c", "clone_script", "Clone"),
        ("f", "toggle_favorite", "Fav"),
    ]

    DEFAULT_CSS = """
    MainScreen #main-layout {
        height: 1fr;
    }
    """

    def __init__(self, store: ScriptStore, history: HistoryStore):
        super().__init__()
        self._store = store
        self._history = history
        self._selected_script: Script | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-layout"):
            yield ScriptList(self._store.list())
            yield MainPanel()
        yield Footer()

    def _get_last_run(self, script_id: str):
        runs = self._history.list_for_script(script_id)
        return runs[0] if runs else None

    def on_script_selected(self, event: ScriptSelected):
        self._selected_script = event.script
        last_run = self._get_last_run(event.script.id)
        panel = self.query_one(MainPanel)
        panel.show_script_details(event.script, last_run)
        if last_run:
            panel.show_finished_run(last_run)

    def action_new_script(self):
        def on_result(script: Script | None):
            if script:
                self._store.add(script)
                self._refresh_list()

        self.app.push_screen(EditScreen(), callback=on_result)

    def action_edit_script(self):
        if not self._selected_script:
            self.notify("No script selected", severity="warning")
            return

        def on_result(script: Script | None):
            if script:
                self._store.update(script)
                self._selected_script = script
                self._refresh_list()
                last_run = self._get_last_run(script.id)
                self.query_one(MainPanel).show_script_details(script, last_run)

        self.app.push_screen(
            EditScreen(self._selected_script), callback=on_result
        )

    def action_edit_in_external(self):
        if not self._selected_script:
            self.notify("No script selected", severity="warning")
            return
        script = self._selected_script
        path = self._store.path_for(script.id)
        try:
            edit_file(self.app, self.app._config, path)
        except EditorError as e:
            self.notify(str(e), severity="error")
            return
        try:
            new_content = path.read_text()
        except OSError as e:
            self.notify(f"Could not reload script: {e}", severity="error")
            return
        if new_content != script.content:
            script.content = new_content
            self._store.update(script)
            self._refresh_list()
            last_run = self._get_last_run(script.id)
            self.query_one(MainPanel).show_script_details(script, last_run)

    def action_delete_script(self):
        if not self._selected_script:
            self.notify("No script selected", severity="warning")
            return

        name = self._selected_script.name
        script_id = self._selected_script.id

        def confirm_delete(confirmed: bool):
            if confirmed:
                self._store.delete(script_id)
                self._selected_script = None
                self._refresh_list()
                self.notify(f"Deleted '{name}'")

        self.app.push_screen(
            ConfirmScreen(f"Delete script '{name}'?"), callback=confirm_delete
        )

    def action_run_script(self):
        if not self._selected_script:
            self.notify("No script selected", severity="warning")
            return

        script = self._selected_script
        if script.args:

            def on_args(values: list[str] | None):
                if values is not None:
                    self._execute(script, values)

            self.app.push_screen(RunScreen(script), callback=on_args)
        else:
            self._execute(script)

    def action_prompt_script(self):
        if not self._selected_script:
            self.notify("No script selected", severity="warning")
            return

        script = self._selected_script

        def on_result(updated: Script | None):
            if updated:
                self._store.update(updated)
                self._selected_script = updated
                self._refresh_list()
                last_run = self._get_last_run(updated.id)
                self.query_one(MainPanel).show_script_details(updated, last_run)

        self.app.push_screen(
            PromptScreen(script, default_model=self.app._config.default_model),
            callback=on_result,
        )

    def action_clone_script(self):
        if not self._selected_script:
            self.notify("No script selected", severity="warning")
            return

        original = self._selected_script
        clone = Script(
            name=f"{original.name} (copy)",
            description=original.description,
            type=original.type,
            content=original.content,
            args=[ScriptArg(**a.model_dump()) for a in original.args],
            timeout=original.timeout,
            favorite=False,
            cwd=original.cwd,
            env=dict(original.env),
        )
        self._store.add(clone)
        self._refresh_list()
        self.notify(f"Cloned '{original.name}'")

    def action_toggle_favorite(self):
        if not self._selected_script:
            self.notify("No script selected", severity="warning")
            return

        script = self._selected_script
        updated = Script(
            id=script.id,
            name=script.name,
            description=script.description,
            type=script.type,
            content=script.content,
            args=script.args,
            timeout=script.timeout,
            favorite=not script.favorite,
            cwd=script.cwd,
            env=script.env,
        )
        self._store.update(updated)
        self._selected_script = updated
        self._refresh_list()
        last_run = self._get_last_run(updated.id)
        self.query_one(MainPanel).show_script_details(updated, last_run)
        label = "Favorited" if updated.favorite else "Unfavorited"
        self.notify(f"{label} '{updated.name}'")

    def _execute(self, script: Script, arg_values: list[str] | None = None):
        panel = self.query_one(MainPanel)
        panel.show_running(script)

        async def run():
            collected: list[OutputLine] = []

            def collect_output(line: OutputLine):
                collected.append(line)
                panel.append_output(line)

            try:
                result = await execute_script(
                    script,
                    arg_values=arg_values,
                    on_output=collect_output,
                    script_path=self._store.path_for(script.id),
                    python_command=self.app._config.python_command,
                )

                from datetime import datetime, timezone
                record = RunRecord(
                    script_id=script.id,
                    script_name=script.name,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    exit_code=result.exit_code,
                    timed_out=result.timed_out,
                    duration=result.duration,
                    lines=collected,
                )
                self._history.add(record)
                panel.show_finished_run(record)
            except (InterpreterNotFoundError, ScriptCwdError) as e:
                panel.show_error(str(e))
                self.notify(str(e), severity="error")
            except Exception as e:
                panel.show_error(f"Error: {e}")
                self.notify(str(e), severity="error")

        self.run_worker(run(), name="execute", exclusive=True)

    def _refresh_list(self):
        self.query_one(ScriptList).update_scripts(self._store.list())


class ConfirmScreen(ModalScreen[bool]):
    """Simple yes/no confirmation dialog."""

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }
    ConfirmScreen #confirm-container {
        width: 50;
        height: auto;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    ConfirmScreen #confirm-buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }
    ConfirmScreen #confirm-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, message: str):
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-container"):
            yield Label(self._message)
            with Horizontal(id="confirm-buttons"):
                yield Button("No", id="no-btn")
                yield Button("Yes", id="yes-btn", variant="error")

    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss(event.button.id == "yes-btn")
