# ScriptPilot — Output Handling

**Status:** Design
**Date:** 2026-05-04

## Problem

ScriptPilot's output flow is a one-way trip to the screen. Output is in-memory only (`RichLog` with `max_lines=10000` in `src/scriptpilot/widgets/main_panel.py:42`), stderr is silently merged into stdout (`src/scriptpilot/executor.py:97`), and there is no way to keep what just appeared on screen. After a 30-second transform that produced JSON or a transformed CSV preview, the next thing the user wants is to inspect or save it.

This task adds:

1. Save / copy bindings on the displayed run.
2. Stderr separation, captured chronologically and styled distinctly in the UI.
3. A pretty JSON viewer for runs that produce JSON.
4. A `SCRIPTPILOT_OUTPUT_DIR` env-var convention for scripts that want to drop artifacts somewhere predictable.

## Goals

1. After a run finishes, `y` copies the output to the system clipboard and `o` writes it to a file.
2. A failing API call shows red stderr separately from green stdout, in chronological order.
3. A script that prints `{"ok": true, "rows": 42}` can be opened in a JSON viewer with `J`.
4. Selecting a script in the list auto-displays its last run's output, so the bindings work without re-running.
5. `SCRIPTPILOT_OUTPUT_DIR` is set in the subprocess env, pointing at a predictable per-run path.

## Non-Goals

- No history browser / runs picker. Selecting a script auto-shows its single most-recent run; older runs are not browsable in this task.
- No stdout-only / stderr-only copy variants. `y` and `o` copy the combined chronological output; scripts that want a clean payload write it to `$SCRIPTPILOT_OUTPUT_DIR`.
- No `mkdir -p` of `$SCRIPTPILOT_OUTPUT_DIR` from the executor — scripts that need it create it themselves.
- No on-disk migration of pre-existing `RunRecord` JSON. Project is fresh; `RunRecord.output: str` is replaced (not paralleled) by `RunRecord.lines: list[OutputLine]`.
- No live-run save / copy. Bindings are inert while a run is in progress.
- No automated Textual snapshot tests; logic is pulled into pure-function modules and unit-tested there.

## Architecture

| Feature | Where it lives | New code |
|---|---|---|
| Stderr separation, chronological store | `executor.py`, `models.py` | `OutputLine` NamedTuple; `RunRecord.lines: list[OutputLine]` |
| Save / copy bindings | `widgets/main_panel.py`, `screens/main.py` | `clipboard.py` helper; `screens/save_prompt.py` modal |
| JSON viewer | `widgets/main_panel.py` + new modal | `screens/json_view.py` |
| `SCRIPTPILOT_OUTPUT_DIR` | `executor.py` | env-var injection, no dir creation |
| Auto-show last-run output | `screens/main.py`, `widgets/main_panel.py` | extend MainPanel with `show_finished_run` |

Three new modules: `src/scriptpilot/clipboard.py`, `src/scriptpilot/screens/save_prompt.py`, `src/scriptpilot/screens/json_view.py`. One new dataclass-shaped type (`OutputLine`) on `models.py`.

### `src/scriptpilot/models.py` — `OutputLine` and reshaped `RunRecord`

```python
from typing import Literal, NamedTuple

class OutputLine(NamedTuple):
    stream: Literal["stdout", "stderr"]
    line: str


class RunRecord(BaseModel):
    script_id: str
    script_name: str
    timestamp: str
    exit_code: int
    timed_out: bool
    duration: float
    lines: list[OutputLine] = []

    def combined_text(self) -> str:
        """Chronological output, stdout and stderr interleaved, no stream marker."""
        return "\n".join(line for _, line in self.lines)

    def stdout_text(self) -> str:
        """Stdout-only lines for the JSON viewer's parse attempts."""
        return "\n".join(line for stream, line in self.lines if stream == "stdout")
```

`NamedTuple` is JSON-serializable as a 2-element array; Pydantic round-trips it via `model_validate` without further config.

### `src/scriptpilot/executor.py` — separate stderr, set env var

`OutputLine` is imported from `scriptpilot.models`, not redefined here.

```python
from scriptpilot.models import OutputLine

async def execute_script(
    script: Script,
    arg_values: list[str] | None = None,
    on_output: Callable[[OutputLine], None] | None = None,
    *,
    script_path: Path,
    python_command: str = "python3",
) -> ExecutionResult:
    cmd_prefix = _resolve_command(script.type, python_command)
    cwd = _resolve_cwd(script.cwd)
    secrets = load_secrets()

    output_dir = (
        Path.home() / ".scriptpilot" / "outputs" / script.id / _ts_dir()
    )
    env = {
        **os.environ,
        **secrets,
        "SCRIPTPILOT_OUTPUT_DIR": str(output_dir),
        **script.env,  # script's per-script env wins
    }

    cmd = [*cmd_prefix, str(script_path), *(arg_values or [])]
    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd),
        env=env,
        start_new_session=True,
    )

    timed_out = False

    async def _read(stream, label: Literal["stdout", "stderr"]):
        while True:
            raw = await stream.readline()
            if not raw:
                break
            text = raw.decode(errors="replace").rstrip("\n")
            if on_output:
                on_output(OutputLine(label, text))

    read_tasks = [
        asyncio.create_task(_read(proc.stdout, "stdout")),
        asyncio.create_task(_read(proc.stderr, "stderr")),
    ]

    try:
        await asyncio.wait_for(proc.wait(), timeout=script.timeout)
    except asyncio.TimeoutError:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()

    await asyncio.gather(*read_tasks)

    duration = time.monotonic() - start
    return ExecutionResult(
        exit_code=proc.returncode if proc.returncode is not None else -1,
        timed_out=timed_out,
        duration=duration,
    )


def _ts_dir() -> str:
    """Filesystem-safe timestamp for SCRIPTPILOT_OUTPUT_DIR (no colons)."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
```

The output dir is **not created** — scripts that want to write artifacts there `mkdir -p "$SCRIPTPILOT_OUTPUT_DIR"` themselves. `script.env` keys override `SCRIPTPILOT_OUTPUT_DIR` if the user explicitly sets one for the script.

`asyncio.gather(*read_tasks)` ensures both pipes are drained — important because if only stdout produces output and stderr is unread, killing the process group still requires both reader coroutines to terminate before we exit.

### `src/scriptpilot/clipboard.py` — new module

```python
from __future__ import annotations
import shutil
import subprocess
import sys


class ClipboardUnavailable(Exception):
    """No clipboard backend (pyperclip, wl-copy, xclip, pbcopy) was found or worked."""


def copy(text: str) -> None:
    """Copy text to the system clipboard.

    Tries pyperclip first (if importable), then shell-based backends:
    wl-copy (Wayland), xclip -selection clipboard (X11), pbcopy (macOS).
    Raises ClipboardUnavailable if no backend works.
    """
    try:
        import pyperclip  # type: ignore
        pyperclip.copy(text)
        return
    except ImportError:
        pass
    except Exception:
        pass  # pyperclip's PyperclipException → fall through

    backends: list[list[str]] = []
    if sys.platform == "darwin":
        backends.append(["pbcopy"])
    else:
        backends.append(["wl-copy"])
        backends.append(["xclip", "-selection", "clipboard"])

    for cmd in backends:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            subprocess.run(cmd, input=text.encode(), check=True)
            return
        except subprocess.CalledProcessError:
            continue

    raise ClipboardUnavailable(
        "no clipboard backend found (install pyperclip, wl-copy, xclip, or pbcopy)"
    )
```

`pyproject.toml` gains an optional extra:

```toml
[project.optional-dependencies]
clipboard = ["pyperclip>=1.8"]
```

### `src/scriptpilot/widgets/main_panel.py` — bindings, styling, run state

```python
from rich.markup import escape

class MainPanel(Widget):
    BINDINGS = [
        ("o", "save_output", "Save"),
        ("y", "copy_output", "Copy"),
        ("J", "view_json", "JSON"),
    ]

    def __init__(self):
        super().__init__()
        self._displayed_run: RunRecord | None = None
        self._is_running: bool = False

    def append_output(self, line: OutputLine):
        log = self.query_one("#output-log", RichLog)
        text = escape(line.line)
        if line.stream == "stderr":
            log.write(f"[red]{text}[/red]")
        else:
            log.write(text)

    def show_running(self, script: Script):
        # ... existing display swap ...
        self._displayed_run = None
        self._is_running = True

    def show_finished_run(self, run: RunRecord):
        """Render a finished run (just-finished or selected from history)."""
        self._displayed_run = run
        self._is_running = False
        log = self.query_one("#output-log", RichLog)
        log.clear()
        for line in run.lines:
            self.append_output(line)
        log.display = True
        status = self.query_one("#status-bar", Static)
        if run.timed_out:
            status.update(f"[red]Timed out after {run.duration:.1f}s[/red]")
        elif run.exit_code == 0:
            status.update(
                f"[green]Exit code: {run.exit_code}[/green]  Duration: {run.duration:.1f}s"
            )
        else:
            status.update(
                f"[red]Exit code: {run.exit_code}[/red]  Duration: {run.duration:.1f}s"
            )
        status.display = True

    def action_save_output(self):
        if self._displayed_run is None or self._is_running:
            return
        run = self._displayed_run
        default_path = (
            Path.home() / ".scriptpilot" / "outputs"
            / f"{_safe_name(run.script_name)}-{_ts_filename()}.txt"
        )

        def on_path(path: Path | None):
            if path is None:
                return
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(run.combined_text())
            except OSError as e:
                self.notify(str(e), severity="error")
                return
            self.notify(f"Saved to {path}")

        self.app.push_screen(SavePromptScreen(default_path), callback=on_path)

    def action_copy_output(self):
        if self._displayed_run is None or self._is_running:
            return
        try:
            clipboard.copy(self._displayed_run.combined_text())
            self.notify("Copied")
        except ClipboardUnavailable as e:
            self.notify(str(e), severity="warning")

    def action_view_json(self):
        if self._displayed_run is None or self._is_running:
            return
        text = self._displayed_run.stdout_text().strip()
        if not text:
            self.notify("No stdout to parse", severity="warning")
            return
        parsed = _try_parse_json(text)
        if parsed is None:
            self.notify("Output is not JSON", severity="warning")
            return
        self.app.push_screen(JsonViewScreen(parsed))


def _try_parse_json(stdout: str) -> object | None:
    """Try whole stdout first, then last non-empty line."""
    candidates = [stdout]
    last = _last_nonempty_line(stdout)
    if last and last != stdout:
        candidates.append(last)
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _last_nonempty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line
    return ""


def _safe_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-") or "output"


def _ts_filename() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
```

Stderr lines are styled red via `[red]…[/red]` markup, with `rich.markup.escape` first to prevent script output containing literal `[brackets]` from being interpreted as markup.

`_try_parse_json`, `_last_nonempty_line`, `_safe_name` are module-level pure functions, unit-testable without instantiating Textual.

### `src/scriptpilot/screens/save_prompt.py` — new modal

```python
class SavePromptScreen(ModalScreen[Path | None]):
    """Prompt for a file path; returns Path on submit, None on cancel."""

    DEFAULT_CSS = """
    SavePromptScreen { align: center middle; }
    SavePromptScreen #save-container {
        width: 80; height: auto;
        background: $surface; border: solid $primary;
        padding: 1 2;
    }
    SavePromptScreen #save-buttons {
        height: 3; align: right middle;
    }
    SavePromptScreen #save-buttons Button { margin-left: 1; }
    """

    def __init__(self, default_path: Path):
        super().__init__()
        self._default = default_path

    def compose(self) -> ComposeResult:
        with Vertical(id="save-container"):
            yield Label("[bold]Save output to:[/bold]")
            yield Input(value=str(self._default), id="save-path")
            with Horizontal(id="save-buttons"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Save", id="save-btn", variant="success")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "save-btn":
            raw = self.query_one("#save-path", Input).value.strip()
            if not raw:
                self.notify("Path is required", severity="error")
                return
            self.dismiss(Path(raw).expanduser())

    def on_input_submitted(self, event: Input.Submitted):
        # Enter on the input also submits.
        self.on_button_pressed(Button.Pressed(self.query_one("#save-btn", Button)))
```

### `src/scriptpilot/screens/json_view.py` — new modal

```python
class JsonViewScreen(ModalScreen[None]):
    """Display parsed JSON via rich.json.JSON."""

    BINDINGS = [("escape,q", "dismiss", "Close")]

    DEFAULT_CSS = """
    JsonViewScreen { align: center middle; }
    JsonViewScreen #jv-container {
        width: 80%; max-width: 120;
        height: 80%;
        background: $surface; border: solid $primary;
        padding: 1 2;
    }
    JsonViewScreen #jv-content { height: 1fr; }
    """

    def __init__(self, parsed: object):
        super().__init__()
        self._parsed = parsed

    def compose(self) -> ComposeResult:
        with Vertical(id="jv-container"):
            yield Label("[bold]JSON output[/bold] ([dim]q to close[/dim])")
            yield Static(JSON.from_data(self._parsed), id="jv-content")

    def action_dismiss(self):
        self.dismiss(None)
```

### `src/scriptpilot/screens/main.py` — auto-show last run, build new RunRecord

`on_script_selected` gets the auto-show wiring:

```python
def on_script_selected(self, event: ScriptSelected):
    self._selected_script = event.script
    last_run = self._get_last_run(event.script.id)
    panel = self.query_one(MainPanel)
    panel.show_script_details(event.script, last_run)
    if last_run:
        panel.show_finished_run(last_run)
```

`_execute` collects into a `list[OutputLine]` and constructs `RunRecord(lines=...)`:

```python
async def run():
    lines: list[OutputLine] = []

    def collect_output(line: OutputLine):
        lines.append(line)
        panel.append_output(line)

    try:
        result = await execute_script(
            script,
            arg_values=arg_values,
            on_output=collect_output,
            script_path=self._store.path_for(script.id),
            python_command=self.app._config.python_command,
        )
        record = RunRecord(
            script_id=script.id,
            script_name=script.name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            duration=result.duration,
            lines=lines,
        )
        self._history.add(record)
        panel.show_finished_run(record)
    except (InterpreterNotFoundError, ScriptCwdError) as e:
        ...
```

The just-finished record becomes the panel's `_displayed_run`, so `o`/`y`/`J` operate on it immediately.

## Data Flow

### Flow A — Just-finished run, copy to clipboard

```
user runs `transform.sh` (prints CSV + a stderr warning)
  → executor: stdout=PIPE, stderr=PIPE
  → _read(stdout): on_output(OutputLine("stdout", "name,age"))
                   on_output(OutputLine("stdout", "alice,30"))
  → _read(stderr): on_output(OutputLine("stderr", "warning: missing col 'email'"))
  → MainScreen._execute.collect_output appends each to `lines` and panel.append_output(line)
  → panel renders: "name,age" white, "alice,30" white, stderr line red
  → run finishes → RunRecord(lines=[...]) → history.add → panel.show_finished_run(record)
  → panel._displayed_run = record
user presses `y`
  → action_copy_output: clipboard.copy(record.combined_text())
       combined_text = "name,age\nalice,30\nwarning: missing col 'email'"
  → notify "Copied"
```

### Flow B — Selected past script, view JSON

```
user clicks `fetch_status` in script list
  → on_script_selected: last_run from history → panel.show_finished_run(last_run)
  → panel._displayed_run = last_run, lines rendered in #output-log
user presses `J`
  → action_view_json:
       text = last_run.stdout_text() = '{"ok": true, "rows": 42}'
       _try_parse_json: json.loads(text) → {"ok": True, "rows": 42}
  → push_screen(JsonViewScreen({"ok": True, "rows": 42}))
  → modal renders rich.json.JSON; q closes
```

### Flow C — Pretty-printed JSON across multiple lines

```
script prints:
  {
    "x": 1,
    "y": [2, 3]
  }

stdout_text = '{\n  "x": 1,\n  "y": [2, 3]\n}'
_try_parse_json:
  candidate 1 = whole stdout → json.loads succeeds → return parsed
```

### Flow D — Status line + JSON at end

```
script prints:
  fetching...
  {"ok": true}

stdout_text = "fetching...\n{\"ok\": true}"
_try_parse_json:
  candidate 1 = whole stdout → JSONDecodeError
  candidate 2 = last_nonempty_line = '{"ok": true}' → json.loads succeeds → return parsed
```

### Flow E — Save with path edit

```
user presses `o`
  → default_path = ~/.scriptpilot/outputs/transform-2026-05-04T17-23-05.txt
  → SavePromptScreen pre-fills
user edits path to `/tmp/out.txt`, presses Save
  → dismiss(Path("/tmp/out.txt"))
  → on_path: parent.mkdir(parents=True, exist_ok=True); write_text(combined_text())
  → notify "Saved to /tmp/out.txt"
```

If `parent.mkdir` or `write_text` raises `OSError` (permission denied, parent path is a file, etc.), notify the message; modal stays open since `on_path` is the dismiss callback — user has already left the modal. **Refinement:** notify on error but the modal is gone; user re-presses `o` to retry. Acceptable for v1; if it becomes friction, switch to validating in the modal before dismissal.

### Flow F — `SCRIPTPILOT_OUTPUT_DIR` write

```
script.id = "abc-123", run starts at 2026-05-04T17:23:05Z
executor sets env: SCRIPTPILOT_OUTPUT_DIR=/home/user/.scriptpilot/outputs/abc-123/2026-05-04T17-23-05
  (dir does NOT exist yet)
script content (bash):
  mkdir -p "$SCRIPTPILOT_OUTPUT_DIR"
  curl ... > "$SCRIPTPILOT_OUTPUT_DIR/data.json"
on completion, the dir contains data.json; ScriptPilot itself is unaware.
```

If the user explicitly sets `script.env = {"SCRIPTPILOT_OUTPUT_DIR": "/tmp/foo"}`, that wins (script.env spread comes after the default).

## Error Handling

| Surface | Failure | Behavior |
|---|---|---|
| `clipboard.copy` | pyperclip unimportable, no shell backend | `ClipboardUnavailable` → MainPanel notifies install hint, severity=warning |
| `clipboard.copy` | pyperclip raises `PyperclipException` | falls through to shell backends |
| `o` save | parent dir cannot be created | `OSError` → notify; user re-presses `o` to retry |
| `o` save | write fails (permission denied, disk full) | `OSError` → notify; user re-presses `o` to retry |
| `o` save modal | empty path on submit | notify "Path is required"; modal stays open |
| `J` viewer | stdout empty | notify "No stdout to parse" |
| `J` viewer | stdout not parseable as JSON (whole or last-line) | notify "Output is not JSON" |
| Bindings | no run displayed (welcome screen) | action early-returns silently |
| Bindings | live run in progress | action early-returns silently |
| Stderr decoding | non-UTF-8 bytes | `decode(errors="replace")` (matches stdout) |
| Reader tasks | one stream stalled | `asyncio.gather(*read_tasks)` reads both concurrently — neither blocks the other |
| `SCRIPTPILOT_OUTPUT_DIR` | dir does not exist when script tries to write | script's responsibility (`mkdir -p` documented in README) |
| `SCRIPTPILOT_OUTPUT_DIR` | user override in `script.env` | user's value wins; documented behavior |
| Markup injection | script prints `[bold]hi[/bold]` | `rich.markup.escape` neutralizes it before write |

## Testing

### `tests/test_clipboard.py` (new)

- Pyperclip importable + works → `pyperclip.copy` called, no shell-out.
- Pyperclip importable + raises → falls through to shell backend.
- No pyperclip, `wl-copy` on PATH → `subprocess.run(["wl-copy"], input=..., check=True)` invoked.
- No pyperclip, no `wl-copy`, `xclip` on PATH → invoked with `["xclip", "-selection", "clipboard"]`.
- Patch `sys.platform = "darwin"` → tries `pbcopy` first.
- No backends available (`shutil.which` returns None for all) → raises `ClipboardUnavailable`.
- Backend command exits non-zero → falls through to next backend or raises.

### `tests/test_executor.py` (extend)

- Stdout and stderr captured into separate `OutputLine` callbacks (run a script that emits to both via `echo` / `>&2`).
- `OutputLine.stream` correctly tagged for each line.
- Both readers drain even when only one stream produces output.
- `SCRIPTPILOT_OUTPUT_DIR` env var is set in subprocess env, points under `~/.scriptpilot/outputs/<id>/<timestamp>`, and the dir is **not** created by the executor.
- Per-script `script.env["SCRIPTPILOT_OUTPUT_DIR"]` overrides the default.
- Timeout path: process killed mid-stream — both reader tasks complete promptly without hanging.

### `tests/test_models.py` (extend)

- `OutputLine("stdout", "x")` is a 2-tuple, accessible by name and index.
- `RunRecord(lines=[OutputLine("stdout", "x"), OutputLine("stderr", "y")])` round-trips through `model_dump_json` / `model_validate_json`.
- `combined_text()` returns lines in chronological order with no stream marker.
- `stdout_text()` filters to stdout only.
- Empty `lines` defaults to `[]`.

### `tests/test_history.py` (extend)

- `HistoryStore` persists and reloads `RunRecord.lines` correctly through JSON file save/load.

### `tests/test_main_panel.py` (new) — pure helpers only

- `_try_parse_json('{"x":1}')` → `{"x": 1}`.
- `_try_parse_json("not json")` → `None`.
- `_try_parse_json('status: ok\n{"x":1}')` → `{"x": 1}` (last-line fallback).
- `_try_parse_json('{\n  "x": 1\n}')` → `{"x": 1}` (multi-line whole-stdout).
- `_try_parse_json("")` → `None`.
- `_last_nonempty_line("a\n\n")` → `"a"`.
- `_last_nonempty_line("")` → `""`.
- `_safe_name("My Script!!")` → `"My-Script"`.
- `_safe_name("")` → `"output"`.

### Manual acceptance walkthrough

1. Run a script that prints `{"ok": true, "rows": 42}`. Press `J` → modal opens with rendered JSON; `q` closes it.
2. Same run, press `y` → notify "Copied"; paste in another app matches the displayed output.
3. Press `o` → modal pre-fills `~/.scriptpilot/outputs/<name>-<ts>.txt`. Submit → file exists with combined output.
4. Run `bash -c 'echo hi; echo oops 1>&2; echo bye'` → stdout lines white, stderr line red, in chronological order.
5. Set `script.env = {"SCRIPTPILOT_OUTPUT_DIR": "/tmp/foo"}` → script sees `/tmp/foo`.
6. Click another script in the list, then click the first one back → its last-run output appears in the panel; `y` copies it.
7. Press `y` while a run is in progress → no-op.
8. Run on a system with no clipboard tool installed and no `pyperclip` → `y` notifies install hint.
9. Run a script that prints `[red]injection[/red]` literally → output displays the raw text, not red.
10. Script that does `mkdir -p "$SCRIPTPILOT_OUTPUT_DIR"; echo hi > "$SCRIPTPILOT_OUTPUT_DIR/note.txt"` → file exists at `~/.scriptpilot/outputs/<id>/<ts>/note.txt`.

## Acceptance Criteria

- After a run finishes (or after selecting a script with prior runs), pressing `y` copies the combined output to the system clipboard via `pyperclip` / `wl-copy` / `xclip` / `pbcopy` (whichever works first), or notifies an install hint if none are available.
- After a run finishes, pressing `o` opens a modal pre-filled with `~/.scriptpilot/outputs/<safe-name>-<timestamp>.txt`; submitting writes the combined output to that path (creating parent dirs as needed).
- Stdout and stderr are read on separate pipes and streamed into `OutputLine(stream, line)` events in the order they arrive. `RunRecord.lines` is a chronological list of these tuples.
- Stderr lines render red in the `RichLog`; stdout lines render plain. Markup in script output is escaped before display.
- Pressing `J` after a run that emitted JSON on stdout opens a modal rendering the parsed structure via `rich.json.JSON`. The parser tries whole stdout first, then the last non-empty line. Non-JSON output notifies a warning.
- Selecting a script in the list automatically renders its most recent run's output in the main panel; the bindings target that run.
- `o`/`y`/`J` are inert while a run is in progress.
- `SCRIPTPILOT_OUTPUT_DIR` is set in the subprocess env to `~/.scriptpilot/outputs/<script-id>/<timestamp>`. The executor does not create the directory. Per-script `script.env` overrides the default.
- `clipboard.py`, `_try_parse_json`, `_last_nonempty_line`, `_safe_name` are unit-tested without Textual.
- `pyproject.toml` declares `pyperclip>=1.8` as a `clipboard` optional extra; default install does not pull it in.
