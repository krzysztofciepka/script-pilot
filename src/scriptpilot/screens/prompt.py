from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label, TextArea
from textual.worker import Worker, WorkerState

from scriptpilot.models import Script
from scriptpilot.openrouter import (
    AuthenticationError,
    GenerationResult,
    OpenRouterClient,
    RateLimitError,
)

TEXTUAL_LANGUAGES = {"bash": "bash", "python": "python", "js": "javascript"}


class PromptScreen(ModalScreen[Script | None]):
    """Modal screen for modifying a script via LLM prompt."""

    DEFAULT_CSS = """
    PromptScreen {
        align: center middle;
    }
    PromptScreen #prompt-container {
        width: 80%;
        max-width: 100;
        height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    PromptScreen #instruction-area {
        height: 6;
        margin-bottom: 1;
    }
    PromptScreen #preview-area {
        height: 1fr;
        margin-bottom: 1;
    }
    PromptScreen #button-bar {
        height: 3;
        align: right middle;
        dock: bottom;
    }
    PromptScreen #button-bar Button {
        margin-left: 1;
    }
    """

    def __init__(self, script: Script, default_model: str = "openai/gpt-4o"):
        super().__init__()
        self._script = script
        self._model = default_model
        self._result: GenerationResult | None = None

    def compose(self) -> ComposeResult:
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        lang = TEXTUAL_LANGUAGES.get(self._script.type, "bash")
        with Vertical(id="prompt-container"):
            yield Label(f"[bold]Modify: {self._script.name}[/bold]")
            if not api_key:
                yield Label(
                    "[red]Set OPENROUTER_API_KEY environment variable.[/red]",
                    id="no-key-warning",
                )
            yield Label("What should be changed?")
            yield TextArea(id="instruction-area", language=None)
            yield Label("Preview:")
            yield TextArea(
                self._script.content,
                id="preview-area",
                language=lang,
                read_only=True,
            )
            with Horizontal(id="button-bar"):
                yield Button("Cancel", id="cancel-btn")
                yield Button(
                    "Submit",
                    id="submit-btn",
                    variant="primary",
                    disabled=not bool(api_key),
                )
                yield Button("Accept", id="accept-btn", variant="success", disabled=True)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "submit-btn":
            self._do_modify()
        elif event.button.id == "accept-btn":
            self._do_accept()

    def _do_modify(self):
        instruction = self.query_one("#instruction-area", TextArea).text.strip()
        if not instruction:
            self.notify("Please describe what to change", severity="error")
            return

        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self.query_one("#submit-btn", Button).disabled = True
        self.notify("Modifying script...")

        self.run_worker(
            self._modify(api_key, instruction),
            name="modify",
        )

    async def _modify(self, api_key: str, instruction: str):
        client = OpenRouterClient(api_key=api_key)
        return await client.modify_script(
            current_code=self._script.content,
            instruction=instruction,
            language=self._script.type,
            model=self._model,
        )

    def on_worker_state_changed(self, event: Worker.StateChanged):
        if event.worker.name != "modify":
            return
        if event.state == WorkerState.SUCCESS:
            self._result = event.worker.result
            preview = self.query_one("#preview-area", TextArea)
            preview.load_text(self._result.code)
            self.query_one("#accept-btn", Button).disabled = False
            self.query_one("#submit-btn", Button).disabled = False
        elif event.state == WorkerState.ERROR:
            error = event.worker.error
            if isinstance(error, AuthenticationError):
                self.notify("Invalid API key", severity="error")
            elif isinstance(error, RateLimitError):
                self.notify("Rate limited, try again later", severity="error")
            else:
                self.notify(f"Error: {error}", severity="error")
            self.query_one("#submit-btn", Button).disabled = False

    def _do_accept(self):
        if not self._result:
            return
        updated = Script(
            id=self._script.id,
            name=self._script.name,
            description=self._script.description,
            type=self._script.type,
            content=self._result.code,
            args=self._result.args,
            timeout=self._script.timeout,
            favorite=self._script.favorite,
        )
        self.dismiss(updated)
