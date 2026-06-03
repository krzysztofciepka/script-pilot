from __future__ import annotations

import json
from pathlib import Path

from textual.app import App

from scriptpilot.models import AppConfig
from scriptpilot.storage import ScriptStore
from scriptpilot.history import HistoryStore
from scriptpilot.screens.main import MainScreen
from scriptpilot.screens.settings import SettingsScreen
from scriptpilot.screens.chat import ChatScreen
from scriptpilot.blackbox import get_api_key
from scriptpilot.models import Script

CONFIG_PATH = Path.home() / ".scriptpilot" / "config.json"


class ScriptPilotApp(App):
    """ScriptPilot TUI application."""

    TITLE = "ScriptPilot"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("s", "open_settings", "Settings"),
        ("g", "generate", "Generate"),
        ("t", "toggle_dark", "Theme"),
        ("?", "show_help", "Help"),
        ("f1", "show_help", "Help"),
    ]

    def __init__(self):
        super().__init__()
        self._config = self._load_config()
        scripts_path = (
            Path(self._config.scripts_dir).expanduser()
            if self._config.scripts_dir
            else None
        )
        self._store = ScriptStore(path=scripts_path)
        self._history = HistoryStore()

    def on_mount(self):
        self.dark = (self._config.theme == "dark")
        self.push_screen(MainScreen(self._store, self._history))

    def action_toggle_dark(self):
        super().action_toggle_dark()
        self._config.theme = "dark" if self.dark else "light"
        try:
            self._save_config()
        except Exception as e:
            self.notify(f"Could not save theme: {e}", severity="error")

    def _load_config(self) -> AppConfig:
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text())
                return AppConfig(**data)
            except Exception:
                pass
        return AppConfig()

    def _save_config(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(self._config.model_dump(), indent=2)
        )

    def action_open_settings(self):
        def on_result(config: AppConfig | None):
            if config:
                self._config = config
                self.dark = (config.theme == "dark")
                self._save_config()
                self.notify("Settings saved")

        self.push_screen(SettingsScreen(self._config), callback=on_result)

    def action_show_help(self):
        # Deferred import: HelpScreen is only used on demand, and importing it
        # eagerly would pull MarkdownViewer into the startup path.
        from scriptpilot.screens.help import HelpScreen
        self.push_screen(HelpScreen())

    def action_generate(self):
        def on_result(script: Script | None):
            if script:
                self._store.add(script)
                for screen in self.screen_stack:
                    if isinstance(screen, MainScreen):
                        screen._refresh_list()
                        break
                self.notify(f"Script '{script.name}' saved")

        self.push_screen(
            ChatScreen(
                store=self._store,
                script=None,
                model=self._config.default_model,
                api_key=get_api_key(),
                max_tool_calls=self._config.agent_max_tool_calls,
                bash_timeout=self._config.bash_tool_timeout,
            ),
            callback=on_result,
        )


def _cli_version() -> str:
    from scriptpilot import __version__
    return __version__ if __version__.startswith("v") else f"v{__version__}"


def main():
    import sys

    argv = sys.argv[1:]
    if "--version" in argv or "-V" in argv:
        print(f"scriptpilot {_cli_version()}")
        return
    if "--upgrade" in argv:
        from scriptpilot.upgrade import GITHUB_API_BASE, run_upgrade

        if not getattr(sys, "frozen", False):
            sys.stderr.write(
                "scriptpilot --upgrade only works on the standalone binary.\n"
                "For pip/uv installs, run: uv tool upgrade scriptpilot\n"
            )
            sys.exit(1)

        rc = run_upgrade(
            sys.stdout, _cli_version(), GITHUB_API_BASE, sys.executable
        )
        sys.exit(rc)

    app = ScriptPilotApp()
    app.run()
