# Script-Pilot Improvements Design

## Overview

Enhance the script-pilot TUI with prompt-based script modification, automatic argument extraction, quality-of-life features (clone, favorites, run history), and a single-binary distribution for Linux.

## 1. Structured LLM Response Format

Foundation for both generation and modification flows.

### System Prompt

Replace the current `SYSTEM_PROMPT` in `openrouter.py` with one that instructs the LLM to always output two fenced blocks:

1. A code block fenced with the script language (````bash`, ````python`, or ````javascript`)
2. A JSON block containing argument definitions

Example expected output:

````
```bash
#!/bin/bash
for f in "$1"/*.{jpg,png}; do
  convert "$f" -rotate "$2" "$f"
done
```

```json
{"args": [{"name": "directory", "type": "string", "required": true, "default": ""}, {"name": "degrees", "type": "integer", "required": false, "default": "90"}]}
```
````

### GenerationResult

New dataclass in `openrouter.py`:

```python
@dataclass
class GenerationResult:
    code: str
    args: list[ScriptArg]
```

Returned by both `generate_script` and `modify_script`.

### Response Parser

`parse_generation_response(text: str) -> GenerationResult` in `openrouter.py`:

1. Extract the first fenced code block as the script code.
2. Extract a fenced block containing valid JSON with an `"args"` key.
3. Validate each arg entry against `ScriptArg` via Pydantic.
4. If parsing fails at any step, raise `MalformedResponseError`.

### Retry Logic

Both `generate_script` and `modify_script` attempt the API call up to 3 times. On `MalformedResponseError`, retry with the same prompt. After 3 failures, raise to caller.

## 2. Prompt-to-Modify

### OpenRouterClient.modify_script

New async method: `modify_script(current_code: str, instruction: str, language: str, model: str) -> GenerationResult`

- System prompt: instructs the LLM that it is modifying an existing script; must output the complete updated script (not a diff) plus args JSON in the structured format.
- User message: includes the full current script code and the user's modification instruction.
- Uses `parse_generation_response` and the retry logic.

### PromptScreen

New file: `screens/prompt.py`

`PromptScreen(ModalScreen[Script | None])`:

- Constructor takes the current `Script` and `default_model: str`.
- Layout:
  - Label showing current script name
  - TextArea for the modification instruction
  - Buttons: Cancel, Submit
- On Submit: runs `modify_script` in a worker, then shows a preview of the updated code in a read-only TextArea.
- After preview, buttons change to: Cancel, Accept.
- Accept: creates updated `Script` with new code and auto-extracted args, dismisses with it.
- Cancel at any point: dismisses with `None`.

### Keybinding

`("p", "prompt_script", "Prompt")` in `MainScreen.BINDINGS`.

`action_prompt_script`:
1. Checks `_selected_script` is not `None`.
2. Pushes `PromptScreen(selected_script, default_model)`.
3. Callback: updates store, refreshes list and detail panel (same pattern as `action_edit_script`).

The model config is passed as `default_model` to `PromptScreen` constructor (same pattern as `GenerateScreen`).

## 3. Auto-Args in Generation Flow

### generate_script Changes

- Return type changes from `str` to `GenerationResult`.
- Uses the new system prompt (structured format).
- Response parsed via `parse_generation_response` with retry.

### GenerateScreen Changes

- `_generate` returns `GenerationResult` instead of raw string.
- Result area displays `result.code`.
- `_do_save` creates `Script` with `args=result.args`.
- The `GenerationResult` is stored as instance state (e.g., `self._result`) between generation and save.

### Backward Compatibility

The `ArgEditor` widget in `EditScreen` remains unchanged. Users can manually adjust auto-extracted args via the edit flow.

## 4. Script Cloning

### Keybinding

`("c", "clone_script", "Clone")` in `MainScreen.BINDINGS`.

### action_clone_script

1. Checks `_selected_script` is not `None`.
2. Creates new `Script`:
   - Copies `content`, `type`, `args`, `timeout`, `description` from selected.
   - Sets `name = "{original.name} (copy)"`.
   - Leaves `id = ""` so `model_post_init` generates a new UUID.
   - Sets `favorite = False`.
3. Adds to store via `_store.add(script)`.
4. Refreshes list.
5. Notifies: `"Cloned '{name}'"`.

No modal dialog needed.

## 5. Favorites

### Model Change

Add `favorite: bool = False` to the `Script` model in `models.py`.

Pydantic defaults handle backward compatibility: existing `scripts.json` files without the field load with `favorite=False`.

### Keybinding

`("f", "toggle_favorite", "Fav")` in `MainScreen.BINDINGS`.

### action_toggle_favorite

1. Checks `_selected_script` is not `None`.
2. Creates updated `Script` with `favorite` toggled.
3. Updates store, refreshes list, updates detail panel.
4. Notifies: `"Favorited '{name}'"` or `"Unfavorited '{name}'"`.

### List Sorting

In `ScriptList.update_scripts` and `compose`, sort scripts: favorites first, then non-favorites. Preserve insertion order within each group.

### Display

Favorited scripts show a star in the list: `[SH] * My Script`.

Non-favorited: `[SH] My Script` (no change).

## 6. Run History

### RunRecord Model

New Pydantic model (in `models.py`):

```python
class RunRecord(BaseModel):
    script_id: str
    script_name: str
    timestamp: str  # ISO 8601
    exit_code: int
    timed_out: bool
    duration: float
    output: str  # full stdout/stderr
```

`script_name` is denormalized so history remains readable if the script is deleted.

### HistoryStore

New class in `history.py`:

- Path: `~/.scriptpilot/history.json`
- `add(record: RunRecord)`: appends record, evicts oldest if count exceeds 100, persists.
- `list_for_script(script_id: str) -> list[RunRecord]`: returns runs for a script, newest first.
- `list_all() -> list[RunRecord]`: all runs, newest first.
- Uses atomic writes (same tempfile+rename pattern as `ScriptStore`).

Cap: 100 records total. Oldest evicted on add.

### Integration

In `MainScreen._execute`:

1. Wrap `panel.append_output` in a collector that both streams to the panel and accumulates lines into a list.
2. After `execute_script` completes, join collected lines into a single output string.
3. Create `RunRecord` with script ID, name, ISO timestamp, exit code, timed_out, duration, output.
4. Add to `HistoryStore`.

### Display

In `MainPanel.show_script_details`, add a "Last run" line below existing details showing: timestamp, exit code, duration -- pulled from the most recent `RunRecord` for that script via `HistoryStore.list_for_script`.

### Initialization

`HistoryStore` instantiated in `ScriptPilotApp.__init__` alongside `ScriptStore`. Passed to `MainScreen` constructor.

## 7. Single Binary (PyInstaller, Linux)

### Build Tool

PyInstaller with `--onefile` mode.

### Build Script

`scripts/build.sh`:

1. Installs PyInstaller via `uv pip install pyinstaller`.
2. Runs: `pyinstaller --onefile --name scriptpilot src/scriptpilot/__main__.py`
3. Handles hidden imports for `textual`, `httpx`, `pydantic` as needed.
4. Output: `dist/scriptpilot`.

### GitHub Actions

`.github/workflows/build.yml`:

- Triggers on release tag push (e.g., `v*`).
- Runs on `ubuntu-latest`.
- Steps: checkout, install uv, sync deps, install PyInstaller, build, upload binary as release asset.

### Dev Dependency

Add `pyinstaller` to dev dependencies in `pyproject.toml`.

### End-User Install

Download from GitHub releases and place on PATH:

```bash
curl -fsSL https://github.com/krzysztofciepka/script-pilot/releases/latest/download/scriptpilot -o /usr/local/bin/scriptpilot && chmod +x /usr/local/bin/scriptpilot
```

## File Change Summary

| File | Change |
|------|--------|
| `models.py` | Add `favorite` field to `Script`, add `RunRecord` model |
| `openrouter.py` | New system prompt, `GenerationResult` dataclass, `parse_generation_response`, `MalformedResponseError`, `modify_script` method, retry logic, update `generate_script` return type |
| `history.py` (new) | `HistoryStore` class |
| `screens/prompt.py` (new) | `PromptScreen` modal |
| `screens/generate.py` | Handle `GenerationResult`, auto-populate args on save |
| `screens/main.py` | New bindings (`p`, `c`, `f`), new actions, output collection for history, pass `HistoryStore` |
| `widgets/script_list.py` | Sort favorites first, star display |
| `widgets/main_panel.py` | Show last run info in script details |
| `app.py` | Instantiate `HistoryStore`, pass to `MainScreen`, wire `p` keybinding model config |
| `scripts/build.sh` (new) | PyInstaller build script |
| `.github/workflows/build.yml` (new) | CI workflow for binary builds |
| `pyproject.toml` | Add `pyinstaller` dev dependency |
