# ScriptPilot — Authoring UX

**Status:** Design
**Date:** 2026-05-01

## Problem

The in-modal `TextArea` in `EditScreen` is fine for tweaks but painful for real script authoring. Adopt the lazygit/k9s pattern: the TUI is a launcher, the editor is the editor.

## Goals

1. Authoring jumps out to `$EDITOR` on a single keystroke, both for saved scripts and for in-progress drafts.
2. Drafts can be executed without persisting them to the script list.
3. `AppConfig` becomes the single source of truth for user preferences, including theme.
4. Minor TUI polish removes the cramped feel of the EditScreen content area.

## Non-Goals

- No history recording for scratch / unsaved runs.
- No live rebuild of `ScriptStore` when `scripts_dir` changes — restart-required is acceptable.
- No automated Textual screen / snapshot tests; logic is extracted into modules and unit-tested.

## Architecture

Two new small modules and three small surgical changes to existing modules.

### New: `src/scriptpilot/editor.py`

External-editor concerns live here:

- `EditorError(Exception)` — raised when no editor is available or the editor cannot be invoked.
- `resolve_editor(config: AppConfig) -> list[str]` — picks `config.editor` → `$VISUAL` → `$EDITOR` → `vi`, returns `shlex.split` argv. Raises `EditorError` if even `vi` is not on `PATH`.
- `edit_file(app: App, config: AppConfig, path: Path) -> None` — wraps `app.suspend()`, runs the editor synchronously via `subprocess.run([*argv, str(path)], check=False)`, surfaces `FileNotFoundError` as `EditorError`. Non-zero editor exit codes are tolerated silently — the caller still reads whatever is on disk.
- Internal helper `_run_editor(argv: list[str], path: Path) -> None` factored out so tests can exercise it without entering an `app.suspend()` context.

### New: `src/scriptpilot/tempscript.py`

Tempfile boilerplate shared by the EditScreen `E` bridge and the scratch-run flow:

- `materialize_draft(content: str, script_type: str) -> Path` — uses `tempfile.NamedTemporaryFile(delete=False, suffix=EXTENSIONS[script_type], mode="w", encoding="utf-8")` (extension from `paths.EXTENSIONS`). Caller is responsible for `unlink(missing_ok=True)` in a `finally`.

### Changes: `src/scriptpilot/models.py`

Three new fields on `AppConfig`:

```python
class AppConfig(BaseModel):
    default_model: str = "openai/gpt-4o"
    python_command: str = "uv run --script"
    editor: str | None = None
    scripts_dir: str | None = None
    theme: Literal["dark", "light"] = "dark"
```

`python_command` already exists from a prior task. Loading an older config file missing the new fields falls back to defaults (Pydantic behavior).

### Changes: `src/scriptpilot/app.py`

- `__init__`: after `self._config = self._load_config()`, compute `scripts_path = Path(self._config.scripts_dir).expanduser() if self._config.scripts_dir else None` and pass to `ScriptStore(path=scripts_path)`.
- `on_mount`: set `self.dark = (self._config.theme == "dark")` before pushing `MainScreen`.
- Override `action_toggle_dark`:
  ```python
  def action_toggle_dark(self):
      super().action_toggle_dark()
      self._config.theme = "dark" if self.dark else "light"
      try:
          self._save_config()
      except Exception as e:
          self.notify(f"Could not save theme: {e}", severity="error")
  ```
- `action_open_settings` callback: when settings change, reapply `self.dark` from the new theme value. `scripts_dir` change is **not** applied live (restart required).

### Changes: `src/scriptpilot/screens/main.py`

New binding `("E", "edit_in_external", "Editor")` (uppercase, distinct from the existing lowercase `e` for in-app Edit).

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

### Changes: `src/scriptpilot/screens/edit.py`

New binding `("E", "edit_in_external", "Editor")` scoped to the modal.

```python
def action_edit_in_external(self):
    text_area = self.query_one("#content-area", TextArea)
    type_select = self.query_one("#type-select", Select)
    tmp = materialize_draft(text_area.text, type_select.value)
    try:
        edit_file(self.app, self.app._config, tmp)
        text_area.load_text(tmp.read_text())
    except EditorError as e:
        self.notify(str(e), severity="error")
    finally:
        tmp.unlink(missing_ok=True)
```

New "Run" button in `#button-bar` (between Cancel and Save). Action:

1. Validate name + content (extract existing `_validate()` returning `(ok, draft_script)` to share with `_save`).
2. Build a transient `Script(...)` from the form values — **never** call `store.add` / `store.update`.
3. `tmp = materialize_draft(draft.content, draft.type)` in a `try/finally`.
4. If `draft.args`: `app.push_screen(RunScreen(draft), callback=lambda values: self._scratch_execute(draft, values, tmp))`.
   Else: `self._scratch_execute(draft, None, tmp)` directly.
5. `_scratch_execute` runs `execute_script(...)` in a worker (mirrors `MainScreen._execute`) but writes output to an inline `RichLog` widget instead of `MainPanel`, and writes nothing to `HistoryStore`.

CSS changes:

- `#content-area` becomes `min-height: 10; height: 1fr;` (replaces `height: 15`).
- New `#scratch-output` `RichLog` widget below the TextArea: `display: none` by default; toggled on when a scratch run starts; `height: 8` or so.

New `Label` after the TextArea: `[dim]Press E to edit in $EDITOR[/dim]`.

`#button-bar` gains a third button:

```python
yield Button("Run", id="run-btn")
yield Button("Cancel", id="cancel-btn")
yield Button("Save", id="save-btn", variant="primary")
```

### Changes: `src/scriptpilot/screens/settings.py`

Three new fields in the form:

```python
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
yield Label(f"Scripts dir: {self._scripts_dir_display()}")
yield Label("[dim]edit ~/.scriptpilot/config.json to change[/dim]")
```

`_scripts_dir_display()` returns `config.scripts_dir or "~/.scriptpilot/scripts (default)"`.

The save handler builds:

```python
editor_val = self.query_one("#editor-input", Input).value.strip() or None
theme_val = self.query_one("#theme-select", Select).value
config = AppConfig(
    default_model=model or "openai/gpt-4o",
    python_command=python_cmd,
    editor=editor_val,
    theme=theme_val,
    scripts_dir=self._config.scripts_dir,  # preserved; not editable in UI
)
```

## Data Flow

### Flow A — `E` on MainScreen (saved script)

```
User presses E
  → MainScreen.action_edit_in_external
  → path = store.path_for(script.id)
  → editor.edit_file(app, config, path)
       └─ with app.suspend():
              subprocess.run([*resolve_editor(config), str(path)], check=False)
  → on return: new_content = path.read_text()
  → if new_content != script.content:
        script.content = new_content
        store.update(script)
        refresh ScriptList + MainPanel
```

### Flow B — `E` inside EditScreen (draft buffer)

```
User presses E
  → EditScreen.action_edit_in_external
  → tmp = tempscript.materialize_draft(buffer, script_type)
  → try:
        editor.edit_file(app, config, tmp)
        TextArea.load_text(tmp.read_text())
    finally:
        tmp.unlink(missing_ok=True)
```

### Flow C — Scratch Run inside EditScreen

```
User clicks "Run"
  → validate() — same as Save
  → build transient Script (no store calls)
  → tmp = materialize_draft(content, type)
  → if draft.args: push RunScreen(draft) for arg values
  → execute_script(draft, arg_values, on_output=scratch_log.write,
                   script_path=tmp,
                   python_command=app._config.python_command)
  → finally: tmp.unlink(missing_ok=True)
  → no HistoryStore write
```

### Flow D — Theme toggle persistence

```
User presses t
  → App.action_toggle_dark
  → super().action_toggle_dark()  # flips self.dark
  → self._config.theme = "dark" if self.dark else "light"
  → self._save_config()
```

## Error Handling

| Surface | Failure | Behavior |
|---|---|---|
| `resolve_editor` | No editor (incl. `vi`) on PATH | Raise `EditorError("no editor found on PATH (tried: ...)")` |
| `edit_file` | Editor binary not found | Catch `FileNotFoundError`, raise `EditorError("editor '<name>' not found on PATH")` |
| `edit_file` | Editor exits non-zero | Treated as success; caller still reads file |
| MainScreen `E` | No script selected | `notify("No script selected", severity="warning")` |
| MainScreen `E` | `EditorError` | `notify(str(e), severity="error")`; in-memory script untouched |
| MainScreen `E` | Disk read fails after edit | `notify("Could not reload script: <err>", severity="error")` |
| EditScreen `E` | `EditorError` | Notify; TextArea untouched; tempfile cleaned up |
| EditScreen Run | Validation fails | Notify (existing pattern); no execution |
| EditScreen Run | `InterpreterNotFoundError` / `ScriptCwdError` | Notify + write to `#scratch-output` RichLog |
| EditScreen Run | Any executor exception | Notify + RichLog; tempfile cleanup in `finally` |
| `materialize_draft` | Unknown `script_type` | `KeyError` propagates (programmer error) |
| `action_toggle_dark` | `_save_config` raises | Notify error; `self.dark` stays toggled for the session |

## Testing

### `tests/test_editor.py` (new)

- `resolve_editor` priority: `config.editor="code --wait"` returns `["code", "--wait"]`.
- `resolve_editor` falls through `$VISUAL` → `$EDITOR` → `vi` (`monkeypatch` env).
- `resolve_editor` with all sources missing and `vi` absent (mock `shutil.which` to return `None`) raises `EditorError`.
- `_run_editor` raises `EditorError` when binary not found (use `nonexistent_editor_xyz`).
- `_run_editor` writes via fake editor: a one-line shell script that appends a marker; verify the target file gains the marker.
- `_run_editor` tolerates non-zero exit code (fake editor `exit 1`).

### `tests/test_tempscript.py` (new)

- `materialize_draft("echo hi", "bash")` → file with `.sh` extension, contents `echo hi`, exists, in `tempfile.gettempdir()`.
- Same for `python` (`.py`) and `js` (`.js`).
- Caller cleanup works: file is removed after `unlink(missing_ok=True)`.

### `tests/test_models.py` (extend)

- `AppConfig()` has `editor is None`, `scripts_dir is None`, `theme == "dark"`.
- `AppConfig(theme="purple")` raises `pydantic.ValidationError`.

### `tests/test_app_config.py` (new)

- Round-trip: write config dict with custom theme / editor / scripts_dir → load → values preserved.
- Loading older config (missing `editor`, `theme`, `scripts_dir`) → defaults applied.
- App `__init__` with `scripts_dir="~/foo"` (mocked) → `ScriptStore` constructed with the expanded path. (Use a `tmp_path` fixture; spy on `ScriptStore.__init__`.)

### Manual acceptance walkthrough

Documented here; not automated.

1. Press `E` on a selected script → `nvim` opens; save+quit returns to TUI with new content visible.
2. Open EditScreen for an existing script, press `E` → vim opens with current draft; save+quit returns; TextArea reflects the edits.
3. EditScreen → enter args, click Run → RunScreen prompts; output streams in inline log; close modal → script not in list.
4. Toggle theme with `t`, quit, relaunch → starts in toggled theme.
5. Settings → change Theme to Light → save → app switches immediately; relaunches Light.
6. Edit `~/.scriptpilot/config.json` to set `scripts_dir`, relaunch → scripts load from new dir; Settings shows the path read-only.

## Out of Scope (Confirmed)

- No history records for scratch runs.
- No live rebuild of `ScriptStore` on `scripts_dir` change.
- No editing of `scripts_dir` from `SettingsScreen`.
- No Textual screen / snapshot tests.

## Acceptance Criteria

- Pressing `E` on a selected script in MainScreen opens the script in `$EDITOR`; save+quit returns to TUI with the new content visible.
- Pressing `E` inside EditScreen round-trips the buffer through `$EDITOR`.
- The "Run" button in EditScreen executes the unsaved draft (prompting for args via `RunScreen` when needed) without writing to the store or history; "Cancel" still discards the draft.
- Theme set via `t` or via `SettingsScreen` survives a quit + relaunch.
- `AppConfig` exposes `editor`, `python_command`, `scripts_dir`, `theme`, `default_model`.
- `#content-area` fills available modal height; a `Press E to edit in $EDITOR` hint label is visible.
