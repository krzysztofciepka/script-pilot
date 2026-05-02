# ScriptPilot — Argument Types & Validation

**Status:** Design
**Date:** 2026-05-02

## Problem

ScriptPilot's argument model is too thin for real automations:

1. Only `string | boolean | integer` exist — no `path` (the most common kind for automation), no enumerated `choice` (env=dev|staging|prod, region, customer-tier).
2. Integer fields silently pass typos to argv as strings — `RunScreen` only validates required-ness at run time (`src/scriptpilot/screens/run.py:78`).
3. Argv is always positional. Modern CLI scripts (argparse, click, commander) expect `--name value` and break under positional invocation.

## Goals

1. Add `path` and `choice` arg types end-to-end (model → form → run modal → argv).
2. Reject bad integer / required-empty input *before* the script runs, with a useful notify and focus retention on the bad field.
3. Per-script `arg_style` toggle for `positional` vs `flags` invocation.
4. AI generation knows about the new types and arg style so generated code matches the chosen invocation.
5. Pure-function argv-construction module (`argv.py`) testable without Textual.

## Non-Goals

- No file picker / `DirectoryTree` / Tab-completion for `path`. A plain `Input` plus a single dim hint is enough for v1.
- No per-arg flag-name override — flag is always `--<arg.name>` literal.
- No Click-style `--name`/`--no-name` boolean pairs — booleans omit on `False`.
- No backfilling existing scripts on disk. `Script.arg_style` defaults to `"positional"` via Pydantic, so loading old `meta.json` files is unchanged.
- No automated Textual screen / snapshot tests; logic is pulled into `argv.py` and unit-tested there.

## Architecture

One new module, two new model fields, four touched files.

### New: `src/scriptpilot/argv.py`

Pure functions; no Textual import.

```python
from __future__ import annotations
from pathlib import Path

from scriptpilot.models import Script, ScriptArg


class ArgValidationError(Exception):
    """Raised when a typed value fails validation."""

    def __init__(self, arg_name: str, message: str):
        super().__init__(message)
        self.arg_name = arg_name
        self.message = message


def validate_and_coerce(arg: ScriptArg, raw: str | bool) -> str | bool:
    """Validate one raw value against an arg definition.

    `raw` is whatever the form widget produced: `bool` from a Switch,
    `str` from an Input or Select. Returns the validated value, still
    as a str/bool (no path resolution or argv-style framing yet).
    Raises `ArgValidationError` on bad input.

    Required-empty: raises.
    Integer non-numeric: raises.
    Choice value not in `arg.choices`: raises.
    Optional-empty: returns "" (or False for boolean).
    """


def build_argv(script: Script, validated: list[str | bool]) -> list[str]:
    """Build the final argv list for a script run.

    - Resolves path-typed values against `script.cwd` (Path expansion + join).
    - Emits positional or flag-style based on `script.arg_style`.
    - Booleans in flags mode: emit `--<name>` if True, omit if False.
    - Empty optional values in flags mode: omit the flag entirely.
    - Empty optional values in positional mode: emit "" (current behavior;
      preserves positional indices for downstream scripts).
    Returns the final `list[str]` passed to subprocess.
    """
```

Splitting `validate_and_coerce` (per-field, fast-fail) from `build_argv` (whole-list, post-validation) lets `RunScreen` validate field-by-field for inline error UI, then construct argv once everything passes.

### Changes: `src/scriptpilot/models.py`

`ScriptArg` gains `path` / `choice` types, a `choices` field, and a model validator:

```python
class ScriptArg(BaseModel):
    name: str
    type: Literal["string", "boolean", "integer", "path", "choice"]
    required: bool = True
    default: str | bool | int | None = None
    choices: list[str] | None = None

    @model_validator(mode="after")
    def _validate_choices(self):
        if self.type == "choice":
            if not self.choices or any(not c.strip() for c in self.choices):
                raise ValueError("choice arg requires non-empty choices list")
            if self.default is not None and self.default not in self.choices:
                raise ValueError(f"default {self.default!r} not in choices")
        elif self.choices is not None:
            raise ValueError("choices is only valid when type='choice'")
        return self
```

`Script` gains `arg_style`:

```python
class Script(BaseModel):
    # ... existing fields ...
    arg_style: Literal["positional", "flags"] = "positional"
```

Backward compat: both `arg_style` and `choices` have safe defaults. Old `meta.json` files load unchanged.

### Changes: `src/scriptpilot/widgets/arg_editor.py`

`ARG_TYPES` extended:

```python
ARG_TYPES = [
    ("string", "string"),
    ("boolean", "boolean"),
    ("integer", "integer"),
    ("path", "path"),
    ("choice", "choice"),
]

ARG_STYLES = [("positional", "positional"), ("--flags", "flags")]
```

`ArgRow`: layout is changed from a single horizontal row to a vertical wrapper containing the existing horizontal row plus a sub-row that's only visible when `type == "choice"`. The widget's `DEFAULT_CSS` drops `layout: horizontal` from `ArgRow` itself (default is vertical) and adds:

```
ArgRow {
    height: auto;
    margin-bottom: 1;
}
ArgRow .arg-main {
    height: 3;
}
ArgRow .arg-choices-hidden {
    display: none;
}
ArgRow #arg-choices {
    margin-top: 0;
    margin-bottom: 0;
}
```

```python
def compose(self) -> ComposeResult:
    with Vertical():
        with Horizontal(classes="arg-main"):
            yield Input(..., id="arg-name")
            yield Select(ARG_TYPES, ..., id="arg-type")
            yield Label("Req:")
            yield Switch(..., id="arg-required")
            yield Input(..., id="arg-default")
            yield Button("X", variant="error", id="arg-remove")
        yield Input(
            value=",".join(self._arg.choices) if self._arg and self._arg.choices else "",
            placeholder="comma-separated choices, e.g. dev,staging,prod",
            id="arg-choices",
            classes="arg-choices-hidden",
        )
```

`#arg-choices` defaults to `display: none` via the `arg-choices-hidden` class. An `on_select_changed` handler on `ArgRow` toggles the class when the type changes:

```python
def on_select_changed(self, event: Select.Changed):
    if event.select.id != "arg-type":
        return
    choices_input = self.query_one("#arg-choices", Input)
    if event.value == "choice":
        choices_input.remove_class("arg-choices-hidden")
    else:
        choices_input.add_class("arg-choices-hidden")
```

`to_script_arg()` reads choices only when `type == "choice"`:

```python
choices = None
if arg_type == "choice":
    raw = self.query_one("#arg-choices", Input).value
    choices = [c.strip() for c in raw.split(",") if c.strip()] or None

return ScriptArg(
    name=name,
    type=arg_type,
    required=required,
    default=default,
    choices=choices,
)
```

`ScriptArg(...)` may now raise `ValidationError` (e.g., `type="choice"` with no choices). `ArgEditor.get_args()` no longer swallows that — it propagates and the calling screen catches.

`ArgEditor` gains a header `Select` for `arg_style`, placed next to the `[bold]Arguments[/bold]` label:

```python
def compose(self) -> ComposeResult:
    with Horizontal(classes="arg-editor-header"):
        yield Label("[bold]Arguments[/bold]")
        yield Select(
            ARG_STYLES,
            value=self._initial_arg_style,
            allow_blank=False,
            id="arg-style-select",
        )
    with Vertical(id="arg-list"):
        for arg in self._initial_args:
            yield ArgRow(arg)
    yield Button("+ Add Argument", id="add-arg-btn", variant="primary")
```

New constructor parameter and accessor:

```python
def __init__(self, args=None, arg_style: str = "positional"):
    super().__init__()
    self._initial_args = args or []
    self._initial_arg_style = arg_style

def get_arg_style(self) -> str:
    return self.query_one("#arg-style-select", Select).value
```

### Changes: `src/scriptpilot/screens/edit.py`

Pass `arg_style` into `ArgEditor` and read it back on save:

```python
yield ArgEditor(s.args if s else [], arg_style=s.arg_style if s else "positional")

# in _collect_form, when constructing/updating Script:
arg_style = self.query_one(ArgEditor).get_arg_style()
```

`_collect_form` wraps `get_args()` in `try/except ValidationError`, mirroring the existing pattern for empty-name validation:

```python
try:
    args = self.query_one(ArgEditor).get_args()
except ValidationError as e:
    self.notify(str(e), severity="error")
    return None
```

### Changes: `src/scriptpilot/screens/run.py`

`compose` updated for the new types:

- `boolean` → `Switch` (unchanged).
- `integer` / `string` → `Input` (unchanged).
- `path` → `Input(placeholder="path", id=f"arg-{i}")`. A single `[dim]Label("relative paths resolve against cwd")[/dim]` is shown once at the top of the modal (only when at least one arg is `path`-typed).
- `choice` → `Select(options=[(c, c) for c in arg.choices], allow_blank=not arg.required, value=<initial>, id=f"arg-{i}")`. `<initial>` is computed: `arg.default` if it's set, else `arg.choices[0]` if required, else `Select.BLANK`. (Pydantic guarantees `arg.default in arg.choices` when set, so no further check needed at the call site.)

`_collect_and_run` reworked to use `argv.py`:

```python
def _collect_and_run(self):
    raw_values = []
    for i, arg in enumerate(self._script.args):
        widget_id = f"arg-{i}"
        if arg.type == "boolean":
            raw_values.append(self.query_one(f"#{widget_id}", Switch).value)
        elif arg.type == "choice":
            v = self.query_one(f"#{widget_id}", Select).value
            raw_values.append("" if v is Select.BLANK else v)
        else:
            raw_values.append(self.query_one(f"#{widget_id}", Input).value.strip())

    validated = []
    for i, (arg, raw) in enumerate(zip(self._script.args, raw_values)):
        try:
            validated.append(validate_and_coerce(arg, raw))
        except ArgValidationError as e:
            self.notify(e.message, severity="error")
            self.query_one(f"#arg-{i}").focus()
            return

    argv = build_argv(self._script, validated)
    self.dismiss(argv)
```

`RunScreen.dismiss` return type stays `list[str] | None`. Callers (`MainScreen._execute`, `EditScreen._scratch_execute`) need no change because they pass argv straight through to `execute_script(arg_values=...)`.

### Changes: `src/scriptpilot/openrouter.py`

`GENERATE_SYSTEM_PROMPT` JSON schema description updated to include the new types, `choices`, and `arg_style`:

```
The JSON block must have this exact format:
```json
{"args": [
  {"name": "arg_name",
   "type": "string|integer|boolean|path|choice",
   "required": true|false,
   "default": "value",
   "choices": ["a", "b"]}
], "arg_style": "positional|flags"}
```

Use an empty args array if the script takes no arguments.
- `choices` is required iff `type == "choice"` and must be a non-empty list of strings; omit otherwise.
- `path` args receive an absolute path (relatives are resolved by ScriptPilot against the script's cwd); your script can treat them as ready-to-use file paths.
- When `arg_style` is `flags`, your script MUST parse arguments as `--name value` (and `--name` for booleans). When `arg_style` is `positional`, parse as `$1 $2 ...`. Pick whichever style is idiomatic for the language and the script's purpose.
```

Identical addition to `MODIFY_SYSTEM_PROMPT`.

`GenerationResult` gains `arg_style`:

```python
@dataclass
class GenerationResult:
    code: str
    args: list[ScriptArg]
    arg_style: str = "positional"
```

`parse_generation_response` reads `arg_style` from the JSON block, defaulting to `"positional"` if absent (back-compat with older LLM responses pre-deployment).

Callers of `generate_script` / `modify_script` (`screens/generate.py`, any modify flow) set `script.arg_style = result.arg_style` along with `script.args = result.args`.

## Data Flow

### Flow A — RunScreen for a script with mixed arg types

```
User opens RunScreen for `deploy` (env: choice, region: choice, dry_run: bool, version: integer)
  → compose: Select for env, Select for region, Switch for dry_run, Input for version
  → user picks env=staging, region=eu, dry_run=on, version=42
  → user clicks Run
  → _collect_and_run:
       raw_values = ["staging", "eu", True, "42"]
       for each: validate_and_coerce
         - choice "staging" in ["dev","staging","prod"] → "staging"
         - choice "eu" in [...] → "eu"
         - bool True → True
         - integer "42" → "42" (int() OK)
       argv = build_argv(script, validated)
         positional: ["staging", "eu", "true", "42"]
         flags:      ["--env", "staging", "--region", "eu", "--dry_run", "--version", "42"]
       dismiss(argv)
  → caller passes to execute_script(arg_values=argv)
```

### Flow B — Path arg with relative input

```
script.cwd = "~/projects/data"
RunScreen renders: Input for `manifest`
  + once-only hint label "[dim]relative paths resolve against cwd[/dim]"
user types "configs/prod.yaml"
  → validate_and_coerce: required check, return "configs/prod.yaml" as-is
  → build_argv:
       expanded = Path("~/projects/data").expanduser() / "configs/prod.yaml"
       → "/home/<user>/projects/data/configs/prod.yaml"
  → dismiss(["/home/.../configs/prod.yaml"])
```

If `script.cwd` is None or empty/whitespace, falls back to `Path.home()` — matches `executor._resolve_cwd` semantics.

### Flow C — Integer rejection

```
user types "abc" in version Input, clicks Run
  → validate_and_coerce(arg=version, raw="abc")
       int("abc") → ValueError
       raise ArgValidationError("version", "'version' must be an integer")
  → RunScreen: notify(message, severity="error")
              query_one("#arg-3").focus()
              return  (no dismiss)
```

### Flow D — LLM generates a flag-style script

```
user prompts: "deploy script with env (dev|staging|prod), dry-run, region"
LLM returns:
  ```bash
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --env) ENV="$2"; shift 2;;
      --region) REGION="$2"; shift 2;;
      --dry-run) DRY_RUN=1; shift;;
      *) shift;;
    esac
  done
  ...
  ```
  ```json
  {"args": [
    {"name": "env", "type": "choice", "choices": ["dev","staging","prod"], "required": true},
    {"name": "region", "type": "string", "required": true},
    {"name": "dry-run", "type": "boolean", "required": false, "default": false}
  ], "arg_style": "flags"}
  ```
  → parse_generation_response constructs GenerationResult
  → GenerateScreen sets script.args = result.args; script.arg_style = result.arg_style
  → next run: build_argv emits --env staging --region eu --dry-run
```

## Error Handling

| Surface | Failure | Behavior |
|---|---|---|
| `ScriptArg(type="choice", choices=None)` | model_validator | `pydantic.ValidationError` — propagates from `Script(**meta_json)`, `ArgRow.to_script_arg()`, `parse_generation_response` |
| `ScriptArg(type="string", choices=[...])` | model_validator | `pydantic.ValidationError` |
| `ScriptArg(type="choice", default="x", choices=["a","b"])` | model_validator | `pydantic.ValidationError` |
| `validate_and_coerce` integer / non-numeric | `ArgValidationError("'<name>' must be an integer")` | RunScreen notifies + focuses bad field |
| `validate_and_coerce` required / empty | `ArgValidationError("'<name>' is required")` | RunScreen notifies + focuses bad field |
| `validate_and_coerce` choice / value not in choices | `ArgValidationError("'<name>' must be one of: <list>")` | RunScreen notifies + focuses (defensive — Select shouldn't allow it, but a stale `default` from the LLM might) |
| `build_argv` path / `script.cwd` None or empty | resolve against `Path.home()` (matches executor's `_resolve_cwd`) | absolute path emitted |
| `build_argv` path / `~` typed by user | `Path("...").expanduser()` before joining | absolute path emitted |
| `parse_generation_response` `arg_style` invalid value | Pydantic `ValidationError` → wrapped to `MalformedResponseError` | retry-on-malformed loop catches it (existing behavior) |
| `parse_generation_response` `arg_style` missing | default to `"positional"` | no error |
| `ArgEditor.get_args()` user picks `choice` then leaves choices empty + clicks Save | `ScriptArg` validator raises `ValidationError`; `EditScreen._collect_form` catches and notifies | form stays open, user fixes |

## Testing

### `tests/test_argv.py` (new)

Pure functions, no Textual import.

- `validate_and_coerce` happy paths for every type (string, boolean, integer, path, choice).
- `validate_and_coerce` integer rejects `"abc"`, `"3.14"`; accepts `"-5"`, `"0"`.
- `validate_and_coerce` required + empty → raises with arg name in message.
- `validate_and_coerce` optional + empty → returns `""` (or `False` for boolean).
- `validate_and_coerce` choice value not in choices → raises.
- `build_argv` positional emission for every type.
- `build_argv` flags emission: boolean True / False, optional empty omitted, required value included as `--name value`.
- `build_argv` path resolution: relative + cwd → absolute; absolute pass-through; cwd None / empty / whitespace → `~` expansion.
- `build_argv` path with `~` typed by user → expanded.
- `build_argv` mixed-type script in `flags` mode end-to-end.

### `tests/test_models.py` (extend)

- `ScriptArg(type="choice", choices=["a","b"])` OK.
- `ScriptArg(type="choice")` → `ValidationError`.
- `ScriptArg(type="choice", choices=[])` → `ValidationError`.
- `ScriptArg(type="choice", choices=["a","   "])` → `ValidationError` (empty after strip).
- `ScriptArg(type="string", choices=["a"])` → `ValidationError`.
- `ScriptArg(type="choice", choices=["a","b"], default="z")` → `ValidationError`.
- `ScriptArg(type="path")` accepted; default may be `"~/foo"` string.
- `Script(...)` defaults `arg_style="positional"`.
- `Script(arg_style="flags")` round-trips through `model_dump`.
- Backward-compat dict missing `arg_style` and `choices` loads with defaults.

### `tests/test_openrouter.py` (extend)

- `parse_generation_response` reads `arg_style` from JSON when present.
- `parse_generation_response` defaults `arg_style="positional"` when JSON omits it.
- `parse_generation_response` with `type="choice"` and `choices=["a","b"]` → `ScriptArg.choices == ["a","b"]`.
- `parse_generation_response` with `type="path"` → `ScriptArg(type="path")` constructed.
- `parse_generation_response` with `type="choice"` and missing `choices` → `MalformedResponseError`.
- `parse_generation_response` with invalid `arg_style="oops"` → `MalformedResponseError`.

### Manual acceptance walkthrough

Documented here; not automated.

1. Create a script with `choice` arg `env: [dev, staging, prod]`. RunScreen shows a dropdown; running it passes the chosen value. No `Input` widget for that field on screen.
2. Create a script with `path` arg, set `cwd = ~/repos/foo`, type `bar.txt` in RunScreen → script receives `/home/<user>/repos/foo/bar.txt` as argv.
3. Create a script with an `integer` arg, type `abc` in RunScreen → notify shows `'<name>' must be an integer`, focus stays on the field, script does not run.
4. Generate a script via AI ("deploy with env=dev|staging|prod, dry-run, region") → response declares `choice` + `arg_style="flags"`; generated bash uses `case` / `getopts`; running it passes `--env staging --region eu --dry-run`.
5. Edit an existing positional script → toggle `arg_style` to `--flags` in EditScreen → save → next run invokes with `--name value`.
6. Open Settings — no change there (this task touches no Settings UI).

## Acceptance Criteria

- `ScriptArg.type` includes `path` and `choice`; Pydantic rejects malformed `choice` configs (missing/empty `choices`, default-not-in-choices, `choices` set on non-choice types).
- `Script.arg_style` defaults `"positional"`; existing scripts on disk load unchanged.
- `RunScreen` rejects bad integers and required-empty fields with a notify and focus retention before dismissing.
- `RunScreen` renders a `Select` for `choice` args.
- `RunScreen` resolves path-arg relative paths against `script.cwd` (or `~` if unset) before passing to argv.
- `flags` `arg_style` produces `--name value` argv (booleans omitted on `False`, `--name` on `True`).
- `argv.py` is independently unit-tested with no Textual import.
- `GENERATE_SYSTEM_PROMPT` and `MODIFY_SYSTEM_PROMPT` document the new types and `arg_style`; `parse_generation_response` reads both with safe defaults.
