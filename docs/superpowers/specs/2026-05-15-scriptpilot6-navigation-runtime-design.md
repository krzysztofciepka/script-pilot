# ScriptPilot — navigation & runtime control (design)

Date: 2026-05-15
Source task: `~/Notes/Notes/Tasks/Prywatne/script-pilot6.md`

## Summary

Four small, self-contained improvements to the TUI:

1. **Fuzzy filter** on the script list (`/` to focus, substring match across name + description + tags, `Esc` clears and unfocuses).
2. **Tags** as first-class `Script` field — comma-separated input in `EditScreen`, dim subscript in the list label, wired into the filter.
3. **Stop / cancel** a running script with `s`, reusing the executor's existing process-group SIGKILL path.
4. **Cross-script run history modal** opened with `H`, listing recent `RunRecord`s; selecting one shows its output in `MainPanel` and syncs the left-list highlight.

## Non-goals

- Folders / hierarchical organization (tags subsume this).
- Fuzzy ranking (substring is sufficient up to ~100 scripts).
- Per-script run history view (already covered by "last run" line in `MainPanel`).
- Re-running from history (out of scope; user can select the script and press `r`).

## Model & storage changes

Two additive Pydantic fields, both with defaults so existing JSON loads cleanly.

```python
# models.py
class Script(BaseModel):
    ...
    tags: list[str] = []          # NEW

class RunRecord(BaseModel):
    ...
    cancelled: bool = False       # NEW
```

`ScriptStore._write` already dumps `Script` via `model_dump(exclude={"content"})`; `tags` rides along. `HistoryStore._save` already dumps `RunRecord` via `model_dump()`; `cancelled` rides along. Old records load with `cancelled=False` via Pydantic defaults.

### Tag normalization

A new module `src/scriptpilot/tags.py`:

```python
def normalize_tags(raw: str) -> list[str]:
    """Split comma-separated tags; strip, lowercase, drop empties, dedupe (preserve order)."""
    seen: set[str] = set()
    out: list[str] = []
    for piece in raw.split(","):
        t = piece.strip().lower()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out
```

Lives in its own module so the filter logic can import it for case-insensitive query matching without depending on `EditScreen`.

## Cancellation plumbing

### Executor (`src/scriptpilot/executor.py`)

`ExecutionResult` gains `cancelled: bool = False`. `execute_script` accepts an optional `cancel_event: asyncio.Event` and races it against `proc.wait()` and the timeout:

```python
async def execute_script(
    script, arg_values=None, on_output=None, *,
    script_path, python_command="python3",
    cancel_event: asyncio.Event | None = None,
) -> ExecutionResult:
    ...
    timed_out = False
    cancelled = False
    try:
        if cancel_event is None:
            await asyncio.wait_for(proc.wait(), timeout=script.timeout)
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
            elif cancel_event.is_set():
                cancelled = True
            # else: proc.wait() completed naturally — nothing to do.
        if timed_out or cancelled:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()
    finally:
        await asyncio.gather(*read_tasks)

    return ExecutionResult(
        exit_code=proc.returncode if proc.returncode is not None else -1,
        timed_out=timed_out,
        cancelled=cancelled,
        duration=time.monotonic() - start,
    )
```

The existing non-cancel path is preserved verbatim (the `if cancel_event is None` branch), so callers that don't pass an event (e.g. `EditScreen._scratch_execute`) are unaffected.

### MainScreen (`src/scriptpilot/screens/main.py`)

- New binding: `("s", "cancel_script", "Cancel")`.
- New attribute: `self._cancel_event: asyncio.Event | None = None`.
- `_execute` creates `self._cancel_event = asyncio.Event()`, passes it through to `execute_script`, and clears it in a `finally` block.
- Persist `cancelled` onto the `RunRecord` (parallel to `timed_out`).
- Action handler:

```python
def action_cancel_script(self):
    if self._cancel_event is None:
        self.notify("Nothing running", severity="warning")
        return
    self._cancel_event.set()
```

### MainPanel (`src/scriptpilot/widgets/main_panel.py`)

`show_finished_run` adds a `cancelled` branch ahead of `timed_out`:

```python
if run.cancelled:
    status.update(f"[yellow]Cancelled by user[/yellow]  Duration: {run.duration:.1f}s")
elif run.timed_out:
    ...
```

## Fuzzy filter

### Widget (`src/scriptpilot/widgets/script_list.py`)

- A hidden `Input` (id `filter-input`) is added above the `ListView`.
- Pressing `/` (bound on `MainScreen`) calls a public `ScriptList.focus_filter()` which sets the input visible and focuses it.
- `Input.Changed` events on `#filter-input` call `_apply_filter(value)`, which filters `self._scripts` and rebuilds the `ListView`.
- A binding `("escape", "clear_filter", "Clear filter")` on `ScriptList` clears the input, hides it, refocuses the `ListView`, and re-renders the full list.

```python
class ScriptList(Widget):
    DEFAULT_CSS = """
    ScriptList { width: 30; dock: left; border-right: solid $primary; }
    ScriptList Input { display: none; height: 3; }
    ScriptList Input.visible { display: block; }
    ScriptList ListView { height: 1fr; }
    """

    BINDINGS = [("escape", "clear_filter", "Clear filter")]

    def compose(self):
        yield Input(placeholder="Filter…", id="filter-input")
        with ListView():
            for script in self._sorted(self._scripts):
                yield ListItem(Label(self._make_label(script)), name=script.id)

    def focus_filter(self):
        inp = self.query_one("#filter-input", Input)
        inp.add_class("visible")
        inp.focus()

    def action_clear_filter(self):
        inp = self.query_one("#filter-input", Input)
        had_value = bool(inp.value)
        inp.value = ""
        inp.remove_class("visible")
        if had_value:
            self._apply_filter("")
        self.query_one(ListView).focus()

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "filter-input":
            self._apply_filter(event.value)

    def _apply_filter(self, query: str):
        filtered = [s for s in self._scripts if _matches(s, query)]
        lv = self.query_one(ListView)
        lv.clear()
        for script in self._sorted(filtered):
            lv.append(ListItem(Label(self._make_label(script)), name=script.id))


def _matches(script: Script, query: str) -> bool:
    q = query.strip().lower()
    if not q:
        return True
    haystack = " ".join([script.name, script.description, *script.tags]).lower()
    return q in haystack
```

### MainScreen binding

Add `("slash", "focus_filter", "Filter")` to `MainScreen.BINDINGS`. The handler simply calls `self.query_one(ScriptList).focus_filter()`.

When the filter `Input` has focus, slash typed into it is captured as a literal character by Textual's default input handling — no conflict.

### Moving focus from filter to list

After typing a query, the user needs a way to pick an item without losing the filter. Two paths, both implemented:

- **`Down` arrow** while focused on `#filter-input` → focus the `ListView` (which then highlights the first item). Handled via `on_key` on the input: intercept `key.key == "down"`, call `self.query_one(ListView).focus()`, swallow the event.
- **`Enter`** while focused on `#filter-input` → same as Down (handled via `on_input_submitted`).

`Esc` keeps the spec'd semantics: clear filter + hide input + focus list with the *unfiltered* list shown.

### Interaction with `update_scripts`

`update_scripts` (called after add/delete/edit/clone/favorite) must respect the current filter. The simplest approach: store the current query on `self._current_query`, and have `update_scripts` re-apply it after refreshing `self._scripts`. This is a one-liner — `_apply_filter(self._current_query)` instead of the existing `lv.clear()` + append loop.

## Tags in EditScreen and list label

### EditScreen (`src/scriptpilot/screens/edit.py`)

Insert a Tags row immediately after Description:

```python
yield Label("Tags (comma-separated):")
yield Input(
    value=", ".join(s.tags) if s else "",
    placeholder="csv, jira, daily",
    id="tags-input",
)
```

`_collect_form` reads and normalizes:

```python
from scriptpilot.tags import normalize_tags
...
tags_raw = self.query_one("#tags-input", Input).value
tags = normalize_tags(tags_raw)
```

…and assigns `tags` on both the in-place edit branch (`self._script.tags = tags`) and the new-Script return branch.

### Clone

`MainScreen.action_clone_script` builds a `Script(...)` manually. Add `tags=list(original.tags)`.

### List label (`widgets/script_list.py`)

```python
@staticmethod
def _make_label(script: Script) -> str:
    star = " *" if script.favorite else ""
    base = f"[{TYPE_LABELS.get(script.type, '??')}]{star} {script.name}"
    if script.tags:
        base += f" [dim]{{{', '.join(script.tags)}}}[/dim]"
    return base
```

`Label` already renders Textual/Rich markup, so `[dim]…[/dim]` styles correctly.

## Run history modal

### Screen (`src/scriptpilot/screens/history.py`, new)

```python
class HistoryScreen(ModalScreen[RunRecord | None]):
    DEFAULT_CSS = """
    HistoryScreen { align: center middle; }
    HistoryScreen #history-container {
        width: 80%; max-width: 120; height: 80%;
        background: $surface; border: solid $primary; padding: 1 2;
    }
    HistoryScreen ListView { height: 1fr; }
    """

    BINDINGS = [("escape", "dismiss_none", "Close")]

    def __init__(self, records: list[RunRecord]):
        super().__init__()
        self._records = records

    def compose(self):
        with Vertical(id="history-container"):
            yield Label("[bold]Run history[/bold]")
            with ListView():
                for i, r in enumerate(self._records):
                    yield ListItem(Label(format_history_row(r)), name=str(i))

    def action_dismiss_none(self):
        self.dismiss(None)

    def on_list_view_selected(self, event: ListView.Selected):
        idx = int(event.item.name)
        self.dismiss(self._records[idx])
```

### Row formatter (in `history.py`, next to `RunRecord`)

```python
def format_history_row(r: RunRecord) -> str:
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

The 22-char truncation on `script_name` keeps rows aligned without dynamic measurement. Timestamps are stored as ISO 8601 strings in UTC; we strip the `T` and the fractional/`+00:00` suffix for display.

### MainScreen integration

- Binding: `("H", "show_history", "History")`.
- Handler:

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
```

`_highlight_script(script_id)` walks the `ListView` items and sets its `index` to the position of the matching item (None if not found, e.g. when filtered out).

## Testing

| Module | Test file | What |
|---|---|---|
| `tags.normalize_tags` | `tests/test_tags.py` (new) | strip/lowercase/dedupe; empty input → `[]`; preserves first-seen order. |
| `models.Script.tags` default | `tests/test_models.py` | default `[]`; round-trips through `model_dump` / `model_validate`. |
| `models.RunRecord.cancelled` default | `tests/test_models.py` | default `False`; loads from old JSON (no field) without error. |
| `executor` cancel path | `tests/test_executor.py` | Long-sleep bash script + `cancel_event`; schedule `cancel_event.set()` ~50ms after start; assert `cancelled=True`, `timed_out=False`, exit_code != 0, duration < `script.timeout`. |
| `widgets.script_list._matches` | `tests/test_script_list.py` (new) | substring matches across name/description/tags; case-insensitive; empty query matches everything. |
| `history.format_history_row` | `tests/test_history.py` | exit 0 / exit N / timed_out / cancelled branches; timestamp formatting. |

Manual verification checklist (run `scriptpilot`):

1. Press `/`, type `csv`, list narrows. `Esc` clears + unfocuses + re-shows full list.
2. New script with tags `Foo, foo , BAR` → list shows `{foo, bar}`.
3. Long-sleep script + `s` → status reads "Cancelled by user", record appears in `H` modal as "cancelled".
4. `H` opens modal; pick an old run → left list highlights its script, MainPanel shows the run's output and script header.
5. `H` with empty history → notify, no modal.
6. Delete a script that has runs in history; press `H`, pick one of its runs → output still shows, warning notified, left list unchanged.

## Files touched

| File | Change |
|---|---|
| `src/scriptpilot/models.py` | `Script.tags`, `RunRecord.cancelled` |
| `src/scriptpilot/tags.py` | NEW — `normalize_tags` |
| `src/scriptpilot/executor.py` | `cancel_event` parameter, `cancelled` field on `ExecutionResult` |
| `src/scriptpilot/history.py` | `format_history_row` |
| `src/scriptpilot/screens/main.py` | `s` / `slash` / `H` bindings + handlers; cancel-event lifecycle; `_highlight_script` helper |
| `src/scriptpilot/screens/edit.py` | Tags input + normalize on save |
| `src/scriptpilot/screens/history.py` | NEW — `HistoryScreen` |
| `src/scriptpilot/widgets/script_list.py` | Filter input, `_matches`, `_apply_filter`, label includes tags |
| `src/scriptpilot/widgets/main_panel.py` | `cancelled` status branch in `show_finished_run` |
| `tests/test_models.py` | New cases for `tags` and `cancelled` defaults |
| `tests/test_history.py` | `format_history_row` tests |
| `tests/test_executor.py` | Cancel-event test |
| `tests/test_tags.py` (new) | Normalization tests |
| `tests/test_script_list.py` (new) | `_matches` tests |
