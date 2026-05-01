from __future__ import annotations

import json
from pathlib import Path

from textual.app import App

from scriptpilot.models import AppConfig
from scriptpilot.storage import ScriptStore
from scriptpilot.history import HistoryStore
from scriptpilot.screens.main import MainScreen
from scriptpilot.screens.settings import SettingsScreen
from scriptpilot.screens.generate import GenerateScreen
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
        self.push_screen(MainScreen(self._store, self._history))

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
                self._save_config()
                self.notify("Settings saved")

        self.push_screen(SettingsScreen(self._config), callback=on_result)

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
            GenerateScreen(default_model=self._config.default_model),
            callback=on_result,
        )


def main():
    app = ScriptPilotApp()
    app.run()
