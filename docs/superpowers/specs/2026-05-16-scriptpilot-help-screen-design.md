# ScriptPilot — In-app help screen (Task scriptpilot7)

## Goal

Add a "man page" inside the TUI: a modal screen that walks the user through ScriptPilot's features and every key binding, split into chapters, concise and easy to understand. Triggered with `?` or `F1`.

The reference section of the help must stay accurate as bindings are added or renamed, with no manual upkeep.

## Decisions

| Topic | Choice | Rationale |
|-------|--------|-----------|
| Trigger key | `?` and `F1` | `?` is the TUI convention (vim/less/k9s/lazygit); `F1` is universal. `ctrl+h` collides with backspace in most terminals. |
| Layout | Textual's `MarkdownViewer` | Purpose-built for a navigable document; TOC sidebar comes for free; standard Markdown rendering for code blocks, lists, tables. |
| Content source | External `src/scriptpilot/help.md` | Real Markdown, edited like any other doc; hatchling bundles files under `packages` automatically; PyInstaller picks it up via one `--add-data` flag. |
| Drift handling | Hand-written prose chapters; auto-generated shortcuts reference from `BINDINGS` at runtime | Prose stays human; the table is *always* accurate because it's generated from the source of truth. |

## Chapter outline

The `.md` is structured as `##` headings so each chapter becomes a TOC entry in `MarkdownViewer`.

| # | Chapter | Covers |
|---|---------|--------|
| 1 | Welcome | One-paragraph intro + 30-second tour (`n` new, `r` run, `g` AI, `q` quit). |
| 2 | Managing scripts | `n`, `e`, `E` (external editor), `d`, `c` (clone), `f` (favorite), `/` (filter), tags, arg styles (positional vs flags). |
| 3 | Running scripts | `r`, `k` (cancel), streaming output, `o` (save output), `y` (copy), `J` (view JSON), `p` (prompt scripts), `H` (history). |
| 4 | AI generation | `g`, `BLACKBOX_API_KEY` (env or `~/.scriptpilot/.env`), default model in Settings, modifying existing scripts. |
| 5 | Reproducible execution | Per-script working directory, per-script env vars, the global `~/.scriptpilot/.env` secrets file with precedence rules, PEP 723 deps via `uv run --script`. |
| 6 | Settings, themes & upgrades | `s` settings, `t` theme, `scriptpilot --upgrade`, `scriptpilot --version`, `~/.scriptpilot/config.json`. |
| R | Reference: Shortcuts *(auto-generated)* | Flat per-screen tables of every binding. |

## Components

```
src/scriptpilot/
├── screens/help.py        # HelpScreen(ModalScreen[None]): MarkdownViewer over rendered content
├── help.py                # load_help_markdown(), collect_bindings(), render_shortcuts_table()
├── help.md                # prose chapters + <!-- SHORTCUTS_TABLE --> placeholder
└── app.py                 # adds ("?", "show_help") and ("f1", "show_help") to BINDINGS
```

### `scriptpilot/help.py`

Three small pure functions, all testable without Textual.

- `load_help_markdown() -> str`
  Read `help.md` via `importlib.resources.files("scriptpilot") / "help.md"`, substitute the `<!-- SHORTCUTS_TABLE -->` placeholder with the rendered shortcuts table, return.

- `collect_bindings() -> list[BindingGroup]`
  Walk a hardcoded list of `(class, label)` pairs and pull each class's `BINDINGS`. Filters out entries whose description is empty (Textual treats those as hidden). Imports of screen/widget classes are done lazily inside the function to break the `app → screens.help → help → app` import cycle.

  Source-of-truth list:
  ```python
  _GROUPS = [
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

- `render_shortcuts_table(groups) -> str`
  Render to Markdown: one `### <label>` heading per group, then a `| Key | Action |` table. Keys render as inline code (`` `?` ``, `` `f1` ``, `` `slash` ``).

`BindingGroup` is a tiny dataclass: `label: str`, `items: list[tuple[str, str]]` (key, description).

### `screens/help.py`

`HelpScreen(ModalScreen[None])`. Reuses the existing modal style from `HistoryScreen`/`JsonViewScreen` (80% width/height, `$surface` background, `$primary` border, padding `1 2`). Composes a `MarkdownViewer(show_table_of_contents=True)`. Bindings: `escape`, `q`, `?` → close.

### `app.py`

Adds two new entries to `ScriptPilotApp.BINDINGS`:
```python
("?", "show_help", "Help"),
("f1", "show_help", "Help"),
```
And the action:
```python
def action_show_help(self):
    self.push_screen(HelpScreen())
```

## Sync mechanism

Chapter 6 (Reference: Shortcuts) is generated at modal-open time:

1. `HelpScreen.compose()` calls `load_help_markdown()`.
2. `load_help_markdown` reads the raw `help.md` (chapters 1–6 in prose, plus a `<!-- SHORTCUTS_TABLE -->` placeholder).
3. `collect_bindings()` walks `_GROUPS`, pulls each class's `BINDINGS`, filters out empty-description entries.
4. `render_shortcuts_table()` produces a Markdown string.
5. The placeholder is replaced by the rendered table; the result is fed to `MarkdownViewer`.

The placeholder approach (vs. appending) lets the prose author add a one-line intro to chapter 6 inside `help.md` without the code knowing.

## Packaging

- **Wheel (hatchling)**: no `pyproject.toml` change — `packages = ["src/scriptpilot"]` already includes non-Python files under that directory.
- **PyInstaller**:
  - `scriptpilot.spec`: add `('src/scriptpilot/help.md', 'scriptpilot')` to `datas`.
  - `.github/workflows/build.yml` and `scripts/build.sh`: add `--add-data src/scriptpilot/help.md:scriptpilot` to the `pyinstaller` invocation.

Runtime loading uses `importlib.resources.files("scriptpilot") / "help.md"`, which works identically in wheel and frozen contexts.

## Testing

`tests/test_help.py`, four focused tests:

1. **`test_collect_bindings_includes_visible_app_keys`** — assert `?`, `f1`, `q`, `s`, `g`, `t` all appear in the "App" group. Guards against accidental removal of App bindings.

2. **`test_collect_bindings_skips_empty_descriptions`** — verify entries with empty descriptions are filtered out.

3. **`test_render_shortcuts_table_is_valid_markdown`** — render against a fixed `BindingGroup` and assert structure: `### <label>` heading per group, `| Key | Action |` header row, keys wrapped in inline code.

4. **`test_load_help_markdown_substitutes_placeholder_and_lists_every_binding`** — end-to-end: call `load_help_markdown()`, assert the placeholder is gone, assert every key from `collect_bindings()` appears somewhere in the returned string. This is the drift catcher.

No snapshot test for `HelpScreen` rendering — it's a `MarkdownViewer` over our content, and Textual already tests its widgets.

## Non-goals

- No search inside the help.
- No interactive tutorials.
- No language switching / i18n.
- No mouse-friendly buttons; standard `MarkdownViewer` keyboard nav is sufficient.

## Files touched

```
src/scriptpilot/__init__.py       # version bump for the release commit
src/scriptpilot/app.py            # new bindings + action
src/scriptpilot/help.py           # NEW: loader, binding collector, table renderer
src/scriptpilot/help.md           # NEW: prose chapters + placeholder
src/scriptpilot/screens/help.py   # NEW: HelpScreen
scriptpilot.spec                  # add help.md to datas
scripts/build.sh                  # add --add-data
.github/workflows/build.yml       # add --add-data
tests/test_help.py                # NEW: four tests
README.md                         # mention ? / F1 in shortcuts table
pyproject.toml                    # version bump
```
