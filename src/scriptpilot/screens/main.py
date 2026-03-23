from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, Label
from textual.worker import Worker, WorkerState

from scriptpilot.models import Script
from scriptpilot.storage import ScriptStore
from scriptpilot.executor import execute_script, InterpreterNotFoundError
from scriptpilot.widgets.script_list import ScriptList, ScriptSelected, ScriptRunRequested
from scriptpilot.widgets.main_panel import MainPanel
from scriptpilot.screens.edit import EditScreen
from scriptpilot.screens.run import RunScreen


class MainScreen(Screen):
    """Main three-panel screen."""

    BINDINGS = [
        ("n", "new_script", "New"),
        ("e", "edit_script", "Edit"),
        ("d", "delete_script", "Delete"),
        ("r", "run_script", "Run"),
    ]

    DEFAULT_CSS = """
    MainScreen #main-layout {
        height: 1fr;
    }
    """

    def __init__(self, store: ScriptStore):
        super().__init__()
        self._store = store
        self._selected_script: Script | None = None
        self._running = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-layout"):
            yield ScriptList(self._store.list())
            yield MainPanel()
        yield Footer()

    def on_script_selected(self, event: ScriptSelected):
        self._selected_script = event.script
        self.query_one(MainPanel).show_script_details(event.script)

    def on_script_run_requested(self, event: ScriptRunRequested):
        self._selected_script = event.script
        self.action_run_script()

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
                self.query_one(MainPanel).show_script_details(script)

        self.app.push_screen(
            EditScreen(self._selected_script), callback=on_result
        )

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
        if self._running:
            self.notify("A script is already running", severity="warning")
            return

        script = self._selected_script
        if script.args:

            def on_args(values: list[str] | None):
                if values is not None:
                    self._execute(script, values)

            self.app.push_screen(RunScreen(script), callback=on_args)
        else:
            self._execute(script)

    def _execute(self, script: Script, arg_values: list[str] | None = None):
        self._running = True
        panel = self.query_one(MainPanel)
        panel.show_running(script)

        async def run():
            try:
                result = await execute_script(
                    script,
                    arg_values=arg_values,
                    on_output=panel.append_output,
                )
                panel.show_finished(result.exit_code, result.duration, result.timed_out)
            except InterpreterNotFoundError as e:
                panel.show_error(str(e))
                self.notify(str(e), severity="error")
            except Exception as e:
                panel.show_error(f"Error: {e}")
                self.notify(str(e), severity="error")
            finally:
                self._running = False

        self.run_worker(run(), name="execute")

    def on_worker_state_changed(self, event: Worker.StateChanged):
        if event.worker.name == "execute" and event.state in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            self._running = False

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
