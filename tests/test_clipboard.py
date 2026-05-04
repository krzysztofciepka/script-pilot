import sys
from unittest.mock import MagicMock, patch

import pytest

from scriptpilot.clipboard import ClipboardUnavailable, copy


class TestClipboardPyperclip:
    def test_uses_pyperclip_when_importable(self):
        fake_pyperclip = MagicMock()
        with patch.dict(sys.modules, {"pyperclip": fake_pyperclip}):
            copy("hello")
        fake_pyperclip.copy.assert_called_once_with("hello")

    def test_falls_through_when_pyperclip_raises(self):
        fake_pyperclip = MagicMock()
        fake_pyperclip.copy.side_effect = RuntimeError("boom")
        with patch.dict(sys.modules, {"pyperclip": fake_pyperclip}):
            with patch("scriptpilot.clipboard.shutil.which", return_value="/usr/bin/wl-copy"):
                with patch("scriptpilot.clipboard.subprocess.run") as run:
                    run.return_value = None
                    copy("hello")
                    run.assert_called_once()
                    assert run.call_args.args[0][0] == "wl-copy"


class TestClipboardShellLinux:
    @pytest.fixture(autouse=True)
    def _no_pyperclip(self):
        with patch.dict(sys.modules, {"pyperclip": None}):
            yield

    @pytest.fixture(autouse=True)
    def _platform_linux(self):
        with patch("scriptpilot.clipboard.sys.platform", "linux"):
            yield

    def test_prefers_wl_copy_on_linux(self):
        def which(cmd):
            return "/usr/bin/wl-copy" if cmd == "wl-copy" else None

        with patch("scriptpilot.clipboard.shutil.which", side_effect=which):
            with patch("scriptpilot.clipboard.subprocess.run") as run:
                copy("text")
                assert run.call_args.args[0] == ["wl-copy"]
                assert run.call_args.kwargs["input"] == b"text"

    def test_falls_back_to_xclip(self):
        def which(cmd):
            return "/usr/bin/xclip" if cmd == "xclip" else None

        with patch("scriptpilot.clipboard.shutil.which", side_effect=which):
            with patch("scriptpilot.clipboard.subprocess.run") as run:
                copy("text")
                assert run.call_args.args[0] == ["xclip", "-selection", "clipboard"]

    def test_raises_when_no_backend(self):
        with patch("scriptpilot.clipboard.shutil.which", return_value=None):
            with pytest.raises(ClipboardUnavailable):
                copy("text")

    def test_falls_through_failed_backend(self):
        import subprocess

        def which(cmd):
            return f"/usr/bin/{cmd}" if cmd in ("wl-copy", "xclip") else None

        run_calls = []

        def fake_run(cmd, **kwargs):
            run_calls.append(cmd)
            if cmd[0] == "wl-copy":
                raise subprocess.CalledProcessError(1, cmd)
            return None

        with patch("scriptpilot.clipboard.shutil.which", side_effect=which):
            with patch("scriptpilot.clipboard.subprocess.run", side_effect=fake_run):
                copy("text")
        assert run_calls[0][0] == "wl-copy"
        assert run_calls[1][0] == "xclip"


class TestClipboardShellMacos:
    @pytest.fixture(autouse=True)
    def _no_pyperclip(self):
        with patch.dict(sys.modules, {"pyperclip": None}):
            yield

    @pytest.fixture(autouse=True)
    def _platform_darwin(self):
        with patch("scriptpilot.clipboard.sys.platform", "darwin"):
            yield

    def test_uses_pbcopy_on_macos(self):
        def which(cmd):
            return "/usr/bin/pbcopy" if cmd == "pbcopy" else None

        with patch("scriptpilot.clipboard.shutil.which", side_effect=which):
            with patch("scriptpilot.clipboard.subprocess.run") as run:
                copy("text")
                assert run.call_args.args[0] == ["pbcopy"]
