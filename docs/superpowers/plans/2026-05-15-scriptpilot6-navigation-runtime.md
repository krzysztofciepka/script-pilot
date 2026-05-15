# ScriptPilot Navigation & Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship four navigation/runtime improvements to ScriptPilot — fuzzy filter (`/`), tags on `Script`, cancel running script (`s`), and a cross-script run history modal (`H`).

**Architecture:** Additive Pydantic field changes (`Script.tags`, `RunRecord.cancelled`) ride existing storage; a pure `normalize_tags` helper lives in a new `tags.py`; the executor grows an optional `cancel_event: asyncio.Event` that races `proc.wait()` and reuses the existing process-group SIGKILL path; the filter is local to `ScriptList` (substring match via `_matches`); the history modal is a new `HistoryScreen` showing `RunRecord`s from `HistoryStore.list_all()`.

**Tech Stack:** Python 3.10+, Pydantic v2, Textual (TUI), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-05-15-scriptpilot6-navigation-runtime-design.md`

---

## File map

| File | Status | Responsibility |
|---|---|---|
| `src/scriptpilot/tags.py` | NEW | `normalize_tags(raw: str) -> list[str]` |
| `src/scriptpilot/models.py` | MODIFY | Add `Script.tags`, `RunRecord.cancelled` |
| `src/scriptpilot/executor.py` | MODIFY | `cancel_event` parameter, `ExecutionResult.cancelled` |
| `src/scriptpilot/history.py` | MODIFY | Add `format_history_row(r)` |
| `src/scriptpilot/screens/history.py` | NEW | `HistoryScreen(ModalScreen[RunRecord \| None])` |
| `src/scriptpilot/screens/main.py` | MODIFY | `s`/`slash`/`H` bindings + handlers; cancel-event lifecycle; `_highlight_script` |
| `src/scriptpilot/screens/edit.py` | MODIFY | Tags input + normalize on save |
| `src/scriptpilot/widgets/script_list.py` | MODIFY | Hidden filter `Input`, `_matches`, `_apply_filter`, tag-aware label |
| `src/scriptpilot/widgets/main_panel.py` | MODIFY | `cancelled` status branch |
| `tests/test_tags.py` | NEW | `normalize_tags` unit tests |
| `tests/test_script_list.py` | NEW | `_matches` unit tests |
| `tests/test_models.py` | MODIFY | `Script.tags` and `RunRecord.cancelled` defaults + round-trip |
| `tests/test_executor.py` | MODIFY | Cancel-event integration test |
| `tests/test_history.py` | MODIFY | `format_history_row` unit tests |

---

## Task 1: Tag normalization helper

Pure module — fully TDD.

**Files:**
- Create: `src/scriptpilot/tags.py`
- Create: `tests/test_tags.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_tags.py`:

```python
from scriptpilot.tags import normalize_tags


class TestNormalizeTags:
    def test_empty_string(self):
        assert normalize_tags("") == []

    def test_whitespace_only(self):
        assert normalize_tags("   ,  , ") == []

    def test_strips_whitespace(self):
        assert normalize_tags("  csv ,   jira ") == ["csv", "jira"]

    def test_lowercases(self):
        assert normalize_tags("CSV, Jira, FOO") == ["csv", "jira", "foo"]

    def test_dedupes_preserve_first_seen_order(self):
        assert normalize_tags("Foo, foo , BAR, bar, Foo") == ["foo", "bar"]

    def test_drops_empty_pieces(self):
        assert normalize_tags("a,,b,,,c") == ["a", "b", "c"]

    def test_single_tag(self):
        assert normalize_tags("daily") == ["daily"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tags.py -v`
Expected: All FAIL with `ModuleNotFoundError: No module named 'scriptpilot.tags'`.

- [ ] **Step 3: Implement `normalize_tags`**

`src/scriptpilot/tags.py`:

```python
from __future__ import annotations


def normalize_tags(raw: str) -> list[str]:
    """Split comma-separated tags; strip, lowercase, drop empties, dedupe (preserve first-seen order)."""
    seen: set[str] = set()
    out: list[str] = []
    for piece in raw.split(","):
        t = piece.strip().lower()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tags.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/tags.py tests/test_tags.py
git commit -m "feat: tags.normalize_tags helper (strip/lowercase/dedupe)"
```

---

## Task 2: Add `Script.tags` and `RunRecord.cancelled` fields

Additive, default-backed Pydantic fields.

**Files:**
- Modify: `src/scriptpilot/models.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_models.py`:

```python
from scriptpilot.models import Script, RunRecord, OutputLine


class TestScriptTags:
    def test_tags_default_empty(self):
        s = Script(name="x", description="y", type="bash", content="echo hi")
        assert s.tags == []

    def test_tags_round_trip(self):
        s = Script(
            name="x", description="y", type="bash", content="echo hi",
            tags=["csv", "jira"],
        )
        data = s.model_dump()
        assert data["tags"] == ["csv", "jira"]
        s2 = Script(**data)
        assert s2.tags == ["csv", "jira"]

    def test_tags_loads_from_meta_without_field(self):
        # Simulate an old meta.json that didn't have `tags`.
        legacy = {
            "id": "abc", "name": "x", "description": "y",
            "type": "bash", "content": "echo hi",
        }
        s = Script(**legacy)
        assert s.tags == []


class TestRunRecordCancelled:
    def test_cancelled_default_false(self):
        r = RunRecord(
            script_id="a", script_name="a",
            timestamp="2026-05-15T10:00:00",
            exit_code=0, timed_out=False, duration=1.0,
        )
        assert r.cancelled is False

    def test_cancelled_round_trip(self):
        r = RunRecord(
            script_id="a", script_name="a",
            timestamp="2026-05-15T10:00:00",
            exit_code=-1, timed_out=False, duration=2.3,
            cancelled=True,
            lines=[OutputLine("stdout", "hi")],
        )
        data = r.model_dump()
        assert data["cancelled"] is True
        r2 = RunRecord(**data)
        assert r2.cancelled is True

    def test_cancelled_loads_legacy_record(self):
        legacy = {
            "script_id": "a", "script_name": "a",
            "timestamp": "2026-05-15T10:00:00",
            "exit_code": 0, "timed_out": False, "duration": 1.0,
            "lines": [],
        }
        r = RunRecord(**legacy)
        assert r.cancelled is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py::TestScriptTags tests/test_models.py::TestRunRecordCancelled -v`
Expected: FAIL — `'Script' object has no attribute 'tags'` and `'RunRecord' object has no attribute 'cancelled'`.

- [ ] **Step 3: Add the fields to `models.py`**

Edit `src/scriptpilot/models.py` — find the `Script` class and add `tags`:

```python
class Script(BaseModel):
    """A saved automation script."""

    id: str = ""
    name: str
    description: str
    type: Literal["bash", "python", "js"]
    content: str
    args: list[ScriptArg] = []
    timeout: int = 60
    favorite: bool = False
    cwd: str | None = None
    env: dict[str, str] = {}
    arg_style: Literal["positional", "flags"] = "positional"
    tags: list[str] = []
```

Find `RunRecord` and add `cancelled`:

```python
class RunRecord(BaseModel):
    """A single script execution record."""

    script_id: str
    script_name: str
    timestamp: str
    exit_code: int
    timed_out: bool
    duration: float
    lines: list[OutputLine] = []
    cancelled: bool = False
```

- [ ] **Step 4: Run all model tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: all tests pass (existing tests stay green; new tests pass).

- [ ] **Step 5: Run the full test suite — nothing else should regress**

Run: `uv run pytest -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/scriptpilot/models.py tests/test_models.py
git commit -m "feat: Script.tags and RunRecord.cancelled fields"
```

---

## Task 3: Executor cancel-event support

Add `cancel_event: asyncio.Event | None` to `execute_script` and `cancelled: bool` to `ExecutionResult`. Reuse the timeout path (process-group SIGKILL).

**Files:**
- Modify: `src/scriptpilot/executor.py`
- Modify: `tests/test_executor.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_executor.py`:

```python
import asyncio


@pytest.fixture
def long_sleep_script(tmp_path):
    script = Script(
        name="sleep",
        description="sleeps 30s",
        type="bash",
        content="sleep 30",
        timeout=10,
    )
    return script, _materialize(script, tmp_path)


class TestExecutorCancel:
    @pytest.mark.asyncio
    async def test_cancel_event_kills_process(self, long_sleep_script):
        script, path = long_sleep_script
        event = asyncio.Event()

        async def fire_cancel():
            await asyncio.sleep(0.1)
            event.set()

        task = asyncio.create_task(fire_cancel())
        result = await execute_script(script, script_path=path, cancel_event=event)
        await task

        assert result.cancelled is True
        assert result.timed_out is False
        assert result.exit_code != 0
        assert result.duration < 5  # well under the 10s timeout

    @pytest.mark.asyncio
    async def test_no_cancel_event_runs_normally(self, bash_script):
        script, path = bash_script
        result = await execute_script(script, script_path=path)
        assert result.cancelled is False
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_unfired_cancel_event_runs_normally(self, bash_script):
        script, path = bash_script
        event = asyncio.Event()
        result = await execute_script(script, script_path=path, cancel_event=event)
        assert result.cancelled is False
        assert result.exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_executor.py::TestExecutorCancel -v`
Expected: FAIL — `TypeError: execute_script() got an unexpected keyword argument 'cancel_event'`.

- [ ] **Step 3: Update `ExecutionResult` and `execute_script` in `executor.py`**

Modify `src/scriptpilot/executor.py`. First, the dataclass:

```python
@dataclass
class ExecutionResult:
    exit_code: int
    timed_out: bool
    duration: float
    cancelled: bool = False
```

Then the function signature and the wait block. Replace the existing `try: await asyncio.wait_for(...) except asyncio.TimeoutError: ...` block with this:

```python
async def execute_script(
    script: Script,
    arg_values: list[str] | None = None,
    on_output: Callable[[OutputLine], None] | None = None,
    *,
    script_path: Path,
    python_command: str = "python3",
    cancel_event: asyncio.Event | None = None,
) -> ExecutionResult:
    """Execute a script (read from ``script_path``) and stream output."""
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
        **script.env,
    }

    cmd = [*cmd_prefix, str(script_path)]
    if arg_values:
        cmd.extend(arg_values)

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
    cancelled = False

    async def _read(stream, label: Literal["stdout", "stderr"]):
        if stream is None:
            return
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

    if cancel_event is None:
        try:
            await asyncio.wait_for(proc.wait(), timeout=script.timeout)
        except asyncio.TimeoutError:
            timed_out = True
    else:
        wait_task = asyncio.create_task(proc.wait())
        cancel_task = asyncio.create_task(cancel_event.wait())
        done, pending = await asyncio.wait(
            [wait_task, cancel_task],
            timeout=script.timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        if not done:
            timed_out = True
        elif cancel_task in done and cancel_event.is_set():
            cancelled = True

    if timed_out or cancelled:
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
        cancelled=cancelled,
        duration=duration,
    )
```

- [ ] **Step 4: Run executor tests to verify they pass**

Run: `uv run pytest tests/test_executor.py -v`
Expected: all green (existing + 3 new cancel tests).

- [ ] **Step 5: Run the full test suite — nothing else should regress**

Run: `uv run pytest -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/scriptpilot/executor.py tests/test_executor.py
git commit -m "feat: executor accepts cancel_event and surfaces cancelled flag"
```

---

## Task 4: Cancel binding on MainScreen + MainPanel "Cancelled by user" status

End-to-end UI integration for cancel — binding, event lifecycle, status display.

**Files:**
- Modify: `src/scriptpilot/screens/main.py`
- Modify: `src/scriptpilot/widgets/main_panel.py`

No new unit tests for this task — the underlying logic is covered by `test_executor.py::TestExecutorCancel`. Manual verification is the acceptance gate.

- [ ] **Step 1: Add the binding and cancel-event state to `MainScreen`**

In `src/scriptpilot/screens/main.py`:

Add an import at the top:
```python
import asyncio
```

In the `BINDINGS` list, append:
```python
("s", "cancel_script", "Cancel"),
```

In `MainScreen.__init__`, add the event attribute:
```python
def __init__(self, store: ScriptStore, history: HistoryStore):
    super().__init__()
    self._store = store
    self._history = history
    self._selected_script: Script | None = None
    self._cancel_event: asyncio.Event | None = None
```

- [ ] **Step 2: Add the cancel action handler**

In `MainScreen`, add:
```python
def action_cancel_script(self):
    if self._cancel_event is None:
        self.notify("Nothing running", severity="warning")
        return
    self._cancel_event.set()
```

- [ ] **Step 3: Plumb the event through `_execute` and persist `cancelled`**

Replace the body of `_execute` with:

```python
def _execute(self, script: Script, arg_values: list[str] | None = None):
    panel = self.query_one(MainPanel)
    panel.show_running(script)

    cancel_event = asyncio.Event()
    self._cancel_event = cancel_event

    async def run():
        collected: list[OutputLine] = []

        def collect_output(line: OutputLine):
            collected.append(line)
            panel.append_output(line)

        try:
            result = await execute_script(
                script,
                arg_values=arg_values,
                on_output=collect_output,
                script_path=self._store.path_for(script.id),
                python_command=self.app._config.python_command,
                cancel_event=cancel_event,
            )

            from datetime import datetime, timezone
            record = RunRecord(
                script_id=script.id,
                script_name=script.name,
                timestamp=datetime.now(timezone.utc).isoformat(),
                exit_code=result.exit_code,
                timed_out=result.timed_out,
                cancelled=result.cancelled,
                duration=result.duration,
                lines=collected,
            )
            self._history.add(record)
            panel.show_finished_run(record)
        except (InterpreterNotFoundError, ScriptCwdError) as e:
            panel.show_error(str(e))
            self.notify(str(e), severity="error")
        except Exception as e:
            panel.show_error(f"Error: {e}")
            self.notify(str(e), severity="error")
        finally:
            if self._cancel_event is cancel_event:
                self._cancel_event = None

    self.run_worker(run(), name="execute", exclusive=True)
```

- [ ] **Step 4: Add the "Cancelled by user" branch in `MainPanel.show_finished_run`**

In `src/scriptpilot/widgets/main_panel.py`, replace the status block at the bottom of `show_finished_run`:

```python
def show_finished_run(self, run: RunRecord):
    """Render a finished run (just-finished or selected from history)."""
    self.query_one("#welcome").display = False
    self._displayed_run = run
    self._is_running = False

    log = self.query_one("#output-log", RichLog)
    log.clear()
    for line in run.lines:
        self.append_output(line)
    log.display = True

    status = self.query_one("#status-bar", Static)
    if run.cancelled:
        status.update(
            f"[yellow]Cancelled by user[/yellow]  Duration: {run.duration:.1f}s"
        )
    elif run.timed_out:
        status.update(f"[red]Timed out after {run.duration:.1f}s[/red]")
    elif run.exit_code == 0:
        status.update(
            f"[green]Exit code: {run.exit_code}[/green]  "
            f"Duration: {run.duration:.1f}s"
        )
    else:
        status.update(
            f"[red]Exit code: {run.exit_code}[/red]  "
            f"Duration: {run.duration:.1f}s"
        )
    status.display = True
```

- [ ] **Step 5: Smoke-run the test suite to confirm no regressions**

Run: `uv run pytest -v`
Expected: all green (no new tests; existing tests must stay green).

- [ ] **Step 6: Manual verification**

```bash
uv run scriptpilot
```

- Create a new script (type bash, content `sleep 30`).
- Run it.
- Press `s`. Status should show "Cancelled by user". The script should die quickly.

- [ ] **Step 7: Commit**

```bash
git add src/scriptpilot/screens/main.py src/scriptpilot/widgets/main_panel.py
git commit -m "feat: cancel running script with 's' binding"
```

---

## Task 5: Tags input in EditScreen + tag-aware list label

UI integration for tags: form input, normalization on save, label rendering. Clone preserves tags.

**Files:**
- Modify: `src/scriptpilot/screens/edit.py`
- Modify: `src/scriptpilot/widgets/script_list.py`
- Modify: `src/scriptpilot/screens/main.py` (clone branch)

- [ ] **Step 1: Add the tags input to `EditScreen.compose`**

In `src/scriptpilot/screens/edit.py`, after the Description input block (before the Type Select), insert:

```python
yield Label("Tags (comma-separated):")
yield Input(
    value=", ".join(s.tags) if s else "",
    placeholder="csv, jira, daily",
    id="tags-input",
)
```

Concretely, find this block:
```python
yield Label("Description:")
yield Input(value=s.description if s else "", id="desc-input")
yield Label("Type:")
```
And insert the two new lines between `desc-input` and `Type:`.

- [ ] **Step 2: Normalize tags in `_collect_form`**

At the top of `src/scriptpilot/screens/edit.py`, add:
```python
from scriptpilot.tags import normalize_tags
```

In `_collect_form`, after the existing form reads, add:
```python
tags_raw = self.query_one("#tags-input", Input).value
tags = normalize_tags(tags_raw)
```

Then update both return branches.

In the in-place edit branch:
```python
if self._script:
    self._script.name = name
    self._script.description = desc
    self._script.type = script_type
    self._script.content = content
    self._script.timeout = timeout
    self._script.args = args
    self._script.cwd = cwd_str
    self._script.env = env
    self._script.arg_style = arg_style
    self._script.tags = tags
    return self._script
```

In the new-script branch:
```python
return Script(
    name=name,
    description=desc,
    type=script_type,
    content=content,
    timeout=timeout,
    args=args,
    cwd=cwd_str,
    env=env,
    arg_style=arg_style,
    tags=tags,
)
```

- [ ] **Step 3: Update `ScriptList._make_label` to include tags**

In `src/scriptpilot/widgets/script_list.py`, replace `_make_label`:

```python
@staticmethod
def _make_label(script: Script) -> str:
    star = " *" if script.favorite else ""
    base = f"[{TYPE_LABELS.get(script.type, '??')}]{star} {script.name}"
    if script.tags:
        base += f" [dim]{{{', '.join(script.tags)}}}[/dim]"
    return base
```

Then update the existing `compose` and `update_scripts` methods so that `ListItem(Label(...))` uses markup-rendered labels. The existing `Label(label)` already renders Textual markup (the codebase uses this pattern in `MainPanel`), so no other change is needed.

- [ ] **Step 4: Preserve tags in `action_clone_script`**

In `src/scriptpilot/screens/main.py`, in `action_clone_script`, add `tags=list(original.tags)` to the `Script(...)` constructor:

```python
clone = Script(
    name=f"{original.name} (copy)",
    description=original.description,
    type=original.type,
    content=original.content,
    args=[ScriptArg(**a.model_dump()) for a in original.args],
    timeout=original.timeout,
    favorite=False,
    cwd=original.cwd,
    env=dict(original.env),
    tags=list(original.tags),
)
```

- [ ] **Step 5: Run the test suite**

Run: `uv run pytest -v`
Expected: all green (no new tests, no regressions).

- [ ] **Step 6: Manual verification**

```bash
uv run scriptpilot
```

- Edit a script. Enter `Foo, foo , BAR` in the tags field. Save.
- The list should show `[..] script-name {foo, bar}` with the tag part rendered dim.
- Clone the script. The clone should also show `{foo, bar}`.

- [ ] **Step 7: Commit**

```bash
git add src/scriptpilot/screens/edit.py src/scriptpilot/widgets/script_list.py src/scriptpilot/screens/main.py
git commit -m "feat: tags on Script — edit form, list label, clone"
```

---

## Task 6: Filter `_matches` helper

Pure function — TDD.

**Files:**
- Modify: `src/scriptpilot/widgets/script_list.py` (add `_matches` function at module level)
- Create: `tests/test_script_list.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_script_list.py`:

```python
from scriptpilot.models import Script
from scriptpilot.widgets.script_list import _matches


def _make(name: str = "n", description: str = "d", tags=None) -> Script:
    return Script(
        name=name,
        description=description,
        type="bash",
        content="echo hi",
        tags=tags or [],
    )


class TestMatches:
    def test_empty_query_matches_everything(self):
        assert _matches(_make(), "") is True
        assert _matches(_make(), "   ") is True

    def test_substring_in_name(self):
        s = _make(name="csv-importer")
        assert _matches(s, "csv") is True
        assert _matches(s, "import") is True
        assert _matches(s, "xyz") is False

    def test_substring_in_description(self):
        s = _make(name="x", description="imports daily CSV data")
        assert _matches(s, "daily") is True
        assert _matches(s, "imports") is True

    def test_substring_in_tags(self):
        s = _make(tags=["csv", "jira"])
        assert _matches(s, "jira") is True
        assert _matches(s, "ji") is True

    def test_case_insensitive(self):
        s = _make(name="CSV-Importer", tags=["jira"])
        assert _matches(s, "csv") is True
        assert _matches(s, "JIRA") is True
        assert _matches(s, "Import") is True

    def test_no_match(self):
        s = _make(name="alpha", description="beta", tags=["gamma"])
        assert _matches(s, "delta") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_script_list.py -v`
Expected: FAIL — `ImportError: cannot import name '_matches' from 'scriptpilot.widgets.script_list'`.

- [ ] **Step 3: Add `_matches` to `script_list.py`**

In `src/scriptpilot/widgets/script_list.py`, add a module-level function (place it above the `ScriptList` class, after the `TYPE_LABELS` constant):

```python
def _matches(script: Script, query: str) -> bool:
    """Case-insensitive substring match across name, description, and tags."""
    q = query.strip().lower()
    if not q:
        return True
    haystack = " ".join([script.name, script.description, *script.tags]).lower()
    return q in haystack
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_script_list.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/widgets/script_list.py tests/test_script_list.py
git commit -m "feat: _matches substring filter (name/description/tags)"
```

---

## Task 7: Filter Input integration + `/` binding + focus chain

Adds the hidden `Input` above the list, the `/` binding on `MainScreen`, Esc/Down/Enter behavior, and live filtering. UI integration — no new unit tests beyond Task 6's coverage of `_matches`.

**Files:**
- Modify: `src/scriptpilot/widgets/script_list.py`
- Modify: `src/scriptpilot/screens/main.py`

- [ ] **Step 1: Rewrite `ScriptList` to include the filter input**

Replace the body of `src/scriptpilot/widgets/script_list.py` with:

```python
from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import ListItem, ListView, Label, Input

from scriptpilot.models import Script

TYPE_LABELS = {"bash": "SH", "python": "PY", "js": "JS"}


def _matches(script: Script, query: str) -> bool:
    """Case-insensitive substring match across name, description, and tags."""
    q = query.strip().lower()
    if not q:
        return True
    haystack = " ".join([script.name, script.description, *script.tags]).lower()
    return q in haystack


class ScriptSelected(Message):
    """Posted when a script is highlighted in the list (arrow navigation)."""

    def __init__(self, script: Script):
        super().__init__()
        self.script = script


class ScriptList(Widget):
    """Left panel listing saved scripts."""

    DEFAULT_CSS = """
    ScriptList {
        width: 30;
        dock: left;
        border-right: solid $primary;
    }
    ScriptList Input {
        display: none;
        height: 3;
    }
    ScriptList Input.visible {
        display: block;
    }
    ScriptList ListView {
        height: 1fr;
    }
    """

    BINDINGS = [("escape", "clear_filter", "Clear filter")]

    def __init__(self, scripts: list[Script] | None = None):
        super().__init__()
        self._scripts: list[Script] = scripts or []
        self._current_query: str = ""

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Filter…", id="filter-input")
        with ListView():
            for script in self._sorted(self._scripts):
                yield ListItem(Label(self._make_label(script)), name=script.id)

    def focus_filter(self):
        """Public entry point for MainScreen's '/' binding."""
        inp = self.query_one("#filter-input", Input)
        inp.add_class("visible")
        inp.focus()

    def action_clear_filter(self):
        inp = self.query_one("#filter-input", Input)
        had_value = bool(inp.value)
        inp.value = ""
        inp.remove_class("visible")
        if had_value:
            self._current_query = ""
            self._render_list()
        self.query_one(ListView).focus()

    def update_scripts(self, scripts: list[Script]):
        """Refresh the list with new script data, preserving the active filter."""
        self._scripts = scripts
        self._render_list()

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "filter-input":
            self._current_query = event.value
            self._render_list()

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "filter-input":
            self.query_one(ListView).focus()

    def on_key(self, event):
        # When the filter input is focused and the user presses Down,
        # move focus to the list (default Textual behavior captures it).
        inp = self.query_one("#filter-input", Input)
        if inp.has_focus and event.key == "down":
            self.query_one(ListView).focus()
            event.stop()

    def _render_list(self):
        filtered = [s for s in self._scripts if _matches(s, self._current_query)]
        lv = self.query_one(ListView)
        lv.clear()
        for script in self._sorted(filtered):
            lv.append(ListItem(Label(self._make_label(script)), name=script.id))

    @staticmethod
    def _sorted(scripts: list[Script]) -> list[Script]:
        """Sort favorites first, preserve insertion order within groups."""
        favorites = [s for s in scripts if s.favorite]
        others = [s for s in scripts if not s.favorite]
        return favorites + others

    @staticmethod
    def _make_label(script: Script) -> str:
        star = " *" if script.favorite else ""
        base = f"[{TYPE_LABELS.get(script.type, '??')}]{star} {script.name}"
        if script.tags:
            base += f" [dim]{{{', '.join(script.tags)}}}[/dim]"
        return base

    def _find_script(self, item_name: str) -> Script | None:
        for script in self._scripts:
            if script.id == item_name:
                return script
        return None

    def on_list_view_highlighted(self, event: ListView.Highlighted):
        if event.item is not None:
            script = self._find_script(event.item.name)
            if script:
                self.post_message(ScriptSelected(script))

    def on_list_view_selected(self, event: ListView.Selected):
        script = self._find_script(event.item.name)
        if script:
            self.post_message(ScriptSelected(script))
```

- [ ] **Step 2: Add the `/` binding to `MainScreen`**

In `src/scriptpilot/screens/main.py`, append to `BINDINGS`:
```python
("slash", "focus_filter", "Filter"),
```

Add the handler:
```python
def action_focus_filter(self):
    self.query_one(ScriptList).focus_filter()
```

- [ ] **Step 3: Run the existing test suite**

Run: `uv run pytest -v`
Expected: all green (the existing `_matches` tests, plus all pre-existing tests).

- [ ] **Step 4: Manual verification**

```bash
uv run scriptpilot
```

- Press `/`. An input appears above the list with focus.
- Type `csv`. The list narrows in real time.
- Press Down. Focus moves into the list (highlight visible on first filtered item).
- Press Up to go back, then press Esc. The input clears, hides, list shows everything, focus is on the list.
- Press `/` again, type `csv`, press Enter. Focus moves into the list (same as Down).
- With a tagged script `{csv, jira}`, `/jira` filters to it.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/widgets/script_list.py src/scriptpilot/screens/main.py
git commit -m "feat: fuzzy filter on script list ('/' to focus, Esc to clear)"
```

---

## Task 8: History row formatter

Pure formatter — TDD.

**Files:**
- Modify: `src/scriptpilot/history.py`
- Modify: `tests/test_history.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_history.py`:

```python
from scriptpilot.history import format_history_row


class TestFormatHistoryRow:
    def _record(self, **overrides) -> RunRecord:
        defaults = dict(
            script_id="a", script_name="csv-importer",
            timestamp="2026-05-15T14:32:17.123456+00:00",
            exit_code=0, timed_out=False, duration=1.4,
            lines=[],
        )
        defaults.update(overrides)
        return RunRecord(**defaults)

    def test_exit_zero(self):
        row = format_history_row(self._record())
        assert "2026-05-15 14:32:17" in row
        assert "csv-importer" in row
        assert "exit 0" in row
        assert "1.4s" in row

    def test_exit_nonzero(self):
        row = format_history_row(self._record(exit_code=2))
        assert "exit 2" in row

    def test_timed_out(self):
        row = format_history_row(self._record(timed_out=True, duration=60.0))
        assert "timed out" in row
        assert "60.0s" in row

    def test_cancelled(self):
        row = format_history_row(
            self._record(cancelled=True, exit_code=-1, duration=3.0)
        )
        assert "cancelled" in row
        assert "3.0s" in row

    def test_long_script_name_truncated(self):
        row = format_history_row(
            self._record(script_name="this-is-a-very-long-script-name-x")
        )
        # 22-char field, truncated
        assert "this-is-a-very-long-sc" in row
        assert "this-is-a-very-long-script-name-x" not in row

    def test_timestamp_without_timezone_suffix(self):
        row = format_history_row(
            self._record(timestamp="2026-05-15T09:11:00")
        )
        assert "2026-05-15 09:11:00" in row
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_history.py::TestFormatHistoryRow -v`
Expected: FAIL — `ImportError: cannot import name 'format_history_row'`.

- [ ] **Step 3: Implement `format_history_row`**

Append to `src/scriptpilot/history.py`:

```python
def format_history_row(r: RunRecord) -> str:
    """Render a single RunRecord as a one-line label for the history modal."""
    ts = r.timestamp.replace("T", " ").split(".")[0].split("+")[0]
    if r.cancelled:
        status = "[yellow]cancelled[/yellow]"
    elif r.timed_out:
        status = "[red]timed out[/red]"
    elif r.exit_code == 0:
        status = "[green]exit 0[/green]"
    else:
        status = f"[red]exit {r.exit_code}[/red]"
    return f"{ts}  {r.script_name:<22.22}  {status}  {r.duration:.1f}s"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_history.py -v`
Expected: all green (existing + 6 new format tests).

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/history.py tests/test_history.py
git commit -m "feat: format_history_row renders RunRecord for history modal"
```

---

## Task 9: HistoryScreen modal + `H` binding + script-highlight sync

Creates the modal screen and wires it into `MainScreen`. UI integration — no new unit tests (manual verification).

**Files:**
- Create: `src/scriptpilot/screens/history.py`
- Modify: `src/scriptpilot/screens/main.py`

- [ ] **Step 1: Create `HistoryScreen`**

`src/scriptpilot/screens/history.py`:

```python
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView

from scriptpilot.history import format_history_row
from scriptpilot.models import RunRecord


class HistoryScreen(ModalScreen[RunRecord | None]):
    """Modal listing recent RunRecords across all scripts."""

    DEFAULT_CSS = """
    HistoryScreen {
        align: center middle;
    }
    HistoryScreen #history-container {
        width: 80%;
        max-width: 120;
        height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    HistoryScreen ListView {
        height: 1fr;
    }
    """

    BINDINGS = [("escape", "dismiss_none", "Close")]

    def __init__(self, records: list[RunRecord]):
        super().__init__()
        self._records = records

    def compose(self) -> ComposeResult:
        with Vertical(id="history-container"):
            yield Label("[bold]Run history[/bold]  [dim](Enter to open, Esc to close)[/dim]")
            with ListView():
                for i, r in enumerate(self._records):
                    yield ListItem(Label(format_history_row(r)), name=str(i))

    def action_dismiss_none(self):
        self.dismiss(None)

    def on_list_view_selected(self, event: ListView.Selected):
        idx = int(event.item.name)
        self.dismiss(self._records[idx])
```

- [ ] **Step 2: Add the `H` binding and handler in `MainScreen`**

In `src/scriptpilot/screens/main.py`:

Add import:
```python
from scriptpilot.screens.history import HistoryScreen
```

Append to `BINDINGS`:
```python
("H", "show_history", "History"),
```

Add the handler and a small list-highlight helper:

```python
def action_show_history(self):
    records = self._history.list_all()
    if not records:
        self.notify("No run history yet", severity="information")
        return

    def on_pick(record: RunRecord | None):
        if record is None:
            return
        script = self._store.get(record.script_id)
        panel = self.query_one(MainPanel)
        if script:
            self._selected_script = script
            self._highlight_script(script.id)
            panel.show_script_details(script, record)
            panel.show_finished_run(record)
        else:
            panel.show_finished_run(record)
            self.notify(
                f"Source script '{record.script_name}' was deleted",
                severity="warning",
            )

    self.app.push_screen(HistoryScreen(records), callback=on_pick)

def _highlight_script(self, script_id: str):
    """Move the ScriptList highlight to the script with the given id (if visible)."""
    from textual.widgets import ListView
    lv = self.query_one(ScriptList).query_one(ListView)
    for i, item in enumerate(lv.children):
        if getattr(item, "name", None) == script_id:
            lv.index = i
            return
```

- [ ] **Step 3: Run the test suite**

Run: `uv run pytest -v`
Expected: all green (no new tests in this task; the formatter is already covered).

- [ ] **Step 4: Manual verification**

```bash
uv run scriptpilot
```

- Run a couple of scripts (one successful, one cancelled with `s`).
- Press `H`. Modal shows two rows: "exit 0" (green) and "cancelled" (yellow).
- Press Enter on one. Modal closes; left list highlight moves to that script; MainPanel shows its output.
- Press `H` again. Press Esc. Modal closes, no panel change.
- Delete a script that has runs in history, then press `H` and select one of its runs: output shows, warning toasts.
- With zero history (fresh `~/.scriptpilot/history.json` empty), press `H` → "No run history yet" toast, no modal.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/screens/history.py src/scriptpilot/screens/main.py
git commit -m "feat: history modal (H) listing recent runs across scripts"
```

---

## Final verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: all green.

- [ ] **Step 2: End-to-end manual smoke test**

```bash
uv run scriptpilot
```

Walk through the acceptance criteria from the spec:

1. `/csv` filters list to scripts whose name/description/tags mention "csv" (case-insensitive).
2. A `sleep 30` script can be cancelled with `s` without waiting for timeout.
3. `H` shows recent runs across all scripts. Selecting opens the run's captured output in `MainPanel` and syncs the left-list highlight to the run's script.
4. Tagging a script `Foo, foo, BAR` displays `{foo, bar}` in dim subscript in the list label.

If any check fails, fix and recommit before considering the plan complete.
