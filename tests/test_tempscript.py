from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from scriptpilot.tempscript import materialize_draft


class TestMaterializeDraft:
    def test_bash_extension(self):
        path = materialize_draft("echo hi", "bash")
        try:
            assert path.suffix == ".sh"
            assert path.read_text() == "echo hi"
            assert path.parent == Path(tempfile.gettempdir())
        finally:
            path.unlink(missing_ok=True)

    def test_python_extension(self):
        path = materialize_draft("print('hi')", "python")
        try:
            assert path.suffix == ".py"
            assert path.read_text() == "print('hi')"
        finally:
            path.unlink(missing_ok=True)

    def test_js_extension(self):
        path = materialize_draft("console.log('hi')", "js")
        try:
            assert path.suffix == ".js"
            assert path.read_text() == "console.log('hi')"
        finally:
            path.unlink(missing_ok=True)

    def test_empty_content(self):
        path = materialize_draft("", "bash")
        try:
            assert path.read_text() == ""
        finally:
            path.unlink(missing_ok=True)

    def test_unknown_type_raises(self):
        with pytest.raises(KeyError):
            materialize_draft("x", "ruby")

    def test_caller_can_unlink(self):
        path = materialize_draft("x", "bash")
        assert path.exists()
        path.unlink()
        assert not path.exists()
