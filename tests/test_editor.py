from __future__ import annotations

from unittest.mock import patch

import pytest

from scriptpilot.editor import EditorError, resolve_editor
from scriptpilot.models import AppConfig


class TestResolveEditor:
    def test_config_editor_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("VISUAL", "emacs")
        monkeypatch.setenv("EDITOR", "vim")
        config = AppConfig(editor="code --wait")
        with patch("shutil.which", return_value="/usr/bin/code"):
            argv = resolve_editor(config)
        assert argv == ["code", "--wait"]

    def test_visual_used_when_no_config_editor(self, monkeypatch):
        monkeypatch.setenv("VISUAL", "nvim")
        monkeypatch.setenv("EDITOR", "vim")
        config = AppConfig()
        with patch("shutil.which", return_value="/usr/bin/nvim"):
            argv = resolve_editor(config)
        assert argv == ["nvim"]

    def test_editor_used_when_no_visual(self, monkeypatch):
        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.setenv("EDITOR", "vim")
        config = AppConfig()
        with patch("shutil.which", return_value="/usr/bin/vim"):
            argv = resolve_editor(config)
        assert argv == ["vim"]

    def test_falls_back_to_vi(self, monkeypatch):
        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.delenv("EDITOR", raising=False)
        config = AppConfig()
        with patch("shutil.which", return_value="/usr/bin/vi"):
            argv = resolve_editor(config)
        assert argv == ["vi"]

    def test_raises_when_no_editor_available(self, monkeypatch):
        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.delenv("EDITOR", raising=False)
        config = AppConfig()
        with patch("shutil.which", return_value=None):
            with pytest.raises(EditorError):
                resolve_editor(config)

    def test_multi_token_config_editor(self, monkeypatch):
        config = AppConfig(editor="code --wait --new-window")
        with patch("shutil.which", return_value="/usr/bin/code"):
            argv = resolve_editor(config)
        assert argv == ["code", "--wait", "--new-window"]

    def test_empty_config_editor_falls_through(self, monkeypatch):
        monkeypatch.setenv("EDITOR", "vim")
        monkeypatch.delenv("VISUAL", raising=False)
        config = AppConfig(editor="")
        with patch("shutil.which", return_value="/usr/bin/vim"):
            argv = resolve_editor(config)
        assert argv == ["vim"]
