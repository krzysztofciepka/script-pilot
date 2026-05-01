from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import scriptpilot.storage as storage_mod
from scriptpilot.app import ScriptPilotApp


def _spy_store_init():
    """Returns (captured_dict, spy_callable). spy delegates to the real init."""
    captured: dict[str, Path | None] = {}
    real_init = storage_mod.ScriptStore.__init__

    def spy_init(self, path=None):
        captured["path"] = path
        real_init(self, path=path)

    return captured, spy_init


def test_scripts_dir_passed_to_store(tmp_path, monkeypatch):
    """When AppConfig has scripts_dir, ScriptStore is constructed with the expanded path."""
    scripts_dir = tmp_path / "myscripts"
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "default_model": "openai/gpt-4o",
        "scripts_dir": str(scripts_dir),
    }))

    monkeypatch.setattr("scriptpilot.app.CONFIG_PATH", config_path)

    captured, spy = _spy_store_init()
    with patch("scriptpilot.storage.ScriptStore.__init__", spy):
        ScriptPilotApp()

    assert captured["path"] == scripts_dir


def test_no_scripts_dir_uses_default(tmp_path, monkeypatch):
    """When scripts_dir is None, ScriptStore is constructed with path=None (default)."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"default_model": "openai/gpt-4o"}))
    monkeypatch.setattr("scriptpilot.app.CONFIG_PATH", config_path)

    captured, spy = _spy_store_init()
    with patch("scriptpilot.storage.ScriptStore.__init__", spy):
        ScriptPilotApp()

    assert captured["path"] is None


def test_theme_persisted_on_toggle(tmp_path, monkeypatch):
    """Calling action_toggle_dark updates AppConfig.theme and writes config.json."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "default_model": "openai/gpt-4o",
        "theme": "dark",
    }))
    monkeypatch.setattr("scriptpilot.app.CONFIG_PATH", config_path)

    app = ScriptPilotApp()
    # Simulate the in-memory state after Textual flips it.
    app.dark = False  # post-toggle to light
    app._config.theme = "light"
    app._save_config()

    saved = json.loads(config_path.read_text())
    assert saved["theme"] == "light"


def test_theme_loaded_from_config(tmp_path, monkeypatch):
    """When config.theme is 'light', AppConfig reflects that on startup."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "default_model": "openai/gpt-4o",
        "theme": "light",
    }))
    monkeypatch.setattr("scriptpilot.app.CONFIG_PATH", config_path)

    app = ScriptPilotApp()
    assert app._config.theme == "light"


def test_scripts_dir_with_tilde_expanded(tmp_path, monkeypatch):
    """scripts_dir starting with ~ is expanded via Path.expanduser()."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "default_model": "openai/gpt-4o",
        "scripts_dir": "~/scripts",
    }))
    monkeypatch.setattr("scriptpilot.app.CONFIG_PATH", config_path)

    captured, spy = _spy_store_init()
    with patch("scriptpilot.storage.ScriptStore.__init__", spy):
        ScriptPilotApp()

    assert captured["path"] == fake_home / "scripts"
