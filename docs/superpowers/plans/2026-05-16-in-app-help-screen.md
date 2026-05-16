# In-App Help Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `?` / `F1` modal help screen that walks through ScriptPilot's features and key bindings.

**Architecture:** A `ModalScreen` wrapping Textual's built-in `MarkdownViewer` (TOC sidebar). Prose chapters live in a bundled `src/scriptpilot/help.md`; the "Reference: Shortcuts" chapter is generated at runtime from each screen's `BINDINGS` via a `<!-- SHORTCUTS_TABLE -->` placeholder substitution.

**Tech Stack:** Python 3.10+, Textual, pytest, hatchling (wheel), PyInstaller (binary).

**Spec:** `docs/superpowers/specs/2026-05-16-scriptpilot-help-screen-design.md`

**Files touched:**
- Create: `src/scriptpilot/help.py`, `src/scriptpilot/help.md`, `src/scriptpilot/screens/help.py`, `tests/test_help.py`
- Modify: `src/scriptpilot/app.py`, `scriptpilot.spec`, `scripts/build.sh`, `.github/workflows/build.yml`, `README.md`

---

### Task 1: `BindingGroup` + `render_shortcuts_table`

Pure data + Markdown rendering, no Textual dependency.

**Files:**
- Create: `src/scriptpilot/help.py`
- Test: `tests/test_help.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_help.py`:

```python
from __future__ import annotations

from scriptpilot.help import BindingGroup, render_shortcuts_table


class TestRenderShortcutsTable:
    def test_emits_heading_and_markdown_table_per_group(self):
        groups = [
            BindingGroup(
                label="App",
                items=[("q", "Quit"), ("?", "Help")],
            ),
            BindingGroup(
                label="Main view",
                items=[("slash", "Filter"), ("r", "Run")],
            ),
        ]

        out = render_shortcuts_table(groups)

        assert "### App" in out
        assert "### Main view" in out
        # Header row of a GitHub-style Markdown table
        assert "| Key | Action |" in out
        assert "| --- | --- |" in out
        # Keys wrapped in inline code
        assert "| `q` | Quit |" in out
        assert "| `?` | Help |" in out
        assert "| `slash` | Filter |" in out
        assert "| `r` | Run |" in out

    def test_empty_group_is_omitted(self):
        groups = [
            BindingGroup(label="Empty", items=[]),
            BindingGroup(label="Real", items=[("q", "Quit")]),
        ]

        out = render_shortcuts_table(groups)

        assert "### Empty" not in out
        assert "### Real" in out
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/test_help.py -v
```

Expected: `ModuleNotFoundError: No module named 'scriptpilot.help'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/scriptpilot/help.py`:

```python
"""In-app help: chapter loader + auto-generated shortcuts reference."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BindingGroup:
    """A named group of (key, description) pairs for the shortcuts reference."""

    label: str
    items: list[tuple[str, str]] = field(default_factory=list)


def render_shortcuts_table(groups: list[BindingGroup]) -> str:
    """Render binding groups into Markdown. Empty groups are omitted."""
    parts: list[str] = []
    for g in groups:
        if not g.items:
            continue
        parts.append(f"### {g.label}\n")
        parts.append("| Key | Action |")
        parts.append("| --- | --- |")
        for key, desc in g.items:
            parts.append(f"| `{key}` | {desc} |")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/test_help.py -v
```

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/help.py tests/test_help.py
git commit -m "feat: BindingGroup + render_shortcuts_table for in-app help"
```

---

### Task 2: `collect_bindings`

Walk a hardcoded list of `(class, label)` pairs, pull each class's `BINDINGS`, filter out empty descriptions. Lazy imports inside the function to avoid the `app → screens.help → help → app` cycle. Note: `HelpScreen` isn't in `_GROUPS` yet — it's added in Task 5.

**Files:**
- Modify: `src/scriptpilot/help.py`
- Test: `tests/test_help.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_help.py`:

```python
from scriptpilot.help import collect_bindings


class TestCollectBindings:
    def test_app_group_contains_visible_app_keys(self):
        groups = {g.label: g for g in collect_bindings()}
        assert "App" in groups
        keys = {k for k, _ in groups["App"].items}
        # Every currently visible App binding.
        assert {"q", "s", "g", "t"}.issubset(keys)

    def test_main_view_includes_run_and_filter(self):
        groups = {g.label: g for g in collect_bindings()}
        assert "Main view" in groups
        items = dict(groups["Main view"].items)
        assert items["r"] == "Run"
        assert items["slash"] == "Filter"
        assert items["H"] == "History"

    def test_skips_empty_descriptions(self, monkeypatch):
        """Bindings with an empty description string are hidden in Textual; filter them."""
        from scriptpilot import help as help_mod

        class FakeApp:
            BINDINGS = [
                ("a", "noop", "Visible"),
                ("b", "noop", ""),
            ]

        monkeypatch.setattr(help_mod, "_resolve_groups", lambda: [(FakeApp, "Fake")])

        groups = collect_bindings()
        items = dict(groups[0].items)
        assert items == {"a": "Visible"}

    def test_accepts_textual_binding_objects(self, monkeypatch):
        """Textual sometimes stores BINDINGS as Binding(...) objects, not tuples."""
        from scriptpilot import help as help_mod
        from textual.binding import Binding

        class FakeApp:
            BINDINGS = [Binding("x", "noop", "FromObject")]

        monkeypatch.setattr(help_mod, "_resolve_groups", lambda: [(FakeApp, "Fake")])

        groups = collect_bindings()
        items = dict(groups[0].items)
        assert items == {"x": "FromObject"}
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/test_help.py::TestCollectBindings -v
```

Expected: `ImportError: cannot import name 'collect_bindings'`.

- [ ] **Step 3: Add `collect_bindings` and `_resolve_groups` to `src/scriptpilot/help.py`**

Append to `src/scriptpilot/help.py`:

```python
def _resolve_groups() -> list[tuple[type, str]]:
    """Source-of-truth list of (class, label) pairs whose BINDINGS get documented.

    Lazy imports break the app → screens → help → app cycle.
    """
    from scriptpilot.app import ScriptPilotApp
    from scriptpilot.screens.edit import EditScreen
    from scriptpilot.screens.history import HistoryScreen
    from scriptpilot.screens.json_view import JsonViewScreen
    from scriptpilot.screens.main import MainScreen
    from scriptpilot.widgets.main_panel import MainPanel
    from scriptpilot.widgets.script_list import ScriptList

    return [
        (ScriptPilotApp, "App"),
        (MainScreen, "Main view"),
        (MainPanel, "Output panel"),
        (ScriptList, "Script list"),
        (EditScreen, "Edit screen"),
        (HistoryScreen, "History modal"),
        (JsonViewScreen, "JSON view"),
    ]


def _normalize(binding) -> tuple[str, str] | None:
    """Return (key, description) for a BINDINGS entry, or None if it should be hidden."""
    if isinstance(binding, tuple):
        if len(binding) < 3:
            return None
        key, _action, desc = binding[0], binding[1], binding[2]
    else:
        # Textual Binding object (or compatible).
        key = getattr(binding, "key", None)
        desc = getattr(binding, "description", None)
        if not key:
            return None
    if not desc:
        return None
    return key, desc


def collect_bindings() -> list[BindingGroup]:
    """Return one BindingGroup per (class, label) in _resolve_groups()."""
    result: list[BindingGroup] = []
    for cls, label in _resolve_groups():
        raw = getattr(cls, "BINDINGS", []) or []
        items: list[tuple[str, str]] = []
        for b in raw:
            n = _normalize(b)
            if n is not None:
                items.append(n)
        result.append(BindingGroup(label=label, items=items))
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/test_help.py -v
```

Expected: all `TestCollectBindings` tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/help.py tests/test_help.py
git commit -m "feat: collect_bindings walks screen classes and filters hidden bindings"
```

---

### Task 3: `load_help_markdown` + skeleton `help.md`

Read `help.md` from package resources, substitute `<!-- SHORTCUTS_TABLE -->` with the rendered shortcuts table.

**Files:**
- Create: `src/scriptpilot/help.md`
- Modify: `src/scriptpilot/help.py`
- Test: `tests/test_help.py`

- [ ] **Step 1: Create a minimal `src/scriptpilot/help.md`**

```markdown
# ScriptPilot — Help

## Welcome

ScriptPilot is a TUI for managing and running automation scripts.

## Reference: Shortcuts

<!-- SHORTCUTS_TABLE -->
```

(Final prose comes in Task 4 — we want a placeholder file in place so the loader test has something to read.)

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_help.py`:

```python
from scriptpilot.help import load_help_markdown


class TestLoadHelpMarkdown:
    def test_substitutes_placeholder(self):
        out = load_help_markdown()
        assert "<!-- SHORTCUTS_TABLE -->" not in out
        # The generated table has these structural markers.
        assert "| Key | Action |" in out

    def test_every_collected_binding_appears_in_output(self):
        out = load_help_markdown()
        for group in collect_bindings():
            for key, _desc in group.items:
                assert f"`{key}`" in out, f"key {key!r} missing from rendered help"

    def test_keeps_prose_chapter_headings(self):
        out = load_help_markdown()
        assert "## Welcome" in out
        assert "## Reference: Shortcuts" in out
```

- [ ] **Step 3: Run tests to verify they fail**

```
uv run pytest tests/test_help.py::TestLoadHelpMarkdown -v
```

Expected: `ImportError: cannot import name 'load_help_markdown'`.

- [ ] **Step 4: Add `load_help_markdown` to `src/scriptpilot/help.py`**

Append to `src/scriptpilot/help.py`:

```python
import importlib.resources

PLACEHOLDER = "<!-- SHORTCUTS_TABLE -->"


def load_help_markdown() -> str:
    """Return the help text with the shortcuts placeholder substituted."""
    raw = (importlib.resources.files("scriptpilot") / "help.md").read_text(
        encoding="utf-8"
    )
    table = render_shortcuts_table(collect_bindings())
    return raw.replace(PLACEHOLDER, table)
```

- [ ] **Step 5: Run tests to verify they pass**

```
uv run pytest tests/test_help.py -v
```

Expected: every test in the file passes.

- [ ] **Step 6: Commit**

```bash
git add src/scriptpilot/help.py src/scriptpilot/help.md tests/test_help.py
git commit -m "feat: load_help_markdown substitutes shortcuts placeholder"
```

---

### Task 4: Author the full help content

Replace the skeleton `help.md` with the six prose chapters. The Reference: Shortcuts chapter stays as just the placeholder — the table is generated.

**Files:**
- Modify: `src/scriptpilot/help.md`

- [ ] **Step 1: Replace `src/scriptpilot/help.md` with the full content**

```markdown
# ScriptPilot — Help

Press `?` or `F1` from anywhere to reopen this help. Use `↑`/`↓` and `Enter` in the sidebar to jump between chapters; `Esc` or `q` to close.

## Welcome

ScriptPilot is a terminal app for creating, managing, and running automation scripts in **bash**, **Python**, and **JavaScript** — with optional AI-powered script generation via blackbox.ai.

Quick tour:

- `n` — create a new script
- `r` — run the selected script
- `g` — describe a script in plain English and let an LLM write it
- `s` — open settings
- `q` — quit

Everything below is the long form of those ideas, plus every keyboard shortcut at the bottom.

## Managing scripts

Your scripts live in `~/.scriptpilot/scripts/` as individual files on disk. ScriptPilot is the editor and runner — your scripts are just plain files you can also edit with your normal tools.

- `n` — **new script**. You pick a name and language, then the editor opens.
- `e` — **edit** the selected script's metadata, body, arguments, working directory, env vars.
- `E` — open the body in your **external editor** (`$EDITOR`). Saves on exit.
- `d` — **delete** the selected script (confirms first).
- `c` — **clone** the selected script. Useful for derivative variants.
- `f` — **favorite** / unfavorite. Favorites sort to the top.
- `/` — **filter** the list by name / tag substring. `Esc` clears the filter.

**Tags** are free-form labels (comma-separated in the edit screen). They show next to the name and are searched by `/`.

**Argument style.** Each script declares its arguments as either:

- **positional** — passed as `$1 $2 ...` to the script;
- **flags** — passed as `--name value` (or just `--name` for booleans).

Pick whichever is idiomatic for the script's language; ScriptPilot builds the right `argv` for you at run time.

**Argument types:** `string`, `integer`, `boolean`, `path`, `choice`. `path` resolves `~` and joins relatives against the script's working directory before the script sees them.

## Running scripts

`r` runs the selected script. If it has arguments, a form pops up first; press `Enter` to launch once the fields are valid.

While the script is running:

- Output streams into the panel on the right in real time.
- `k` — **cancel** the running process.
- The status bar shows elapsed time and exit code when it finishes.

When it's done:

- `o` — **save** the full output to a file.
- `y` — **copy** the full output to the clipboard.
- `J` — if the output is JSON, open it in a **JSON viewer** modal.
- `p` — open the **prompt scripts** menu for the current script (interactive sub-prompts the script defines).
- `H` — **history**: list of recent runs across all scripts. `Enter` re-opens a past run; `Esc` closes.

## AI generation

`g` opens the AI generation screen. Type a plain-English description, pick the language, hit submit; ScriptPilot calls blackbox.ai and produces a complete script with argument declarations.

**Setup:**

1. Get a key from <https://www.blackbox.ai/>.
2. Export it as `BLACKBOX_API_KEY` **or** add it to `~/.scriptpilot/.env` (one `KEY=VALUE` per line).
3. Optionally set the default model in **Settings** (`s`). Default is `blackboxai/minimax/minimax-m2.5`.

**Modifying an existing script with AI:** open the edit screen and use the modify-with-AI action — describe the change, and the LLM rewrites the script in place.

## Reproducible execution

Each script can pin the environment it runs in, so relative paths and per-script overrides Just Work — no matter where you launch ScriptPilot from.

- **Working directory.** Set in the edit screen. `~` is expanded at run time. Empty means `~`. A missing or non-directory path fails the run with a clear error.
- **Per-script env vars.** `KEY=VALUE` rows in the edit screen. Use this for non-secrets like `ENVIRONMENT=staging`.
- **Global secrets file** at `~/.scriptpilot/.env`. Plain `KEY=VALUE` lines (no `export`, no interpolation, no multiline). `#` comments are allowed. **Use this for API tokens.** Don't paste secrets into per-script env — they'd live with the script body.

Precedence (low → high): `os.environ` < `~/.scriptpilot/.env` < per-script env.

**Python deps via PEP 723.** ScriptPilot runs Python scripts with `uv run --script` by default, so a script with this header gets its deps installed automatically:

```python
# /// script
# dependencies = ["pandas", "openpyxl"]
# ///
import pandas as pd
print(pd.read_csv("input.csv").shape)
```

Switch the Python command to `python3` in Settings if you don't have `uv` installed — PEP 723 won't be honoured in that mode.

## Settings, themes & upgrades

- `s` — **Settings**. Default model, scripts directory, Python command.
- `t` — **toggle theme** between dark and light. Persists across sessions.

Config lives at `~/.scriptpilot/config.json`. Scripts live in the `scripts_dir` you pick (default `~/.scriptpilot/scripts/`).

**On the command line:**

- `scriptpilot --version` — prints the version.
- `scriptpilot --upgrade` — downloads the latest release binary, verifies its sha256 against the GitHub API, and atomically replaces the running binary. Works only on the standalone Linux binary; for `uv tool` installs, run `uv tool upgrade scriptpilot`.

## Reference: Shortcuts

Every binding, grouped by context. Generated from the source.

<!-- SHORTCUTS_TABLE -->
```

- [ ] **Step 2: Run all tests**

```
uv run pytest tests/test_help.py -v
```

Expected: all pass. The drift test (`test_every_collected_binding_appears_in_output`) verifies the generated table contains every key.

- [ ] **Step 3: Commit**

```bash
git add src/scriptpilot/help.md
git commit -m "docs: author full help.md prose chapters"
```

---

### Task 5: `HelpScreen` modal

A `ModalScreen` that loads `help.md` and renders it through Textual's `MarkdownViewer`. Also: add `HelpScreen` to `_resolve_groups` so it appears in the shortcuts reference.

**Files:**
- Create: `src/scriptpilot/screens/help.py`
- Modify: `src/scriptpilot/help.py`

- [ ] **Step 1: Create the modal**

Create `src/scriptpilot/screens/help.py`:

```python
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import MarkdownViewer

from scriptpilot.help import load_help_markdown


class HelpScreen(ModalScreen[None]):
    """Modal man-page: prose chapters + auto-generated shortcuts reference."""

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    HelpScreen #help-container {
        width: 90%;
        max-width: 140;
        height: 90%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    HelpScreen MarkdownViewer {
        height: 1fr;
    }
    """

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("?", "close", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-container"):
            yield MarkdownViewer(
                markdown=load_help_markdown(),
                show_table_of_contents=True,
            )

    def action_close(self) -> None:
        self.dismiss(None)
```

- [ ] **Step 2: Add `HelpScreen` to `_resolve_groups`**

In `src/scriptpilot/help.py`, update `_resolve_groups` to include `HelpScreen` at the end:

```python
def _resolve_groups() -> list[tuple[type, str]]:
    """Source-of-truth list of (class, label) pairs whose BINDINGS get documented.

    Lazy imports break the app → screens → help → app cycle.
    """
    from scriptpilot.app import ScriptPilotApp
    from scriptpilot.screens.edit import EditScreen
    from scriptpilot.screens.help import HelpScreen
    from scriptpilot.screens.history import HistoryScreen
    from scriptpilot.screens.json_view import JsonViewScreen
    from scriptpilot.screens.main import MainScreen
    from scriptpilot.widgets.main_panel import MainPanel
    from scriptpilot.widgets.script_list import ScriptList

    return [
        (ScriptPilotApp, "App"),
        (MainScreen, "Main view"),
        (MainPanel, "Output panel"),
        (ScriptList, "Script list"),
        (EditScreen, "Edit screen"),
        (HistoryScreen, "History modal"),
        (JsonViewScreen, "JSON view"),
        (HelpScreen, "Help"),
    ]
```

- [ ] **Step 3: Run all tests**

```
uv run pytest tests/test_help.py -v
```

Expected: all pass. `test_every_collected_binding_appears_in_output` now also sees `escape`, `q`, and `?` from `HelpScreen`'s bindings, and they appear in the generated table.

- [ ] **Step 4: Commit**

```bash
git add src/scriptpilot/screens/help.py src/scriptpilot/help.py
git commit -m "feat: HelpScreen modal renders help.md via MarkdownViewer"
```

---

### Task 6: Wire `?` and `F1` into the App + add `action_show_help`

**Files:**
- Modify: `src/scriptpilot/app.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_help.py`:

```python
class TestAppBindings:
    def test_help_bindings_present_on_app_class(self):
        from scriptpilot.app import ScriptPilotApp

        keys = {b[0] for b in ScriptPilotApp.BINDINGS if isinstance(b, tuple)}
        assert "?" in keys
        assert "f1" in keys

    def test_help_appears_in_collected_app_group(self):
        groups = {g.label: g for g in collect_bindings()}
        items = dict(groups["App"].items)
        assert items.get("?") == "Help"
        assert items.get("f1") == "Help"
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/test_help.py::TestAppBindings -v
```

Expected: `assert "?" in keys` fails.

- [ ] **Step 3: Add bindings + action to `ScriptPilotApp`**

In `src/scriptpilot/app.py`, update `BINDINGS` (currently lines 24-29) to add the two new entries:

```python
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("s", "open_settings", "Settings"),
        ("g", "generate", "Generate"),
        ("t", "toggle_dark", "Theme"),
        ("?", "show_help", "Help"),
        ("f1", "show_help", "Help"),
    ]
```

And add the action method (anywhere alongside the other `action_*` methods):

```python
    def action_show_help(self):
        from scriptpilot.screens.help import HelpScreen
        self.push_screen(HelpScreen())
```

- [ ] **Step 4: Run all tests**

```
uv run pytest -q
```

Expected: full suite passes.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/app.py tests/test_help.py
git commit -m "feat: bind ? and F1 to open the in-app help screen"
```

---

### Task 7: Manual smoke test in the TUI

- [ ] **Step 1: Launch ScriptPilot**

```
uv run scriptpilot
```

- [ ] **Step 2: Verify each of these manually**

1. Press `?` from the main screen — the help modal opens with the welcome chapter visible and a TOC sidebar.
2. Navigate the TOC with the arrow keys; selecting a chapter scrolls the right pane.
3. Scroll the content with `Page Up`/`Page Down`.
4. Confirm the **Reference: Shortcuts** chapter contains a section for each group (App, Main view, Output panel, Script list, Edit screen, History modal, JSON view, Help) and lists every binding.
5. Press `?` while the help is open — the modal closes (toggle).
6. Reopen with `F1` — same modal.
7. Press `Esc` — closes.
8. Reopen, then press `q` — closes (not "quit the app").
9. Quit with `q` from the main screen — confirm the app actually quits (no leftover binding capture).

Stop and investigate if any step misbehaves before moving on. There's no automated test for these — visual confirmation is the bar.

---

### Task 8: Bundle `help.md` in the PyInstaller binary

**Files:**
- Modify: `scriptpilot.spec`, `scripts/build.sh`, `.github/workflows/build.yml`

- [ ] **Step 1: Update `scriptpilot.spec`**

In `scriptpilot.spec`, change the `datas` block (currently lines 4-5) from:

```python
datas = []
datas += collect_data_files('textual')
```

to:

```python
datas = []
datas += collect_data_files('textual')
datas += [('src/scriptpilot/help.md', 'scriptpilot')]
```

- [ ] **Step 2: Update `scripts/build.sh`**

In `scripts/build.sh`, add a line to the `pyinstaller` invocation after `--collect-data textual`:

```bash
uv run pyinstaller \
    --onefile \
    --name scriptpilot \
    --hidden-import textual \
    --hidden-import textual.widgets \
    --hidden-import textual.screen \
    --hidden-import textual.css \
    --hidden-import httpx \
    --hidden-import pydantic \
    --collect-data textual \
    --add-data src/scriptpilot/help.md:scriptpilot \
    src/scriptpilot/__main__.py
```

- [ ] **Step 3: Update `.github/workflows/build.yml`**

In `.github/workflows/build.yml`, add the same `--add-data` flag inside the `Build binary` step (currently the multi-line `uv run pyinstaller ...` block at lines 27-38):

```yaml
      - name: Build binary
        run: |
          uv run pyinstaller \
            --onefile \
            --name scriptpilot \
            --hidden-import textual \
            --hidden-import textual.widgets \
            --hidden-import textual.screen \
            --hidden-import textual.css \
            --hidden-import httpx \
            --hidden-import pydantic \
            --collect-data textual \
            --add-data src/scriptpilot/help.md:scriptpilot \
            src/scriptpilot/__main__.py
```

- [ ] **Step 4: Local build smoke test**

```
bash scripts/build.sh
./dist/scriptpilot --version
```

Expected: prints `scriptpilot vX.Y.Z`. (We don't fully launch the TUI from `dist/` here — manual UI testing already happened in Task 7. This step just confirms the binary builds with the new data file.)

- [ ] **Step 5: Commit**

```bash
git add scriptpilot.spec scripts/build.sh .github/workflows/build.yml
git commit -m "build: bundle help.md into the PyInstaller binary"
```

---

### Task 9: README mention

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add `?` and `F1` to the keyboard shortcuts table**

In `README.md`, find the `## Keyboard Shortcuts` section (the one with `| Key | Action |`). Insert a row for `?` / `F1` right above the `q` row:

```markdown
| `?` / `F1` | Open in-app help |
| `q` | Quit |
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: mention ? / F1 help shortcut in README"
```

---

## Acceptance

When all tasks are done:

- `uv run pytest -q` is green (the existing 297 + the new `test_help.py` tests).
- `uv run scriptpilot` opens the help modal with `?` or `F1`.
- The Reference: Shortcuts chapter contains every binding from every screen, no `<!-- SHORTCUTS_TABLE -->` leakage.
- `dist/scriptpilot` (built locally) starts and reports its version.
- README's shortcuts table lists `?` / `F1`.
