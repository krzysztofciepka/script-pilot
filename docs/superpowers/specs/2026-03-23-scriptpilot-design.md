# ScriptPilot TUI — Design Spec

## Overview

ScriptPilot is a terminal UI application that lets users create, manage, and execute automation scripts (bash, Python, JavaScript) with optional AI-powered script generation via OpenRouter.

**Runtime:** Python 3.10+
**TUI Framework:** Textual
**Packaging:** uv with pyproject.toml
**Installable as:** `scriptpilot` CLI command via `[project.scripts]` entry point

---

## Data Models & Storage

### Pydantic Models (`models.py`)

**ScriptArg:**
- `name: str`
- `type: Literal["string", "boolean", "integer"]`
- `required: bool = True`
- `default: str | bool | int | None = None`

**Script:**
- `id: str` — uuid4
- `name: str`
- `description: str`
- `type: Literal["bash", "python", "js"]`
- `content: str` — script source stored inline
- `args: list[ScriptArg] = []`
- `timeout: int = 60`

**AppConfig:**
- `default_model: str = "openai/gpt-4o"`

### Storage (`storage.py`)

- `ScriptStore` class wrapping `~/.scriptpilot/scripts.json`
- CRUD: `list()`, `get(id)`, `add(script)`, `update(script)`, `delete(id)`
- Atomic writes (write to temp file, then rename) to prevent corruption
- Creates `~/.scriptpilot/` on first run

### Key Decision: Inline Content

Script content is stored inline in `scripts.json`, not as file path references. Scripts are written to temp files for execution. This eliminates orphaned file references and the "invalid script path" error class entirely.

**PRD deviation:** The PRD stores scripts as file path references with a `"path"` field. Inline storage supersedes this, making the PRD's "Invalid script path → Remove from list, show warning" error case no longer applicable.

### API Key

Read from `OPENROUTER_API_KEY` environment variable. No config file storage.

**PRD deviation:** The PRD includes an editable API key field in settings. This spec uses an environment variable instead because: (1) it follows the standard convention used by OpenAI, Anthropic, and other API providers, (2) it avoids storing secrets in plaintext config files, and (3) it's simpler to implement. The settings screen shows whether the env var is set so users know if AI features are available.

### Dependencies for Executed Scripts

Scripts are assumed to be self-contained. No dependency management (no pip install, npm install, etc.) for executed scripts. Users are responsible for having dependencies installed in their environment.

---

## Script Execution (`executor.py`)

Single async function `execute_script()`:

1. Writes script content to temp file with appropriate extension (`.sh`, `.py`, `.js`)
2. Sets executable permission for bash scripts
3. Validates interpreter on PATH via `shutil.which("bash"/"python3"/"node")` — returns clear error if missing
4. Spawns via `asyncio.create_subprocess_exec` with correct interpreter
5. Streams stdout/stderr line-by-line to UI via callback (real-time output)
6. Enforces per-script timeout — kills process, returns timeout error
7. Returns result: `exit_code`, `timed_out`, `duration`
8. Cleans up temp file after execution

### Argument Injection

Arguments passed as positional args to subprocess after script path:
- `bash /tmp/script.sh arg1 arg2`
- `python3 /tmp/script.py arg1 arg2`
- `node /tmp/script.js arg1 arg2`

Boolean args passed as `"true"/"false"` strings.

---

## OpenRouter Integration (`openrouter.py`)

### OpenRouterClient

Async client using `httpx`:

- `generate_script(description: str, language: str, model: str) -> str` — returns generated script content
- `list_models() -> list[dict]` — fetches available models from `/api/v1/models`

### System Prompt

Instructs the model to output only executable code with brief comments, no markdown fences, no explanation. Response parser strips markdown fences if present anyway.

### No Streaming

Generated scripts are typically short. Simple spinner in UI while waiting. No streaming of partial code.

### Error Types

- Missing/invalid API key → `AuthenticationError`
- Rate limit → `RateLimitError` with retry-after
- Network/timeout → `ConnectionError`

---

## UI Architecture

### App (`app.py`)

Textual `App` subclass. Global key bindings: `q` (quit), `s` (settings), `g` (generate), `n` (new script). Loads scripts from `ScriptStore` on startup. Supports light/dark themes via Textual's built-in `toggle_dark()`, bound to `t` key.

### Main Screen (`screens/main.py`)

Three-panel layout:

- **Left panel** — `ScriptList` widget: `ListView` of saved scripts. `j/k`/arrows to navigate. Shows name and type. `+ New` entry at bottom.
- **Right panel** — `MainPanel` widget, contextual:
  - No selection: welcome/empty state
  - Script selected: name, description, type, args summary, timeout
  - Script running: real-time output (`RichLog`)
  - Script finished: output + exit code/duration footer
- **Bottom bar** — `[Enter/r] Run  [e] Edit  [d] Delete  [g] Generate  [n] New  [s] Settings  [t] Theme  [q] Quit`
- `Tab` switches focus between panels
- `d` shows confirmation dialog before deleting

### Settings Screen (`screens/settings.py`)

Modal screen (overlays main):
- Default model (select from fetched model list)
- API key status indicator (shows whether env var is set, not editable)
- Save/Cancel buttons

### Generate Screen (`screens/generate.py`)

Modal screen:
- Description `TextArea`, language `Select` (bash/python/js)
- Submit → spinner → generated code in editable `TextArea`
- "Save" prompts for name and description
- "Retry" to regenerate, "Cancel" to discard

### Run Screen (`screens/run.py`)

Modal that appears when executing a script that has defined arguments:
- Displays script name at top
- For each arg: labeled input field, pre-filled with default value if set
- Required args validated before allowing submission
- Boolean args rendered as checkboxes/switches
- "Run" and "Cancel" buttons
- If script has no args, this modal is skipped — execution starts immediately

### Edit/Create Screen (`screens/edit.py`)

Modal screen for both new (`n`) and edit (`e`):
- Name `Input`, description `Input`, type `Select`, timeout `Input`, content `TextArea`
- Args editor: add/remove rows with name, type, required, default fields
- Save/Cancel buttons

**PRD deviation — editor preference:** The PRD includes an "editor preference" setting for manual edits. Since this spec uses an inline TextArea for all editing (no external editor launch), this setting is not applicable and is intentionally omitted.

---

## Error Handling

### Execution
- Interpreter not found → toast: "Python3/Node/Bash not found on PATH", script doesn't run
- Timeout → process killed, output shows "Script timed out after Xs" in red
- Non-zero exit → output shown, exit code in red/yellow
- Zero exit → exit code in green

### OpenRouter
- No API key → generate screen shows "Set OPENROUTER_API_KEY environment variable", submit disabled
- Auth failure → toast: "Invalid API key"
- Network error → toast: "Could not reach OpenRouter", retry active
- Rate limit → toast: "Rate limited, try again in Xs"

### Storage
- Corrupted JSON → backup as `.bak`, start empty, warning toast
- Disk write failure → toast: "Failed to save", preserve in-memory state

### UI Edge Cases
- Empty list → "No scripts yet. Press [n] to create one or [g] to generate with AI"
- Long output → `RichLog` scrollback capped at 10,000 lines
- Concurrent execution → disabled, toast explains only one script at a time

---

## Project Structure

```
script-pilot/
├── pyproject.toml
├── src/
│   └── scriptpilot/
│       ├── __init__.py
│       ├── __main__.py         # python -m scriptpilot support
│       ├── app.py              # Textual App, key bindings, entry point
│       ├── models.py           # Pydantic models
│       ├── storage.py          # ScriptStore — JSON CRUD
│       ├── executor.py         # Script execution
│       ├── openrouter.py       # OpenRouter API client
│       ├── screens/
│       │   ├── __init__.py
│       │   ├── main.py         # Main three-panel screen
│       │   ├── settings.py     # Settings modal
│       │   ├── generate.py     # AI generation modal
│       │   ├── edit.py         # Script create/edit modal
│       │   └── run.py          # Argument input modal
│       └── widgets/
│           ├── __init__.py
│           ├── script_list.py  # Left panel list
│           ├── main_panel.py   # Right panel
│           └── arg_editor.py   # Argument list editor
└── tests/
    ├── test_models.py
    ├── test_storage.py
    ├── test_executor.py
    └── test_openrouter.py
```

### Dependencies

**Runtime:**
- `textual>=0.80`
- `httpx>=0.27`
- `pydantic>=2.0`

**Dev:**
- `pytest`
- `pytest-asyncio`

### Entry Point

`[project.scripts]` → `scriptpilot = "scriptpilot.app:main"`
`__main__.py` calls same `main()` for `python -m scriptpilot`

### Testing

`models.py`, `storage.py`, `executor.py`, `openrouter.py` are plain Python — tested with pytest without Textual dependency. UI tests deferred to manual testing for v1.

---

## Navigation Reference

| Key | Action |
|-----|--------|
| j/k, arrows | Navigate script list |
| Enter, r | Execute selected script (shows arg form if script has args) |
| e | Edit selected script |
| d | Delete selected script |
| n | New manual script |
| g | Generate script with AI |
| s | Open settings |
| t | Toggle light/dark theme |
| q | Quit |
| Tab | Switch focus between panels |
