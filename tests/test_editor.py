from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from scriptpilot.editor import EditorError, _run_editor, resolve_editor
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


class TestRunEditor:
    def test_editor_invoked_on_file(self, tmp_path):
        """A fake editor (shell script) appends a marker; we verify it ran on the target file."""
        target = tmp_path / "script.sh"
        target.write_text("echo original\n")

        fake_editor = tmp_path / "fake_editor.sh"
        fake_editor.write_text(
            '#!/bin/sh\n'
            'echo "edited by fake_editor" >> "$1"\n'
        )
        fake_editor.chmod(
            fake_editor.stat().st_mode
            | stat.S_IEXEC
            | stat.S_IRGRP
            | stat.S_IXGRP
            | stat.S_IXOTH
        )

        _run_editor([str(fake_editor)], target)

        text = target.read_text()
        assert "echo original" in text
        assert "edited by fake_editor" in text

    def test_raises_editor_error_when_binary_missing(self, tmp_path):
        target = tmp_path / "script.sh"
        target.write_text("x")
        with pytest.raises(EditorError):
            _run_editor(["nonexistent_editor_xyz_zzz"], target)

    def test_tolerates_nonzero_exit(self, tmp_path):
        """Editor that exits non-zero should not raise."""
        target = tmp_path / "script.sh"
        target.write_text("x")

        fake_editor = tmp_path / "exit_one.sh"
        fake_editor.write_text('#!/bin/sh\nexit 1\n')
        fake_editor.chmod(
            fake_editor.stat().st_mode
            | stat.S_IEXEC
            | stat.S_IRGRP
            | stat.S_IXGRP
            | stat.S_IXOTH
        )

        # Should not raise
        _run_editor([str(fake_editor)], target)
