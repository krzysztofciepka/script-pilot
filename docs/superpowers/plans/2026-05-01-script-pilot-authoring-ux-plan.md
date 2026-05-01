# ScriptPilot Authoring UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "Edit in $EDITOR" escape hatch (MainScreen + EditScreen), a scratch Run for unsaved drafts, three new `AppConfig` fields (`editor`, `scripts_dir`, `theme`), and minor TUI polish — implementing the spec at `docs/superpowers/specs/2026-05-01-script-pilot-authoring-ux-design.md`.

**Architecture:** Two new small modules (`editor.py` for `$EDITOR` integration, `tempscript.py` for tempfile boilerplate). `AppConfig` gains three persisted fields. App startup reads `scripts_dir` and `theme`; `action_toggle_dark` is overridden to persist. `MainScreen` and `EditScreen` get an uppercase `E` binding for external editing. `EditScreen` gets a Run button that builds a transient `Script` and reuses `execute_script` against a tempfile, streaming output to an inline `RichLog`. `SettingsScreen` exposes the new fields.

**Tech Stack:** Python 3.10+, Textual, Pydantic, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-05-01-script-pilot-authoring-ux-design.md`

---

## File Map

**Create:**
- `src/scriptpilot/editor.py` — `resolve_editor`, `_run_editor`, `edit_file`, `EditorError`
- `src/scriptpilot/tempscript.py` — `materialize_draft`
- `tests/test_editor.py`
- `tests/test_tempscript.py`
- `tests/test_app_config.py`

**Modify:**
- `src/scriptpilot/models.py` — add `editor`, `scripts_dir`, `theme` to `AppConfig`
- `src/scriptpilot/app.py` — pass `scripts_dir` to `ScriptStore`, set `self.dark` from theme, override `action_toggle_dark`, reapply theme after Settings
- `src/scriptpilot/screens/main.py` — `E` binding + `action_edit_in_external`
- `src/scriptpilot/screens/edit.py` — `E` binding + `action_edit_in_external`, Run button + scratch execute, inline `RichLog`, `#content-area` CSS, hint label
- `src/scriptpilot/screens/settings.py` — editor Input, theme Select, scripts_dir Label
- `tests/test_models.py` — add cases for `editor`, `scripts_dir`, `theme`

---

## Task 1: AppConfig fields

**Files:**
- Modify: `src/scriptpilot/models.py:49-53`
- Test: `tests/test_models.py` (extend `TestAppConfig`)

- [ ] **Step 1: Write failing tests for new AppConfig fields**

Append to `tests/test_models.py`:

```python
class TestAppConfigAuthoring:
    def test_editor_default_none(self):
        config = AppConfig()
        assert config.editor is None

    def test_editor_custom(self):
        config = AppConfig(editor="code --wait")
        assert config.editor == "code --wait"

    def test_scripts_dir_default_none(self):
        config = AppConfig()
        assert config.scripts_dir is None

    def test_scripts_dir_custom(self):
        config = AppConfig(scripts_dir="~/myscripts")
        assert config.scripts_dir == "~/myscripts"

    def test_theme_default_dark(self):
        config = AppConfig()
        assert config.theme == "dark"

    def test_theme_set_light(self):
        config = AppConfig(theme="light")
        assert config.theme == "light"

    def test_theme_invalid_rejected(self):
        with pytest.raises(Exception):
            AppConfig(theme="purple")

    def test_backward_compat_old_config(self):
        """A config dict missing the new fields loads with defaults."""
        config = AppConfig(**{"default_model": "openai/gpt-4o"})
        assert config.editor is None
        assert config.scripts_dir is None
        assert config.theme == "dark"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py::TestAppConfigAuthoring -v`
Expected: FAIL — `editor`/`scripts_dir`/`theme` are not fields on `AppConfig`.

- [ ] **Step 3: Add fields to AppConfig**

Edit `src/scriptpilot/models.py`. Replace the `AppConfig` class:

```python
class AppConfig(BaseModel):
    """Application configuration."""

    default_model: str = "openai/gpt-4o"
    python_command: str = "uv run --script"
    editor: str | None = None
    scripts_dir: str | None = None
    theme: Literal["dark", "light"] = "dark"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS — all `TestAppConfig*` classes green.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/models.py tests/test_models.py
git commit -m "feat: add editor, scripts_dir, theme to AppConfig"
```

---

## Task 2: Wire `scripts_dir` into `ScriptPilotApp.__init__`

**Files:**
- Modify: `src/scriptpilot/app.py:31-35`
- Test: `tests/test_app_config.py` (new)

- [ ] **Step 1: Create the new test file with a failing test**

Create `tests/test_app_config.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from scriptpilot.app import ScriptPilotApp
from scriptpilot.models import AppConfig


def test_scripts_dir_passed_to_store(tmp_path, monkeypatch):
    """When AppConfig has scripts_dir, ScriptStore is constructed with the expanded path."""
    scripts_dir = tmp_path / "myscripts"
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "default_model": "openai/gpt-4o",
        "scripts_dir": str(scripts_dir),
    }))

    monkeypatch.setattr("scriptpilot.app.CONFIG_PATH", config_path)

    captured = {}

    real_init = __import__("scriptpilot.storage", fromlist=["ScriptStore"]).ScriptStore.__init__

    def spy_init(self, path=None):
        captured["path"] = path
        real_init(self, path=path)

    with patch("scriptpilot.storage.ScriptStore.__init__", spy_init):
        ScriptPilotApp()

    assert captured["path"] == scripts_dir


def test_no_scripts_dir_uses_default(tmp_path, monkeypatch):
    """When scripts_dir is None, ScriptStore is constructed with path=None (default)."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"default_model": "openai/gpt-4o"}))
    monkeypatch.setattr("scriptpilot.app.CONFIG_PATH", config_path)

    captured = {}

    real_init = __import__("scriptpilot.storage", fromlist=["ScriptStore"]).ScriptStore.__init__

    def spy_init(self, path=None):
        captured["path"] = path
        real_init(self, path=path)

    with patch("scriptpilot.storage.ScriptStore.__init__", spy_init):
        ScriptPilotApp()

    assert captured["path"] is None


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

    captured = {}

    real_init = __import__("scriptpilot.storage", fromlist=["ScriptStore"]).ScriptStore.__init__

    def spy_init(self, path=None):
        captured["path"] = path
        real_init(self, path=path)

    with patch("scriptpilot.storage.ScriptStore.__init__", spy_init):
        ScriptPilotApp()

    assert captured["path"] == fake_home / "scripts"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_app_config.py -v`
Expected: FAIL — currently `ScriptPilotApp.__init__` calls `ScriptStore()` with no args, so the path is always `None`. The first test (custom `scripts_dir`) will fail.

- [ ] **Step 3: Wire scripts_dir into the App constructor**

Edit `src/scriptpilot/app.py`. Replace the `__init__` method:

```python
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
```

(Note: order swapped — `_load_config` runs first because the store needs `_config.scripts_dir`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_app_config.py -v`
Expected: PASS — all three tests green.

- [ ] **Step 5: Run full test suite to check no regressions**

Run: `uv run pytest -v`
Expected: PASS — all existing tests still green.

- [ ] **Step 6: Commit**

```bash
git add src/scriptpilot/app.py tests/test_app_config.py
git commit -m "feat: honor AppConfig.scripts_dir when constructing ScriptStore"
```

---

## Task 3: Apply theme on startup + persist on toggle

**Files:**
- Modify: `src/scriptpilot/app.py:37-38` (`on_mount`), add `action_toggle_dark`
- Test: `tests/test_app_config.py` (extend)

- [ ] **Step 1: Write failing test for theme persistence on toggle**

Append to `tests/test_app_config.py`:

```python
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
    # action_toggle_dark calls super(); we patch that to just flip self.dark.
    app.dark = False  # representing the "post-toggle to light" state
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
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_app_config.py::test_theme_persisted_on_toggle tests/test_app_config.py::test_theme_loaded_from_config -v`
Expected: PASS — these tests don't actually exercise `action_toggle_dark` yet (they test `_save_config` plumbing which already works). They establish the round-trip baseline.

- [ ] **Step 3: Override action_toggle_dark and apply theme on mount**

Edit `src/scriptpilot/app.py`. Add this method to `ScriptPilotApp`:

```python
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
```

(The existing `on_mount` body becomes the second line of the new `on_mount`. Replace, don't append.)

- [ ] **Step 4: Update settings callback to reapply theme**

In `src/scriptpilot/app.py`, replace `action_open_settings`:

```python
def action_open_settings(self):
    def on_result(config: AppConfig | None):
        if config:
            self._config = config
            self.dark = (config.theme == "dark")
            self._save_config()
            self.notify("Settings saved")

    self.push_screen(SettingsScreen(self._config), callback=on_result)
```

- [ ] **Step 5: Run all app config tests**

Run: `uv run pytest tests/test_app_config.py tests/test_models.py -v`
Expected: PASS — all green.

- [ ] **Step 6: Manual smoke test**

```bash
uv run scriptpilot
```

Steps:
1. App should launch in dark mode.
2. Press `t` — theme flips to light.
3. Press `q` to quit.
4. `cat ~/.scriptpilot/config.json` — confirm `"theme": "light"`.
5. Re-launch — app should now start in light mode.
6. Press `t` again, quit, re-launch — back to dark.

(If the test machine has no DISPLAY/TTY, skip the manual smoke test and document that step 6 was deferred.)

- [ ] **Step 7: Commit**

```bash
git add src/scriptpilot/app.py tests/test_app_config.py
git commit -m "feat: persist theme across launches and apply on mount"
```

---

## Task 4: `editor.py` — `EditorError` and `resolve_editor`

**Files:**
- Create: `src/scriptpilot/editor.py`
- Test: `tests/test_editor.py` (new)

- [ ] **Step 1: Write failing tests for resolve_editor**

Create `tests/test_editor.py`:

```python
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
        config = AppConfig(editor="")  # treated as "not set"
        with patch("shutil.which", return_value="/usr/bin/vim"):
            argv = resolve_editor(config)
        assert argv == ["vim"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_editor.py -v`
Expected: FAIL — `scriptpilot.editor` module does not exist.

- [ ] **Step 3: Create editor.py with EditorError and resolve_editor**

Create `src/scriptpilot/editor.py`:

```python
from __future__ import annotations

import os
import shlex
import shutil

from scriptpilot.models import AppConfig


class EditorError(Exception):
    """Raised when no usable editor is available or the editor cannot be launched."""


def resolve_editor(config: AppConfig) -> list[str]:
    """Resolve the editor command to use.

    Priority: ``config.editor`` → ``$VISUAL`` → ``$EDITOR`` → ``vi``.
    Returns the argv list (split via ``shlex``). Raises ``EditorError`` if even
    ``vi`` is not on ``PATH``.
    """
    candidates: list[str] = []
    if config.editor and config.editor.strip():
        candidates.append(config.editor)
    visual = os.environ.get("VISUAL", "").strip()
    if visual:
        candidates.append(visual)
    editor_env = os.environ.get("EDITOR", "").strip()
    if editor_env:
        candidates.append(editor_env)
    candidates.append("vi")

    for cmd in candidates:
        parts = shlex.split(cmd)
        if not parts:
            continue
        if shutil.which(parts[0]) is not None:
            return parts

    raise EditorError(
        f"no editor found on PATH (tried: {', '.join(c.split()[0] for c in candidates if c.split())})"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_editor.py -v`
Expected: PASS — all `TestResolveEditor` tests green.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/editor.py tests/test_editor.py
git commit -m "feat: add editor module with EditorError and resolve_editor"
```

---

## Task 5: `editor.py` — `_run_editor` and `edit_file`

**Files:**
- Modify: `src/scriptpilot/editor.py` (extend)
- Test: `tests/test_editor.py` (extend)

- [ ] **Step 1: Write failing tests for _run_editor**

Append to `tests/test_editor.py`:

```python
import stat
import subprocess
from pathlib import Path

from scriptpilot.editor import _run_editor


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
        fake_editor.chmod(fake_editor.stat().st_mode | stat.S_IEXEC | stat.S_IRGRP | stat.S_IXGRP | stat.S_IXOTH)

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
        """Editor that exits non-zero should not raise — the user may have :cq'd."""
        target = tmp_path / "script.sh"
        target.write_text("x")

        fake_editor = tmp_path / "exit_one.sh"
        fake_editor.write_text('#!/bin/sh\nexit 1\n')
        fake_editor.chmod(fake_editor.stat().st_mode | stat.S_IEXEC | stat.S_IRGRP | stat.S_IXGRP | stat.S_IXOTH)

        # Should not raise
        _run_editor([str(fake_editor)], target)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_editor.py::TestRunEditor -v`
Expected: FAIL — `_run_editor` is not defined.

- [ ] **Step 3: Add _run_editor and edit_file to editor.py**

Append to `src/scriptpilot/editor.py`:

```python
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import App


def _run_editor(argv: list[str], path: Path) -> None:
    """Invoke ``argv + [path]`` synchronously. Raises ``EditorError`` if the
    binary can't be launched. Non-zero exit codes from the editor itself are
    tolerated — the caller decides what to do with whatever is on disk.
    """
    try:
        subprocess.run([*argv, str(path)], check=False)
    except FileNotFoundError as e:
        raise EditorError(f"editor '{argv[0]}' not found on PATH") from e
    except OSError as e:
        raise EditorError(f"could not launch editor '{argv[0]}': {e}") from e


def edit_file(app: "App", config: AppConfig, path: Path) -> None:
    """Suspend the Textual app, run the resolved editor on ``path``, then resume.

    Raises ``EditorError`` if no editor is available or the editor can't be launched.
    """
    argv = resolve_editor(config)
    with app.suspend():
        _run_editor(argv, path)
```

Also move the `import subprocess` line into the imports block at the top of the file (so it's not duplicated). Final imports section should be:

```python
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import App

from scriptpilot.models import AppConfig
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_editor.py -v`
Expected: PASS — all editor tests green.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/editor.py tests/test_editor.py
git commit -m "feat: editor module — _run_editor and edit_file with app.suspend"
```

---

## Task 6: `tempscript.py` — `materialize_draft`

**Files:**
- Create: `src/scriptpilot/tempscript.py`
- Test: `tests/test_tempscript.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/test_tempscript.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tempscript.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Create tempscript.py**

Create `src/scriptpilot/tempscript.py`:

```python
from __future__ import annotations

import tempfile
from pathlib import Path

from scriptpilot.paths import EXTENSIONS


def materialize_draft(content: str, script_type: str) -> Path:
    """Write ``content`` to a tempfile with the extension for ``script_type``.

    The caller is responsible for unlinking the returned path
    (``Path.unlink(missing_ok=True)`` in a ``finally``).

    Raises ``KeyError`` if ``script_type`` isn't in ``paths.EXTENSIONS`` —
    a programmer error, not a user-facing condition.
    """
    suffix = EXTENSIONS[script_type]
    fd, name = tempfile.mkstemp(suffix=suffix, prefix="scriptpilot-draft-")
    path = Path(name)
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tempscript.py -v`
Expected: PASS — all green.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/tempscript.py tests/test_tempscript.py
git commit -m "feat: tempscript module with materialize_draft"
```

---

## Task 7: MainScreen `E` binding — `action_edit_in_external`

**Files:**
- Modify: `src/scriptpilot/screens/main.py:22-30` (BINDINGS), add new method

No automated test for this screen action (existing pattern in this repo is no Textual screen tests; the editor module is unit-tested separately). Manual verification at the end.

- [ ] **Step 1: Add the E binding**

Edit `src/scriptpilot/screens/main.py`. Replace the `BINDINGS` list:

```python
BINDINGS = [
    ("n", "new_script", "New"),
    ("e", "edit_script", "Edit"),
    ("E", "edit_in_external", "Editor"),
    ("d", "delete_script", "Delete"),
    ("r", "run_script", "Run"),
    ("p", "prompt_script", "Prompt"),
    ("c", "clone_script", "Clone"),
    ("f", "toggle_favorite", "Fav"),
]
```

- [ ] **Step 2: Add the new imports**

In `src/scriptpilot/screens/main.py`, replace the existing import line for `executor` and add the editor import. Locate:

```python
from scriptpilot.executor import execute_script, InterpreterNotFoundError, ScriptCwdError
```

Add right after it:

```python
from scriptpilot.editor import edit_file, EditorError
```

- [ ] **Step 3: Add the action method**

In `src/scriptpilot/screens/main.py`, add this method to `MainScreen` (place it after `action_edit_script`):

```python
def action_edit_in_external(self):
    if not self._selected_script:
        self.notify("No script selected", severity="warning")
        return
    script = self._selected_script
    path = self._store.path_for(script.id)
    try:
        edit_file(self.app, self.app._config, path)
    except EditorError as e:
        self.notify(str(e), severity="error")
        return
    try:
        new_content = path.read_text()
    except OSError as e:
        self.notify(f"Could not reload script: {e}", severity="error")
        return
    if new_content != script.content:
        script.content = new_content
        self._store.update(script)
        self._refresh_list()
        last_run = self._get_last_run(script.id)
        self.query_one(MainPanel).show_script_details(script, last_run)
```

- [ ] **Step 4: Run full test suite (smoke check for import errors)**

Run: `uv run pytest -v`
Expected: PASS — no regressions.

- [ ] **Step 5: Manual verification**

```bash
EDITOR=vim uv run scriptpilot
```

Steps:
1. Create or select an existing script.
2. Press `Shift+E` (capital `E`).
3. App suspends, `vim` opens on the script body.
4. Add a comment line, save, quit (`:wq`).
5. App resumes; if the script is still selected, the panel reflects the new content (verify by re-pressing `e` to open the EditScreen and seeing the new line in the TextArea).

- [ ] **Step 6: Commit**

```bash
git add src/scriptpilot/screens/main.py
git commit -m "feat: MainScreen E binding opens script in \$EDITOR"
```

---

## Task 8: EditScreen `E` binding — tempfile bridge

**Files:**
- Modify: `src/scriptpilot/screens/edit.py` (BINDINGS, action method)

- [ ] **Step 1: Add the BINDINGS list and imports**

Edit `src/scriptpilot/screens/edit.py`. Add the new imports near the top (after the existing `from scriptpilot.widgets...` lines):

```python
from scriptpilot.editor import edit_file, EditorError
from scriptpilot.tempscript import materialize_draft
```

- [ ] **Step 2: Add BINDINGS to EditScreen**

In `src/scriptpilot/screens/edit.py`, add a `BINDINGS` class attribute to `EditScreen` (place it just before `DEFAULT_CSS`):

```python
class EditScreen(ModalScreen[Script | None]):
    """Modal screen for creating or editing a script."""

    BINDINGS = [
        ("E", "edit_in_external", "Editor"),
    ]

    DEFAULT_CSS = """
    ...
    """
```

- [ ] **Step 3: Add the action method**

In `src/scriptpilot/screens/edit.py`, add this method to `EditScreen` (place it right before the existing `_save` method):

```python
def action_edit_in_external(self):
    text_area = self.query_one("#content-area", TextArea)
    type_select = self.query_one("#type-select", Select)
    script_type = type_select.value
    tmp = materialize_draft(text_area.text, script_type)
    try:
        edit_file(self.app, self.app._config, tmp)
        text_area.load_text(tmp.read_text())
    except EditorError as e:
        self.notify(str(e), severity="error")
    finally:
        tmp.unlink(missing_ok=True)
```

- [ ] **Step 4: Run tests for regressions**

Run: `uv run pytest -v`
Expected: PASS.

- [ ] **Step 5: Manual verification**

```bash
EDITOR=vim uv run scriptpilot
```

Steps:
1. Press `n` to start a new script.
2. Type a partial script in the TextArea (do NOT save).
3. Press `Shift+E`.
4. Vim opens with the buffer contents on a tempfile path under `/tmp/scriptpilot-draft-*`.
5. Add a line, save, quit.
6. App returns to the EditScreen; the TextArea now reflects the new line.
7. Press Cancel — the script was never saved, so it doesn't appear in the script list.
8. `ls /tmp/scriptpilot-draft-*` — should be empty (cleaned up).

- [ ] **Step 6: Commit**

```bash
git add src/scriptpilot/screens/edit.py
git commit -m "feat: EditScreen E binding bridges draft buffer to \$EDITOR via tempfile"
```

---

## Task 9: EditScreen Run button — scratch execute with inline RichLog

**Files:**
- Modify: `src/scriptpilot/screens/edit.py` (button bar, validation refactor, Run handler, scratch_execute, CSS)

- [ ] **Step 1: Add RichLog import**

In `src/scriptpilot/screens/edit.py`, update the textual widgets import:

```python
from textual.widgets import Button, Input, Label, RichLog, Select, TextArea
```

Also add the model + executor imports needed for the scratch execute (place after the existing `from scriptpilot.widgets...` imports):

```python
from scriptpilot.executor import execute_script, InterpreterNotFoundError, ScriptCwdError
from scriptpilot.screens.run import RunScreen
```

- [ ] **Step 2: Update DEFAULT_CSS for content-area and add scratch-output**

In `src/scriptpilot/screens/edit.py`, replace the `#content-area` block in `DEFAULT_CSS` and add a `#scratch-output` block. Replace:

```css
EditScreen #content-area {
    min-height: 10;
    height: 15;
    margin-bottom: 1;
}
```

with:

```css
EditScreen #content-area {
    min-height: 10;
    height: 1fr;
    margin-bottom: 1;
}
EditScreen #scratch-output {
    display: none;
    height: 8;
    border: solid $accent;
    margin-bottom: 1;
}
EditScreen #scratch-output.visible {
    display: block;
}
EditScreen .editor-hint {
    color: $text-muted;
    margin-bottom: 1;
}
```

- [ ] **Step 3: Add the Run button to the button bar**

In `src/scriptpilot/screens/edit.py`, locate the `with Horizontal(id="button-bar"):` block in `compose`. Replace it:

```python
with Horizontal(id="button-bar"):
    yield Button("Run", id="run-btn")
    yield Button("Cancel", id="cancel-btn")
    yield Button("Save", id="save-btn", variant="primary")
```

- [ ] **Step 4: Add the hint label and scratch RichLog inside the scroll**

In `src/scriptpilot/screens/edit.py`, locate the TextArea yield in `compose`:

```python
yield TextArea(
    s.content if s else "",
    id="content-area",
    language=lang,
)
```

Add immediately after it:

```python
yield Label("[dim]Press E to edit in $EDITOR[/dim]", classes="editor-hint")
yield RichLog(id="scratch-output", highlight=True, markup=True)
```

- [ ] **Step 5: Refactor _save to share validation**

In `src/scriptpilot/screens/edit.py`, replace `_save` with a `_collect_form` helper plus a thinner `_save`:

```python
def _collect_form(self) -> Script | None:
    """Read the form into a Script. Returns None if validation fails (already notified)."""
    name = self.query_one("#name-input", Input).value.strip()
    desc = self.query_one("#desc-input", Input).value.strip()
    script_type = self.query_one("#type-select", Select).value
    content = self.query_one("#content-area", TextArea).text
    timeout_str = self.query_one("#timeout-input", Input).value.strip()
    args = self.query_one(ArgEditor).get_args()
    cwd_str = self.query_one("#cwd-input", Input).value.strip() or None
    env = self.query_one(EnvEditor).get_env()

    if not name:
        self.notify("Script name is required", severity="error")
        return None
    if not content.strip():
        self.notify("Script content is required", severity="error")
        return None

    try:
        timeout = int(timeout_str)
    except ValueError:
        timeout = 60

    if self._script:
        self._script.name = name
        self._script.description = desc
        self._script.type = script_type
        self._script.content = content
        self._script.timeout = timeout
        self._script.args = args
        self._script.cwd = cwd_str
        self._script.env = env
        return self._script

    return Script(
        name=name,
        description=desc,
        type=script_type,
        content=content,
        timeout=timeout,
        args=args,
        cwd=cwd_str,
        env=env,
    )

def _save(self):
    script = self._collect_form()
    if script is not None:
        self.dismiss(script)
```

- [ ] **Step 6: Update on_button_pressed to handle Run**

In `src/scriptpilot/screens/edit.py`, replace `on_button_pressed`:

```python
def on_button_pressed(self, event: Button.Pressed):
    if event.button.id == "cancel-btn":
        self.dismiss(None)
    elif event.button.id == "save-btn":
        self._save()
    elif event.button.id == "run-btn":
        self._scratch_run()
```

- [ ] **Step 7: Add the scratch run logic**

In `src/scriptpilot/screens/edit.py`, add these methods to `EditScreen` (after `_collect_form`):

```python
def _scratch_run(self):
    draft = self._collect_form()
    if draft is None:
        return
    # Note: _collect_form mutates self._script for existing scripts. That's
    # intentional for Save, but we DO NOT call store.update here, so the
    # in-memory mutation is only kept if the user later presses Save.

    if draft.args:
        def on_args(values: list[str] | None):
            if values is not None:
                self._scratch_execute(draft, values)

        self.app.push_screen(RunScreen(draft), callback=on_args)
    else:
        self._scratch_execute(draft, None)

def _scratch_execute(self, draft: Script, arg_values: list[str] | None):
    log = self.query_one("#scratch-output", RichLog)
    log.add_class("visible")
    log.clear()
    log.write(f"[bold]$ running draft '{draft.name}'[/bold]")

    tmp = materialize_draft(draft.content, draft.type)

    async def run():
        try:
            result = await execute_script(
                draft,
                arg_values=arg_values,
                on_output=log.write,
                script_path=tmp,
                python_command=self.app._config.python_command,
            )
            tag = "red" if result.exit_code != 0 else "green"
            status = "timed out" if result.timed_out else f"exit {result.exit_code}"
            log.write(f"[{tag}]— {status} in {result.duration:.2f}s[/]")
        except (InterpreterNotFoundError, ScriptCwdError) as e:
            log.write(f"[red]error:[/red] {e}")
            self.notify(str(e), severity="error")
        except Exception as e:
            log.write(f"[red]error:[/red] {e}")
            self.notify(str(e), severity="error")
        finally:
            tmp.unlink(missing_ok=True)

    self.run_worker(run(), name="scratch-execute", exclusive=True)
```

- [ ] **Step 8: Run full test suite**

Run: `uv run pytest -v`
Expected: PASS — no regressions.

- [ ] **Step 9: Manual verification**

```bash
uv run scriptpilot
```

Steps:
1. Press `n` to start a new bash script.
2. Name it `scratch-test`, content `echo "hello $1"; exit 0`.
3. Add an arg `name` (string, required, default `world`).
4. Click **Run** — `RunScreen` appears with the `name` field defaulted to `world`. Click Run there.
5. The scratch output area appears below the TextArea with `hello world` and `— exit 0` line.
6. Click Cancel on the EditScreen — the script does not appear in the list.
7. Repeat with content that exits 1: scratch output shows `[red]— exit 1[/red]`.
8. Repeat with a missing interpreter (e.g., temporarily set type=js and rename `node` out of PATH) — error notification + red error in scratch output. Tempfile cleaned up.

- [ ] **Step 10: Commit**

```bash
git add src/scriptpilot/screens/edit.py
git commit -m "feat: EditScreen scratch Run with inline RichLog and tempfile"
```

---

## Task 10: SettingsScreen — editor / theme / scripts_dir

**Files:**
- Modify: `src/scriptpilot/screens/settings.py`

- [ ] **Step 1: Update imports**

In `src/scriptpilot/screens/settings.py`, replace the textual widgets import:

```python
from textual.widgets import Button, Input, Label, Select
```

(Adds `Select`.)

- [ ] **Step 2: Update compose with new fields**

In `src/scriptpilot/screens/settings.py`, replace the entire `compose` method:

```python
def compose(self) -> ComposeResult:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
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
        yield Label(f"OpenRouter API Key: {key_status}")
        yield Label("[dim]Set via OPENROUTER_API_KEY environment variable[/dim]")
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
        yield Label(
            "[dim]edit ~/.scriptpilot/config.json to change[/dim]"
        )
        yield Label(f"Secrets file: {SECRETS_PATH} [{secrets_status}]")
        yield Label(
            "[dim]One KEY=VALUE per line. Edit with your editor.[/dim]"
        )
        with Horizontal(id="button-bar"):
            yield Button("Cancel", id="cancel-btn")
            yield Button("Save", id="save-btn", variant="primary")
```

- [ ] **Step 3: Update the save handler**

In `src/scriptpilot/screens/settings.py`, replace `on_button_pressed`:

```python
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
            default_model=model or "openai/gpt-4o",
            python_command=python_cmd,
            editor=editor_val,
            theme=theme_val,
            scripts_dir=self._config.scripts_dir,
        )
        self.dismiss(config)
```

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest -v`
Expected: PASS.

- [ ] **Step 5: Manual verification**

```bash
uv run scriptpilot
```

Steps:
1. Press `s` for Settings.
2. Verify all fields are visible: Default Model, Python command, Editor command, Theme (Select), Scripts dir (read-only label), Secrets file.
3. Set Editor command to `nvim`. Save. Notify "Settings saved".
4. `cat ~/.scriptpilot/config.json` — confirm `"editor": "nvim"`.
5. Re-open Settings. Change Theme to Light. Save. App switches to light theme.
6. Quit. Re-launch — light theme. Settings still shows `nvim`.
7. Manually edit `config.json` to add `"scripts_dir": "/tmp/sp-test"`. Re-launch. Settings now shows `Scripts dir: /tmp/sp-test`.
8. Press `Shift+E` on a script — `nvim` is invoked (confirms editor field is honored).

- [ ] **Step 6: Commit**

```bash
git add src/scriptpilot/screens/settings.py
git commit -m "feat: SettingsScreen exposes editor, theme, and read-only scripts_dir"
```

---

## Task 11: Final manual acceptance walkthrough

**Files:** none — this is a pure verification step.

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: PASS — all green.

- [ ] **Step 2: Walk through every spec acceptance criterion**

```bash
uv run scriptpilot
```

Verify each of these against the spec:

1. **MainScreen E reload:** Select any script, press `Shift+E`, edit in `$EDITOR`, save+quit → panel reflects new content. Select something else, then back — content persisted (`store.update` worked).
2. **EditScreen E roundtrip:** Press `n` → type partial content → press `Shift+E` → edit → save+quit → TextArea has new content. Cancel — script not in list.
3. **Scratch Run:**
   - Without args: open EditScreen on existing or new script → click Run → output streams to `#scratch-output`. Cancel — script not modified or added.
   - With required args: click Run → `RunScreen` appears → enter values → execute → output streams. Cancel out of `RunScreen` → no execution; back to EditScreen unchanged.
4. **Theme persistence:**
   - Press `t` → flip → quit → re-launch → starts in toggled theme.
   - Settings → change Theme dropdown → Save → app switches immediately. Quit/re-launch → persists.
5. **AppConfig completeness:** `cat ~/.scriptpilot/config.json` shows all five fields: `default_model`, `python_command`, `editor`, `scripts_dir`, `theme`.
6. **CSS polish:** `#content-area` fills available modal height. Hint label `Press E to edit in $EDITOR` visible below TextArea.
7. **scripts_dir override:** Edit `config.json` to point `scripts_dir` at a fresh dir. Re-launch. List is empty (or matches that dir). Settings shows the new path read-only.

- [ ] **Step 3: If any check fails, file follow-up commit(s) and re-run from Step 1**

Common gotchas to check first when something fails:
- `Shift+E` not registering on some terminals → confirm Textual's `BINDINGS = [("E", ...)]` matches; if not, fall back to a different key like `o` (and update spec).
- `app.suspend()` not restoring terminal cleanly → confirm subprocess uses default stdin/stdout/stderr (no PIPE).
- Scratch output not visible → check `display: block` toggle on `#scratch-output.visible`.
- Theme not persisting → confirm `_save_config` writes the new field; check JSON.

- [ ] **Step 4: Final commit (if any docs / nits remain)**

If everything passes, no final commit needed. Otherwise commit the fixups with descriptive messages.

---

## Self-Review Notes (author)

1. **Spec coverage:**
   - § Architecture / new modules → Tasks 4–6.
   - § AppConfig fields → Task 1.
   - § App init/on_mount/toggle → Tasks 2–3.
   - § MainScreen E → Task 7.
   - § EditScreen E → Task 8.
   - § EditScreen Run → Task 9.
   - § SettingsScreen → Task 10.
   - § CSS polish + hint label → Task 9 step 2/4 (folded into the Run task because they touch the same `compose`/`DEFAULT_CSS`).
   - § Tests (test_editor, test_tempscript, extend test_models, test_app_config) → Tasks 1, 2, 3, 4, 5, 6.
   - § Manual acceptance walkthrough → Task 11.

2. **Placeholder scan:** No TBD/TODO/"add appropriate". Every code step has full code; every test step has full test code; every command has expected output.

3. **Type / signature consistency:**
   - `EditorError` defined in Task 4, used in Tasks 5/7/8. ✓
   - `resolve_editor(config: AppConfig) -> list[str]` defined in Task 4, called in Task 5 (`edit_file`). ✓
   - `_run_editor(argv: list[str], path: Path)` Task 5, used by `edit_file`. ✓
   - `edit_file(app, config, path)` Task 5, called in Tasks 7/8. ✓
   - `materialize_draft(content: str, script_type: str) -> Path` Task 6, called in Tasks 8/9. ✓
   - `Script` constructor args (Task 9 `_collect_form`) match the existing model in `models.py`. ✓
   - `RichLog.add_class("visible")` matches the CSS rule `#scratch-output.visible`. ✓

No issues to fix.
