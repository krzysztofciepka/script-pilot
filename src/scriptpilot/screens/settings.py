from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select

from scriptpilot.blackbox import API_KEY_ENV, get_api_key
from scriptpilot.models import AppConfig
from scriptpilot.secrets import SECRETS_PATH, load_secrets


class SettingsScreen(ModalScreen[AppConfig | None]):
    """Modal screen for app settings."""

    DEFAULT_CSS = """
    SettingsScreen {
        align: center middle;
    }
    SettingsScreen #settings-container {
        width: 60%;
        max-width: 80;
        height: auto;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    SettingsScreen Input {
        margin-bottom: 1;
    }
    SettingsScreen #button-bar {
        height: 3;
        align: right middle;
        margin-top: 1;
    }
    SettingsScreen #button-bar Button {
        margin-left: 1;
    }
    """

    def __init__(self, config: AppConfig):
        super().__init__()
        self._config = config

    def compose(self) -> ComposeResult:
        api_key = get_api_key()
        key_status = "[green]Set[/green]" if api_key else "[red]Not set[/red]"

        if SECRETS_PATH.exists():
            n = len(load_secrets())
            secrets_status = f"[green]{n} keys loaded[/green]"
        else:
            secrets_status = "[dim]not present[/dim]"

        scripts_dir_display = self._config.scripts_dir or "~/.scriptpilot/scripts (default)"

        with Vertical(id="settings-container"):
            yield Label("[bold]Settings[/bold]")
            yield Label("")
            yield Label(f"Blackbox API Key: {key_status}")
            yield Label(
                f"[dim]Set {API_KEY_ENV} env var or add it to ~/.scriptpilot/.env[/dim]"
            )
            yield Label("")
            yield Label("Default Model:")
            yield Input(
                value=self._config.default_model,
                id="model-input",
            )
            yield Label("Python command:")
            yield Input(
                value=self._config.python_command,
                placeholder="uv run --script",
                id="python-cmd-input",
            )
            yield Label("Editor command:")
            yield Input(
                value=self._config.editor or "",
                placeholder="$VISUAL or $EDITOR or vi",
                id="editor-input",
            )
            yield Label("Theme:")
            yield Select(
                [("Dark", "dark"), ("Light", "light")],
                value=self._config.theme,
                allow_blank=False,
                id="theme-select",
            )
            yield Label(f"Scripts dir: {scripts_dir_display}")
            yield Label("[dim]edit ~/.scriptpilot/config.json to change[/dim]")
            yield Label(f"Agent max tool calls: {self._config.agent_max_tool_calls}")
            yield Label(f"Bash tool timeout (s): {self._config.bash_tool_timeout}")
            yield Label("[dim]edit ~/.scriptpilot/config.json to change[/dim]")
            yield Label(f"Secrets file: {SECRETS_PATH} [{secrets_status}]")
            yield Label(
                "[dim]One KEY=VALUE per line. Edit with your editor.[/dim]"
            )
            with Horizontal(id="button-bar"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Save", id="save-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "save-btn":
            model = self.query_one("#model-input", Input).value.strip()
            python_cmd = self.query_one("#python-cmd-input", Input).value.strip()
            if not python_cmd:
                python_cmd = "uv run --script"
            editor_val = self.query_one("#editor-input", Input).value.strip() or None
            theme_val = self.query_one("#theme-select", Select).value
            config = AppConfig(
                default_model=model or "blackboxai/minimax/minimax-m2.5",
                python_command=python_cmd,
                editor=editor_val,
                theme=theme_val,
                scripts_dir=self._config.scripts_dir,
                agent_max_tool_calls=self._config.agent_max_tool_calls,
                bash_tool_timeout=self._config.bash_tool_timeout,
            )
            self.dismiss(config)
