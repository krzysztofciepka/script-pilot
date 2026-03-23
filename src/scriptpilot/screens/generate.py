from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, TextArea
from textual.worker import Worker, WorkerState

from scriptpilot.models import Script
from scriptpilot.openrouter import (
    OpenRouterClient,
    AuthenticationError,
    RateLimitError,
)

LANGUAGES = [("Bash", "bash"), ("Python", "python"), ("JavaScript", "js")]

TEXTUAL_LANGUAGES = {"bash": "bash", "python": "python", "js": "javascript"}


class GenerateScreen(ModalScreen[Script | None]):
    """Modal screen for AI script generation via OpenRouter."""

    DEFAULT_CSS = """
    GenerateScreen {
        align: center middle;
    }
    GenerateScreen #gen-container {
        width: 80%;
        max-width: 100;
        height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    GenerateScreen #description-area {
        height: 6;
        margin-bottom: 1;
    }
    GenerateScreen #result-area {
        height: 1fr;
        margin-bottom: 1;
    }
    GenerateScreen #button-bar {
        height: 3;
        align: right middle;
    }
    GenerateScreen #button-bar Button {
        margin-left: 1;
    }
    GenerateScreen #save-fields {
        height: auto;
        margin-bottom: 1;
    }
    """

    def __init__(self, default_model: str = "openai/gpt-4o"):
        super().__init__()
        self._model = default_model
        self._generated = False

    def compose(self) -> ComposeResult:
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        with Vertical(id="gen-container"):
            yield Label("[bold]Generate Script with AI[/bold]")
            if not api_key:
                yield Label(
                    "[red]Set OPENROUTER_API_KEY environment variable to use AI generation.[/red]",
                    id="no-key-warning",
                )
            yield Label("What should this script do?")
            yield TextArea(id="description-area", language=None)
            yield Label("Language:")
            yield Select(LANGUAGES, value="bash", id="lang-select")
            yield Label("Generated Code:")
            yield TextArea(id="result-area", language="bash", read_only=True)
            with Vertical(id="save-fields"):
                yield Label("Script Name:")
                yield Input(id="save-name", placeholder="Name for this script")
                yield Label("Description:")
                yield Input(id="save-desc", placeholder="Brief description")
            with Horizontal(id="button-bar"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Retry", id="retry-btn", disabled=True)
                yield Button(
                    "Generate",
                    id="generate-btn",
                    variant="primary",
                    disabled=not bool(api_key),
                )
                yield Button("Save", id="save-btn", variant="success", disabled=True)

    def on_mount(self):
        self.query_one("#save-fields").display = False

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "generate-btn" or event.button.id == "retry-btn":
            self._do_generate()
        elif event.button.id == "save-btn":
            self._do_save()

    def _do_generate(self):
        description = self.query_one("#description-area", TextArea).text.strip()
        if not description:
            self.notify("Please describe what the script should do", severity="error")
            return

        language = self.query_one("#lang-select", Select).value
        api_key = os.environ.get("OPENROUTER_API_KEY", "")

        # Update result area language to match selection
        result_area = self.query_one("#result-area", TextArea)
        result_area.language = TEXTUAL_LANGUAGES.get(language, "bash")

        self.query_one("#generate-btn", Button).disabled = True
        self.query_one("#retry-btn", Button).disabled = True
        self.notify("Generating script...")

        self.run_worker(
            self._generate(api_key, description, language),
            name="generate",
        )

    async def _generate(self, api_key: str, description: str, language: str):
        client = OpenRouterClient(api_key=api_key)
        return await client.generate_script(description, language, self._model)

    def on_worker_state_changed(self, event: Worker.StateChanged):
        if event.worker.name != "generate":
            return
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            result_area = self.query_one("#result-area", TextArea)
            result_area.read_only = False
            result_area.load_text(result)
            self.query_one("#save-fields").display = True
            self.query_one("#save-btn", Button).disabled = False
            self.query_one("#retry-btn", Button).disabled = False
            self.query_one("#generate-btn", Button).disabled = False
            self._generated = True
        elif event.state == WorkerState.ERROR:
            error = event.worker.error
            if isinstance(error, AuthenticationError):
                self.notify("Invalid API key", severity="error")
            elif isinstance(error, RateLimitError):
                self.notify("Rate limited, try again later", severity="error")
            else:
                self.notify(f"Could not reach OpenRouter: {error}", severity="error")
            self.query_one("#generate-btn", Button).disabled = False
            self.query_one("#retry-btn", Button).disabled = not self._generated

    def _do_save(self):
        name = self.query_one("#save-name", Input).value.strip()
        if not name:
            self.notify("Script name is required", severity="error")
            return
        desc = self.query_one("#save-desc", Input).value.strip()
        content = self.query_one("#result-area", TextArea).text
        language = self.query_one("#lang-select", Select).value

        script = Script(
            name=name,
            description=desc,
            type=language,
            content=content,
        )
        self.dismiss(script)
