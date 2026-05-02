# ScriptPilot — Argument Types & Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `path` and `choice` argument types, real-time integer validation, and a per-script positional-vs-flags arg style toggle to ScriptPilot, with AI generation aware of the new schema.

**Architecture:** Two new fields on existing Pydantic models (`ScriptArg.choices`, `Script.arg_style`) with a model validator; one new pure-function module `src/scriptpilot/argv.py` for validation and argv construction; small surgical changes to the EditScreen, RunScreen, ArgEditor widget, and OpenRouter system prompts.

**Tech Stack:** Python 3.11+, Pydantic v2, Textual TUI, pytest + pytest-asyncio + respx.

**Spec:** `docs/superpowers/specs/2026-05-02-script-pilot-arg-types-design.md`

---

## File Map

**Created:**
- `src/scriptpilot/argv.py` — pure functions: `ArgValidationError`, `validate_and_coerce(arg, raw)`, `build_argv(script, validated)`. No Textual import.
- `tests/test_argv.py` — unit tests for the above.

**Modified:**
- `src/scriptpilot/models.py` — extend `ScriptArg.type` literal, add `ScriptArg.choices` field + `model_validator`, add `Script.arg_style` field.
- `src/scriptpilot/openrouter.py` — extend `GENERATE_SYSTEM_PROMPT` and `MODIFY_SYSTEM_PROMPT`, add `arg_style` to `GenerationResult`, update `parse_generation_response`.
- `src/scriptpilot/widgets/arg_editor.py` — extend `ARG_TYPES`, add `ARG_STYLES`, add choices sub-row to `ArgRow`, add header `arg_style` Select on `ArgEditor`, propagate `ValidationError` from `get_args()`.
- `src/scriptpilot/screens/edit.py` — pass/read `arg_style`, catch `ValidationError` from `get_args()`.
- `src/scriptpilot/screens/run.py` — render Select for choice / Input for path with one-time hint, validate per-field via `argv.validate_and_coerce`, build argv via `argv.build_argv`, focus on bad field on validation failure.
- `src/scriptpilot/screens/generate.py` — wire `result.arg_style` into the new `Script`.
- `src/scriptpilot/screens/prompt.py` — wire `result.arg_style` into the updated `Script`.
- `tests/test_models.py` — extend with new validator + `arg_style` cases.
- `tests/test_openrouter.py` — extend with `arg_style` parsing + new types.

---

## Task 1: Extend `ScriptArg` with `path` / `choice` types and `choices` field

**Files:**
- Modify: `src/scriptpilot/models.py:9-15`
- Test: `tests/test_models.py` (extend)

- [ ] **Step 1: Write failing tests for new types and validator**

Append to `tests/test_models.py` (after the existing `TestScriptArg` class, in a new class):

```python
class TestScriptArgChoices:
    def test_choice_with_choices_ok(self):
        arg = ScriptArg(name="env", type="choice", choices=["dev", "staging", "prod"])
        assert arg.type == "choice"
        assert arg.choices == ["dev", "staging", "prod"]

    def test_choice_without_choices_rejected(self):
        with pytest.raises(Exception):
            ScriptArg(name="env", type="choice")

    def test_choice_empty_list_rejected(self):
        with pytest.raises(Exception):
            ScriptArg(name="env", type="choice", choices=[])

    def test_choice_blank_string_in_choices_rejected(self):
        with pytest.raises(Exception):
            ScriptArg(name="env", type="choice", choices=["dev", "   "])

    def test_choices_on_non_choice_rejected(self):
        with pytest.raises(Exception):
            ScriptArg(name="x", type="string", choices=["a"])

    def test_choice_default_in_choices_ok(self):
        arg = ScriptArg(
            name="env", type="choice",
            choices=["dev", "prod"], default="dev",
        )
        assert arg.default == "dev"

    def test_choice_default_not_in_choices_rejected(self):
        with pytest.raises(Exception):
            ScriptArg(
                name="env", type="choice",
                choices=["dev", "prod"], default="staging",
            )

    def test_path_type_ok(self):
        arg = ScriptArg(name="manifest", type="path")
        assert arg.type == "path"
        assert arg.choices is None

    def test_path_with_string_default_ok(self):
        arg = ScriptArg(name="manifest", type="path", default="~/foo.yaml")
        assert arg.default == "~/foo.yaml"

    def test_backward_compat_no_choices_field(self):
        """Existing meta files without `choices` load with default None."""
        data = {"name": "x", "type": "string", "required": True, "default": None}
        arg = ScriptArg(**data)
        assert arg.choices is None
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd /home/kc/repos/script-pilot && uv run pytest tests/test_models.py::TestScriptArgChoices -v`
Expected: FAIL on every test (`pydantic.ValidationError` for new types, AttributeError for `choices`).

- [ ] **Step 3: Update `ScriptArg` in `src/scriptpilot/models.py`**

Replace the existing `ScriptArg` class:

```python
class ScriptArg(BaseModel):
    """A single argument definition for a script."""

    name: str
    type: Literal["string", "boolean", "integer", "path", "choice"]
    required: bool = True
    default: str | bool | int | None = None
    choices: list[str] | None = None

    @model_validator(mode="after")
    def _validate_choices(self):
        if self.type == "choice":
            if not self.choices:
                raise ValueError("choice arg requires non-empty choices list")
            if any(not c.strip() for c in self.choices):
                raise ValueError("choices must not contain blank entries")
            if self.default is not None and self.default not in self.choices:
                raise ValueError(f"default {self.default!r} not in choices")
        elif self.choices is not None:
            raise ValueError("choices is only valid when type='choice'")
        return self
```

Add `model_validator` to the import line at the top of the file:

```python
from pydantic import BaseModel, model_validator
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS for `TestScriptArgChoices` tests; existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/models.py tests/test_models.py
git commit -m "feat: ScriptArg gains path/choice types and choices field"
```

---

## Task 2: Add `Script.arg_style` field

**Files:**
- Modify: `src/scriptpilot/models.py:18-34`
- Test: `tests/test_models.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_models.py`:

```python
class TestScriptArgStyle:
    def test_arg_style_default_positional(self):
        s = Script(name="x", description="x", type="bash", content="x")
        assert s.arg_style == "positional"

    def test_arg_style_flags(self):
        s = Script(
            name="x", description="x", type="bash", content="x",
            arg_style="flags",
        )
        assert s.arg_style == "flags"

    def test_arg_style_invalid_rejected(self):
        with pytest.raises(Exception):
            Script(
                name="x", description="x", type="bash", content="x",
                arg_style="kwargs",
            )

    def test_arg_style_roundtrip(self):
        s = Script(
            name="x", description="x", type="bash", content="x",
            arg_style="flags",
        )
        data = s.model_dump()
        s2 = Script(**data)
        assert s2.arg_style == "flags"

    def test_backward_compat_no_arg_style_field(self):
        """Existing meta files without `arg_style` load as positional."""
        data = {
            "name": "x", "description": "x", "type": "bash",
            "content": "x", "id": "abc",
        }
        s = Script(**data)
        assert s.arg_style == "positional"
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest tests/test_models.py::TestScriptArgStyle -v`
Expected: FAIL — `arg_style` field doesn't exist.

- [ ] **Step 3: Add `arg_style` to `Script`**

In `src/scriptpilot/models.py`, modify the `Script` class — add the `arg_style` field after `env`:

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

    def model_post_init(self, __context):
        if not self.id:
            self.id = str(uuid.uuid4())
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/models.py tests/test_models.py
git commit -m "feat: Script gains arg_style with positional default"
```

---

## Task 3: Create `argv.py` with `ArgValidationError` and `validate_and_coerce`

**Files:**
- Create: `src/scriptpilot/argv.py`
- Create: `tests/test_argv.py`

- [ ] **Step 1: Write failing tests for `validate_and_coerce`**

Create `tests/test_argv.py`:

```python
import pytest

from scriptpilot.argv import ArgValidationError, validate_and_coerce
from scriptpilot.models import ScriptArg


class TestValidateAndCoerceString:
    def test_required_value_ok(self):
        arg = ScriptArg(name="msg", type="string", required=True)
        assert validate_and_coerce(arg, "hello") == "hello"

    def test_required_empty_raises(self):
        arg = ScriptArg(name="msg", type="string", required=True)
        with pytest.raises(ArgValidationError) as ei:
            validate_and_coerce(arg, "")
        assert ei.value.arg_name == "msg"
        assert "required" in ei.value.message.lower()

    def test_optional_empty_returns_empty(self):
        arg = ScriptArg(name="msg", type="string", required=False)
        assert validate_and_coerce(arg, "") == ""


class TestValidateAndCoerceBoolean:
    def test_true(self):
        arg = ScriptArg(name="dry", type="boolean", required=False)
        assert validate_and_coerce(arg, True) is True

    def test_false(self):
        arg = ScriptArg(name="dry", type="boolean", required=False)
        assert validate_and_coerce(arg, False) is False


class TestValidateAndCoerceInteger:
    def test_valid_integer_string(self):
        arg = ScriptArg(name="n", type="integer", required=True)
        assert validate_and_coerce(arg, "42") == "42"

    def test_negative_integer(self):
        arg = ScriptArg(name="n", type="integer", required=True)
        assert validate_and_coerce(arg, "-5") == "-5"

    def test_zero(self):
        arg = ScriptArg(name="n", type="integer", required=False)
        assert validate_and_coerce(arg, "0") == "0"

    def test_non_numeric_raises(self):
        arg = ScriptArg(name="n", type="integer", required=True)
        with pytest.raises(ArgValidationError) as ei:
            validate_and_coerce(arg, "abc")
        assert ei.value.arg_name == "n"
        assert "integer" in ei.value.message.lower()

    def test_float_string_raises(self):
        arg = ScriptArg(name="n", type="integer", required=True)
        with pytest.raises(ArgValidationError):
            validate_and_coerce(arg, "3.14")

    def test_required_empty_raises(self):
        arg = ScriptArg(name="n", type="integer", required=True)
        with pytest.raises(ArgValidationError):
            validate_and_coerce(arg, "")

    def test_optional_empty_returns_empty(self):
        arg = ScriptArg(name="n", type="integer", required=False)
        assert validate_and_coerce(arg, "") == ""


class TestValidateAndCoercePath:
    def test_required_value_ok(self):
        arg = ScriptArg(name="p", type="path", required=True)
        assert validate_and_coerce(arg, "foo.txt") == "foo.txt"

    def test_required_empty_raises(self):
        arg = ScriptArg(name="p", type="path", required=True)
        with pytest.raises(ArgValidationError):
            validate_and_coerce(arg, "")

    def test_optional_empty_returns_empty(self):
        arg = ScriptArg(name="p", type="path", required=False)
        assert validate_and_coerce(arg, "") == ""


class TestValidateAndCoerceChoice:
    def test_valid_choice(self):
        arg = ScriptArg(name="env", type="choice", choices=["dev", "prod"])
        assert validate_and_coerce(arg, "dev") == "dev"

    def test_choice_not_in_list_raises(self):
        arg = ScriptArg(name="env", type="choice", choices=["dev", "prod"])
        with pytest.raises(ArgValidationError) as ei:
            validate_and_coerce(arg, "staging")
        assert ei.value.arg_name == "env"
        assert "one of" in ei.value.message.lower()

    def test_required_empty_raises(self):
        arg = ScriptArg(name="env", type="choice",
                        choices=["dev", "prod"], required=True)
        with pytest.raises(ArgValidationError):
            validate_and_coerce(arg, "")

    def test_optional_empty_returns_empty(self):
        arg = ScriptArg(name="env", type="choice",
                        choices=["dev", "prod"], required=False)
        assert validate_and_coerce(arg, "") == ""
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest tests/test_argv.py -v`
Expected: FAIL — `scriptpilot.argv` module does not exist.

- [ ] **Step 3: Create `src/scriptpilot/argv.py`**

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
    `str` from an Input or Select. Returns the validated value, still as
    a str/bool (no path resolution or argv-style framing yet). Raises
    `ArgValidationError` on bad input.
    """
    if arg.type == "boolean":
        return bool(raw)

    text = raw if isinstance(raw, str) else str(raw)

    if not text:
        if arg.required:
            raise ArgValidationError(
                arg.name, f"'{arg.name}' is required"
            )
        return ""

    if arg.type == "integer":
        try:
            int(text)
        except ValueError:
            raise ArgValidationError(
                arg.name, f"'{arg.name}' must be an integer"
            ) from None
        return text

    if arg.type == "choice":
        if arg.choices is None or text not in arg.choices:
            allowed = ", ".join(arg.choices or [])
            raise ArgValidationError(
                arg.name, f"'{arg.name}' must be one of: {allowed}"
            )
        return text

    # string and path: any non-empty value passes; path resolution
    # happens later in build_argv.
    return text
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_argv.py -v`
Expected: PASS for all `validate_and_coerce` tests.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/argv.py tests/test_argv.py
git commit -m "feat: argv module with validate_and_coerce"
```

---

## Task 4: Add `build_argv` to `argv.py`

**Files:**
- Modify: `src/scriptpilot/argv.py`
- Modify: `tests/test_argv.py`

- [ ] **Step 1: Write failing tests for `build_argv`**

Append to `tests/test_argv.py`:

```python
from pathlib import Path

from scriptpilot.argv import build_argv
from scriptpilot.models import Script


def _make_script(args, arg_style="positional", cwd=None):
    return Script(
        name="x", description="x", type="bash", content="x",
        args=args, arg_style=arg_style, cwd=cwd,
    )


class TestBuildArgvPositional:
    def test_string(self):
        s = _make_script([ScriptArg(name="msg", type="string")])
        assert build_argv(s, ["hello"]) == ["hello"]

    def test_integer(self):
        s = _make_script([ScriptArg(name="n", type="integer")])
        assert build_argv(s, ["42"]) == ["42"]

    def test_boolean_true(self):
        s = _make_script([ScriptArg(name="dry", type="boolean")])
        assert build_argv(s, [True]) == ["true"]

    def test_boolean_false(self):
        s = _make_script([ScriptArg(name="dry", type="boolean")])
        assert build_argv(s, [False]) == ["false"]

    def test_optional_string_empty_emits_empty_string(self):
        s = _make_script([ScriptArg(name="msg", type="string", required=False)])
        assert build_argv(s, [""]) == [""]

    def test_choice(self):
        s = _make_script([ScriptArg(name="env", type="choice",
                                    choices=["dev", "prod"])])
        assert build_argv(s, ["dev"]) == ["dev"]

    def test_mixed(self):
        s = _make_script([
            ScriptArg(name="env", type="choice", choices=["dev", "prod"]),
            ScriptArg(name="dry", type="boolean"),
            ScriptArg(name="n", type="integer"),
        ])
        assert build_argv(s, ["dev", True, "42"]) == ["dev", "true", "42"]


class TestBuildArgvFlags:
    def test_string_required(self):
        s = _make_script(
            [ScriptArg(name="msg", type="string")],
            arg_style="flags",
        )
        assert build_argv(s, ["hello"]) == ["--msg", "hello"]

    def test_integer(self):
        s = _make_script(
            [ScriptArg(name="n", type="integer")],
            arg_style="flags",
        )
        assert build_argv(s, ["42"]) == ["--n", "42"]

    def test_boolean_true_emits_flag(self):
        s = _make_script(
            [ScriptArg(name="dry-run", type="boolean")],
            arg_style="flags",
        )
        assert build_argv(s, [True]) == ["--dry-run"]

    def test_boolean_false_omits(self):
        s = _make_script(
            [ScriptArg(name="dry-run", type="boolean")],
            arg_style="flags",
        )
        assert build_argv(s, [False]) == []

    def test_optional_empty_omits_flag(self):
        s = _make_script(
            [ScriptArg(name="msg", type="string", required=False)],
            arg_style="flags",
        )
        assert build_argv(s, [""]) == []

    def test_choice(self):
        s = _make_script(
            [ScriptArg(name="env", type="choice", choices=["dev", "prod"])],
            arg_style="flags",
        )
        assert build_argv(s, ["dev"]) == ["--env", "dev"]

    def test_mixed(self):
        s = _make_script([
            ScriptArg(name="env", type="choice", choices=["dev", "prod"]),
            ScriptArg(name="region", type="string"),
            ScriptArg(name="dry-run", type="boolean", required=False, default=False),
        ], arg_style="flags")
        assert build_argv(s, ["dev", "eu", True]) == [
            "--env", "dev", "--region", "eu", "--dry-run",
        ]


class TestBuildArgvPath:
    def test_relative_resolved_against_cwd(self, tmp_path):
        s = _make_script(
            [ScriptArg(name="p", type="path")],
            cwd=str(tmp_path),
        )
        argv = build_argv(s, ["sub/file.txt"])
        assert argv == [str(tmp_path / "sub/file.txt")]

    def test_absolute_passes_through(self):
        s = _make_script([ScriptArg(name="p", type="path")])
        argv = build_argv(s, ["/etc/hosts"])
        assert argv == ["/etc/hosts"]

    def test_tilde_expanded(self):
        s = _make_script([ScriptArg(name="p", type="path")])
        argv = build_argv(s, ["~/foo.txt"])
        assert argv == [str(Path.home() / "foo.txt")]

    def test_cwd_none_falls_back_to_home(self):
        s = _make_script(
            [ScriptArg(name="p", type="path")],
            cwd=None,
        )
        argv = build_argv(s, ["foo.txt"])
        assert argv == [str(Path.home() / "foo.txt")]

    def test_cwd_empty_falls_back_to_home(self):
        s = _make_script(
            [ScriptArg(name="p", type="path")],
            cwd="",
        )
        argv = build_argv(s, ["foo.txt"])
        assert argv == [str(Path.home() / "foo.txt")]

    def test_cwd_whitespace_falls_back_to_home(self):
        s = _make_script(
            [ScriptArg(name="p", type="path")],
            cwd="   ",
        )
        argv = build_argv(s, ["foo.txt"])
        assert argv == [str(Path.home() / "foo.txt")]

    def test_cwd_with_tilde_expanded(self):
        s = _make_script(
            [ScriptArg(name="p", type="path")],
            cwd="~",
        )
        argv = build_argv(s, ["foo.txt"])
        assert argv == [str(Path.home() / "foo.txt")]

    def test_optional_empty_path_positional_emits_empty(self):
        s = _make_script(
            [ScriptArg(name="p", type="path", required=False)],
        )
        assert build_argv(s, [""]) == [""]

    def test_optional_empty_path_flags_omits(self):
        s = _make_script(
            [ScriptArg(name="p", type="path", required=False)],
            arg_style="flags",
        )
        assert build_argv(s, [""]) == []

    def test_path_in_flags_mode(self, tmp_path):
        s = _make_script(
            [ScriptArg(name="manifest", type="path")],
            arg_style="flags",
            cwd=str(tmp_path),
        )
        argv = build_argv(s, ["a.yaml"])
        assert argv == ["--manifest", str(tmp_path / "a.yaml")]
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest tests/test_argv.py -v`
Expected: FAIL — `build_argv` does not exist yet.

- [ ] **Step 3: Implement `build_argv`**

Append to `src/scriptpilot/argv.py`:

```python
def _resolve_cwd(script_cwd: str | None) -> Path:
    """Mirror executor._resolve_cwd: None/empty/whitespace → home; else expanduser.

    Unlike the executor we do NOT verify the directory exists — that's the
    executor's job at run time. We only need a base Path for joining.
    """
    if not script_cwd or not script_cwd.strip():
        return Path.home()
    return Path(script_cwd).expanduser()


def _resolve_path_value(raw: str, script_cwd: str | None) -> str:
    """Resolve a typed path: expand ~, then join against the script cwd if relative."""
    p = Path(raw).expanduser()
    if p.is_absolute():
        return str(p)
    return str(_resolve_cwd(script_cwd) / p)


def build_argv(script: Script, validated: list[str | bool]) -> list[str]:
    """Build the final argv list for a script run.

    See module docstring / spec for behavior summary.
    """
    argv: list[str] = []
    for arg, value in zip(script.args, validated):
        if arg.type == "boolean":
            if script.arg_style == "flags":
                if value:
                    argv.append(f"--{arg.name}")
                # False: omit
            else:
                argv.append("true" if value else "false")
            continue

        # value is a str at this point
        text = value if isinstance(value, str) else str(value)

        if arg.type == "path" and text:
            text = _resolve_path_value(text, script.cwd)

        if script.arg_style == "flags":
            if text == "":
                # optional empty: omit the flag
                continue
            argv.append(f"--{arg.name}")
            argv.append(text)
        else:
            argv.append(text)

    return argv
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_argv.py -v`
Expected: PASS for all tests in `tests/test_argv.py`.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/argv.py tests/test_argv.py
git commit -m "feat: argv.build_argv handles positional/flags + path resolution"
```

---

## Task 5: Update OpenRouter prompts and parser to support new types and `arg_style`

**Files:**
- Modify: `src/scriptpilot/openrouter.py:13-35,55-58,61-91`
- Test: `tests/test_openrouter.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_openrouter.py` (after the existing `TestParseGenerationResponse` class):

```python
class TestParseArgStyle:
    def test_arg_style_present(self):
        text = (
            '```bash\necho hi\n```\n\n'
            '```json\n{"args": [], "arg_style": "flags"}\n```'
        )
        result = parse_generation_response(text)
        assert result.arg_style == "flags"

    def test_arg_style_missing_defaults_positional(self):
        text = (
            '```bash\necho hi\n```\n\n'
            '```json\n{"args": []}\n```'
        )
        result = parse_generation_response(text)
        assert result.arg_style == "positional"

    def test_arg_style_invalid_raises(self):
        text = (
            '```bash\necho hi\n```\n\n'
            '```json\n{"args": [], "arg_style": "kwargs"}\n```'
        )
        with pytest.raises(MalformedResponseError):
            parse_generation_response(text)


class TestParseChoiceArg:
    def test_choice_with_choices(self):
        text = (
            '```bash\necho $1\n```\n\n'
            '```json\n{"args": ['
            '{"name": "env", "type": "choice", "required": true, '
            '"choices": ["dev", "prod"]}'
            ']}\n```'
        )
        result = parse_generation_response(text)
        assert result.args[0].type == "choice"
        assert result.args[0].choices == ["dev", "prod"]

    def test_choice_missing_choices_raises(self):
        text = (
            '```bash\necho $1\n```\n\n'
            '```json\n{"args": ['
            '{"name": "env", "type": "choice", "required": true}'
            ']}\n```'
        )
        with pytest.raises(MalformedResponseError):
            parse_generation_response(text)

    def test_path_arg(self):
        text = (
            '```bash\ncat $1\n```\n\n'
            '```json\n{"args": ['
            '{"name": "p", "type": "path", "required": true}'
            ']}\n```'
        )
        result = parse_generation_response(text)
        assert result.args[0].type == "path"
        assert result.args[0].choices is None
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest tests/test_openrouter.py::TestParseArgStyle tests/test_openrouter.py::TestParseChoiceArg -v`
Expected: FAIL — `arg_style` attribute does not exist on `GenerationResult`; choice/path types not yet handled.

- [ ] **Step 3: Update `GENERATE_SYSTEM_PROMPT` and `MODIFY_SYSTEM_PROMPT`**

Replace the two prompt constants in `src/scriptpilot/openrouter.py:13-35` with:

```python
GENERATE_SYSTEM_PROMPT = (
    "You are a script generator. You MUST output exactly two fenced blocks:\n\n"
    "1. A code block with the script (use ```bash, ```python, or ```javascript as the fence label)\n"
    "2. A JSON block with argument definitions and arg_style\n\n"
    "The code must be complete, valid, and ready to run. Include brief comments where helpful.\n\n"
    "The JSON block must have this exact format:\n"
    "```json\n"
    '{"args": [{"name": "arg_name", '
    '"type": "string|integer|boolean|path|choice", '
    '"required": true|false, "default": "value", '
    '"choices": ["a", "b"]}], '
    '"arg_style": "positional|flags"}\n'
    "```\n\n"
    "Rules:\n"
    "- Use an empty args array if the script takes no arguments.\n"
    "- `choices` is required iff `type == \"choice\"` and must be a non-empty list of strings; omit otherwise.\n"
    "- `path` args receive an absolute path (relatives are resolved by ScriptPilot against the script's cwd); your script can treat them as ready-to-use file paths.\n"
    "- When `arg_style` is `flags`, your script MUST parse arguments as `--name value` (and `--name` for booleans). When `arg_style` is `positional`, parse as `$1 $2 ...`. Pick whichever style is idiomatic for the language and the script's purpose.\n"
    "Do NOT include any text outside these two blocks."
)


MODIFY_SYSTEM_PROMPT = (
    "You are a script modifier. You will receive an existing script and an instruction "
    "describing what to change. Output the COMPLETE updated script (not a diff). "
    "You MUST output exactly two fenced blocks:\n\n"
    "1. A code block with the full updated script (use ```bash, ```python, or ```javascript)\n"
    "2. A JSON block with argument definitions and arg_style for the updated script\n\n"
    "The JSON block must have this exact format:\n"
    "```json\n"
    '{"args": [{"name": "arg_name", '
    '"type": "string|integer|boolean|path|choice", '
    '"required": true|false, "default": "value", '
    '"choices": ["a", "b"]}], '
    '"arg_style": "positional|flags"}\n'
    "```\n\n"
    "Rules:\n"
    "- Use an empty args array if the script takes no arguments.\n"
    "- `choices` is required iff `type == \"choice\"` and must be a non-empty list of strings; omit otherwise.\n"
    "- `path` args receive an absolute path (relatives are resolved by ScriptPilot against the script's cwd); your script can treat them as ready-to-use file paths.\n"
    "- When `arg_style` is `flags`, your script MUST parse arguments as `--name value` (and `--name` for booleans). When `arg_style` is `positional`, parse as `$1 $2 ...`. Pick whichever style is idiomatic for the language and the script's purpose.\n"
    "Do NOT include any text outside these two blocks."
)
```

- [ ] **Step 4: Add `arg_style` to `GenerationResult`**

Replace `src/scriptpilot/openrouter.py:54-58`:

```python
@dataclass
class GenerationResult:
    """Parsed LLM response containing code, argument definitions, and arg_style."""
    code: str
    args: list[ScriptArg]
    arg_style: str = "positional"
```

- [ ] **Step 5: Update `parse_generation_response` to read `arg_style`**

Replace the body of `parse_generation_response` (`src/scriptpilot/openrouter.py:61-91`):

```python
def parse_generation_response(text: str) -> GenerationResult:
    """Parse an LLM response into code, argument definitions, and arg_style."""
    blocks = re.findall(r"```(\w*)\n(.*?)```", text, re.DOTALL)
    if not blocks:
        raise MalformedResponseError("No fenced code blocks found")

    code = None
    parsed = None

    for lang, content in blocks:
        if lang == "json":
            try:
                obj = _json.loads(content.strip())
                if isinstance(obj, dict) and "args" in obj:
                    parsed = obj
            except _json.JSONDecodeError:
                raise MalformedResponseError("Invalid JSON in args block")
        elif code is None:
            code = content.strip()

    if code is None:
        raise MalformedResponseError("No code block found")
    if parsed is None:
        raise MalformedResponseError("No JSON block with 'args' key found")

    try:
        args = [ScriptArg(**a) for a in parsed["args"]]
    except Exception as e:
        raise MalformedResponseError(f"Invalid arg definition: {e}") from e

    arg_style = parsed.get("arg_style", "positional")
    if arg_style not in ("positional", "flags"):
        raise MalformedResponseError(
            f"Invalid arg_style {arg_style!r} (must be 'positional' or 'flags')"
        )

    return GenerationResult(code=code, args=args, arg_style=arg_style)
```

- [ ] **Step 6: Run tests, verify they pass**

Run: `uv run pytest tests/test_openrouter.py -v`
Expected: PASS for all tests, including `TestParseArgStyle`, `TestParseChoiceArg`, AND existing tests (the existing `TestParseGenerationResponse` cases all use `arg_style`-less JSON, which now defaults to `"positional"`).

- [ ] **Step 7: Commit**

```bash
git add src/scriptpilot/openrouter.py tests/test_openrouter.py
git commit -m "feat: openrouter prompts + parser handle path/choice/arg_style"
```

---

## Task 6: Extend `ArgEditor` widget for new types, choices sub-row, and `arg_style` header

**Files:**
- Modify: `src/scriptpilot/widgets/arg_editor.py`

This task has no automated tests — it's pure UI composition. Verification is via the existing test suite continuing to pass and via the manual walkthrough at the end of the plan.

- [ ] **Step 1: Replace `ARG_TYPES` and add `ARG_STYLES`**

In `src/scriptpilot/widgets/arg_editor.py`, replace line 10:

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

- [ ] **Step 2: Update `ArgRow` — drop horizontal layout, add choices sub-row**

Replace the `DEFAULT_CSS` block on `ArgRow` (currently `src/scriptpilot/widgets/arg_editor.py:16-37`):

```python
    DEFAULT_CSS = """
    ArgRow {
        height: auto;
        margin-bottom: 1;
    }
    ArgRow .arg-main {
        height: 3;
    }
    ArgRow .arg-main Input {
        width: 1fr;
        margin-right: 1;
    }
    ArgRow .arg-main Select {
        width: 16;
        margin-right: 1;
    }
    ArgRow .arg-main Switch {
        width: 12;
        margin-right: 1;
    }
    ArgRow .arg-main Button {
        width: 8;
    }
    ArgRow .arg-choices-hidden {
        display: none;
    }
    ArgRow #arg-choices {
        margin-top: 0;
        margin-bottom: 0;
    }
    """
```

Replace `ArgRow.compose` (`src/scriptpilot/widgets/arg_editor.py:43-61`):

```python
    def compose(self) -> ComposeResult:
        with Horizontal(classes="arg-main"):
            yield Input(
                value=self._arg.name if self._arg else "",
                placeholder="Name",
                id="arg-name",
            )
            yield Select(
                ARG_TYPES,
                value=self._arg.type if self._arg else "string",
                id="arg-type",
            )
            yield Label("Req:")
            yield Switch(value=self._arg.required if self._arg else True, id="arg-required")
            yield Input(
                value=str(self._arg.default) if self._arg and self._arg.default is not None else "",
                placeholder="Default",
                id="arg-default",
            )
            yield Button("X", variant="error", id="arg-remove")
        choices_classes = "arg-choices-hidden"
        if self._arg and self._arg.type == "choice":
            choices_classes = ""
        yield Input(
            value=",".join(self._arg.choices) if self._arg and self._arg.choices else "",
            placeholder="comma-separated choices, e.g. dev,staging,prod",
            id="arg-choices",
            classes=choices_classes,
        )
```

- [ ] **Step 3: Add `ArgRow.on_select_changed` to toggle the choices sub-row visibility**

Add a method to `ArgRow` (after `compose`, before `to_script_arg`):

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

- [ ] **Step 4: Update `ArgRow.to_script_arg` to read choices when applicable**

Replace `to_script_arg` (`src/scriptpilot/widgets/arg_editor.py:63-84`):

```python
    def to_script_arg(self) -> ScriptArg | None:
        """Convert this row to a ScriptArg, or None if name is empty.

        May raise pydantic.ValidationError when the user produces an
        inconsistent combination (e.g. choice type with empty choices).
        """
        name = self.query_one("#arg-name", Input).value.strip()
        if not name:
            return None
        arg_type = self.query_one("#arg-type", Select).value
        required = self.query_one("#arg-required", Switch).value
        default_str = self.query_one("#arg-default", Input).value.strip()

        default = None
        if default_str:
            if arg_type == "boolean":
                default = default_str.lower() in ("true", "1", "yes")
            elif arg_type == "integer":
                try:
                    default = int(default_str)
                except ValueError:
                    default = None
            else:
                default = default_str

        choices = None
        if arg_type == "choice":
            raw = self.query_one("#arg-choices", Input).value
            choices = [c.strip() for c in raw.split(",") if c.strip()] or None

        return ScriptArg(
            name=name, type=arg_type, required=required,
            default=default, choices=choices,
        )
```

- [ ] **Step 5: Add `arg_style` Select to `ArgEditor` header and accessor**

Replace `ArgEditor.DEFAULT_CSS` (`src/scriptpilot/widgets/arg_editor.py:90-101`):

```python
    DEFAULT_CSS = """
    ArgEditor {
        height: auto;
        padding: 1;
        border: solid $primary;
    }
    ArgEditor #arg-list {
        height: auto;
    }
    ArgEditor #add-arg-btn {
        margin-top: 1;
    }
    ArgEditor .arg-editor-header {
        height: 3;
    }
    ArgEditor #arg-style-select {
        width: 22;
        margin-left: 2;
    }
    """
```

Replace `ArgEditor.__init__` and `compose` (`src/scriptpilot/widgets/arg_editor.py:104-113`):

```python
    def __init__(self, args: list[ScriptArg] | None = None,
                 arg_style: str = "positional"):
        super().__init__()
        self._initial_args = args or []
        self._initial_arg_style = arg_style

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

Add a `get_arg_style` method (after `get_args`):

```python
    def get_arg_style(self) -> str:
        return self.query_one("#arg-style-select", Select).value
```

- [ ] **Step 6: Verify the existing test suite still passes**

Run: `uv run pytest tests/ -v`
Expected: PASS — all existing tests still pass; no new failures introduced by widget refactor.

- [ ] **Step 7: Commit**

```bash
git add src/scriptpilot/widgets/arg_editor.py
git commit -m "feat: ArgEditor supports path/choice types and arg_style"
```

---

## Task 7: Update `EditScreen` to wire `arg_style` and catch `ValidationError`

**Files:**
- Modify: `src/scriptpilot/screens/edit.py`

- [ ] **Step 1: Add ValidationError import**

At the top of `src/scriptpilot/screens/edit.py`, add the import:

```python
from pydantic import ValidationError
```

- [ ] **Step 2: Pass `arg_style` to `ArgEditor` in `compose`**

Replace `src/scriptpilot/screens/edit.py:127`:

```python
                yield ArgEditor(
                    s.args if s else [],
                    arg_style=s.arg_style if s else "positional",
                )
```

- [ ] **Step 3: Wrap `get_args` in try/except and read `arg_style` in `_collect_form`**

Replace the body of `_collect_form` (`src/scriptpilot/screens/edit.py:155-198`):

```python
    def _collect_form(self) -> Script | None:
        """Read the form into a Script. Returns None if validation fails (already notified)."""
        name = self.query_one("#name-input", Input).value.strip()
        desc = self.query_one("#desc-input", Input).value.strip()
        script_type = self.query_one("#type-select", Select).value
        content = self.query_one("#content-area", TextArea).text
        timeout_str = self.query_one("#timeout-input", Input).value.strip()
        cwd_str = self.query_one("#cwd-input", Input).value.strip() or None
        env = self.query_one(EnvEditor).get_env()
        arg_editor = self.query_one(ArgEditor)
        arg_style = arg_editor.get_arg_style()

        if not name:
            self.notify("Script name is required", severity="error")
            return None
        if not content.strip():
            self.notify("Script content is required", severity="error")
            return None

        try:
            args = arg_editor.get_args()
        except ValidationError as e:
            self.notify(f"Invalid argument: {e.errors()[0]['msg']}", severity="error")
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
            self._script.arg_style = arg_style
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
            arg_style=arg_style,
        )
```

- [ ] **Step 4: Smoke check — import the module to verify syntax**

Run: `uv run python -c "from scriptpilot.screens.edit import EditScreen; print('OK')"`
Expected: `OK`.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: PASS (no new failures).

- [ ] **Step 6: Commit**

```bash
git add src/scriptpilot/screens/edit.py
git commit -m "feat: EditScreen wires arg_style and catches ValidationError"
```

---

## Task 8: Update `RunScreen` for new types, validation, and argv module

**Files:**
- Modify: `src/scriptpilot/screens/run.py`

- [ ] **Step 1: Update imports**

Replace the imports block at the top of `src/scriptpilot/screens/run.py`:

```python
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Switch

from scriptpilot.argv import ArgValidationError, build_argv, validate_and_coerce
from scriptpilot.models import Script, ScriptArg
```

- [ ] **Step 2: Replace `compose` with the new render logic**

Replace `RunScreen.compose` (`src/scriptpilot/screens/run.py:50-70`):

```python
    def compose(self) -> ComposeResult:
        with Vertical(id="run-container"):
            yield Label(f"[bold]Run: {self._script.name}[/bold]")
            yield Label("")
            if any(a.type == "path" for a in self._script.args):
                yield Label(
                    "[dim]relative paths resolve against cwd[/dim]",
                    id="path-hint",
                )
            for i, arg in enumerate(self._script.args):
                req = "*" if arg.required else ""
                with Horizontal(classes="arg-row"):
                    yield Label(f"{arg.name}{req}:")
                    if arg.type == "boolean":
                        default_val = bool(arg.default) if arg.default is not None else False
                        yield Switch(value=default_val, id=f"arg-{i}")
                    elif arg.type == "choice":
                        options = [(c, c) for c in (arg.choices or [])]
                        if arg.default is not None:
                            initial = arg.default
                        elif arg.required and arg.choices:
                            initial = arg.choices[0]
                        else:
                            initial = Select.BLANK
                        yield Select(
                            options,
                            value=initial,
                            allow_blank=not arg.required,
                            id=f"arg-{i}",
                        )
                    else:
                        default_str = str(arg.default) if arg.default is not None else ""
                        placeholder = "path" if arg.type == "path" else arg.type
                        yield Input(
                            value=default_str,
                            placeholder=placeholder,
                            id=f"arg-{i}",
                        )
            with Horizontal(id="button-bar"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Run", id="run-btn", variant="success")
```

- [ ] **Step 3: Replace `_collect_and_run` to use `validate_and_coerce` + `build_argv`**

Replace `_collect_and_run` (`src/scriptpilot/screens/run.py:78-92`):

```python
    def _collect_and_run(self):
        raw_values: list[str | bool] = []
        for i, arg in enumerate(self._script.args):
            widget_id = f"arg-{i}"
            if arg.type == "boolean":
                raw_values.append(self.query_one(f"#{widget_id}", Switch).value)
            elif arg.type == "choice":
                v = self.query_one(f"#{widget_id}", Select).value
                raw_values.append("" if v is Select.BLANK else v)
            else:
                raw_values.append(
                    self.query_one(f"#{widget_id}", Input).value.strip()
                )

        validated: list[str | bool] = []
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

- [ ] **Step 4: Smoke check — import the module**

Run: `uv run python -c "from scriptpilot.screens.run import RunScreen; print('OK')"`
Expected: `OK`.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: PASS (no new failures).

- [ ] **Step 6: Commit**

```bash
git add src/scriptpilot/screens/run.py
git commit -m "feat: RunScreen renders path/choice and validates via argv module"
```

---

## Task 9: Wire `arg_style` from `GenerationResult` into `Script` construction

**Files:**
- Modify: `src/scriptpilot/screens/generate.py:173-179`
- Modify: `src/scriptpilot/screens/prompt.py:144-153`

- [ ] **Step 1: Update `GenerateScreen._do_save` to set `arg_style`**

Replace `_do_save` body block in `src/scriptpilot/screens/generate.py:173-179`:

```python
        script = Script(
            name=name,
            description=desc,
            type=language,
            content=content,
            args=self._result.args if self._result else [],
            arg_style=self._result.arg_style if self._result else "positional",
        )
        self.dismiss(script)
```

- [ ] **Step 2: Update `PromptScreen._do_accept` to set `arg_style`**

Replace the `Script(...)` construction at `src/scriptpilot/screens/prompt.py:144-153`:

```python
        updated = Script(
            id=self._script.id,
            name=self._script.name,
            description=self._script.description,
            type=self._script.type,
            content=self._result.code,
            args=self._result.args,
            timeout=self._script.timeout,
            favorite=self._script.favorite,
            cwd=self._script.cwd,
            env=self._script.env,
            arg_style=self._result.arg_style,
        )
        self.dismiss(updated)
```

(Also propagates `cwd` and `env` which the prior code dropped — a pre-existing oversight worth fixing while we're here, since modify flows currently lose those fields when accepting an LLM modification.)

- [ ] **Step 3: Smoke check**

Run: `uv run python -c "from scriptpilot.screens.generate import GenerateScreen; from scriptpilot.screens.prompt import PromptScreen; print('OK')"`
Expected: `OK`.

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/screens/generate.py src/scriptpilot/screens/prompt.py
git commit -m "feat: generate/prompt wire arg_style and preserve cwd/env on modify"
```

---

## Task 10: Final verification + manual acceptance walkthrough

**Files:** none modified.

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS. No skips beyond what was already skipped on `master`.

- [ ] **Step 2: Sanity-import the package**

Run: `uv run python -c "import scriptpilot; from scriptpilot.argv import build_argv, validate_and_coerce, ArgValidationError; from scriptpilot.models import Script, ScriptArg; print('OK')"`
Expected: `OK`.

- [ ] **Step 3: Manual acceptance walkthrough**

(Performed by the user — these are not automated, per the spec's testing section. Document any deviations as follow-up tasks.)

Run: `uv run python -m scriptpilot`

1. Create a new bash script with a `choice` arg `env` with choices `dev, staging, prod`. Save. Run it. Expected: dropdown shown in RunScreen, no Input widget. Selecting `staging` and running passes `staging` as `$1`.
2. Create a script with `cwd = ~/repos/script-pilot` and a `path` arg `manifest`. Save. Run. Type `pyproject.toml`. Expected: script receives `/home/<user>/repos/script-pilot/pyproject.toml`.
3. Create a script with an `integer` arg `n`. Run. Type `abc`. Expected: notify shows `'n' must be an integer`, focus stays on the field, script does not run.
4. Edit any positional script. Toggle the arg style Select to `--flags`. Save. Run with values. Expected: argv includes `--name value` pairs, booleans omitted on False.
5. Generate a script via AI with prompt "deploy with env (dev|staging|prod), region, dry-run". Expected: response includes `arg_style="flags"` and `choice` arg; saving produces a script that when run invokes with `--env staging --region eu --dry-run`. (Requires `OPENROUTER_API_KEY`.)

- [ ] **Step 4: No commit required for verification.**

---

## Self-Review Checklist (Author)

Spec coverage check:
- ✅ `path` and `choice` types in models — Task 1.
- ✅ `Script.arg_style` field — Task 2.
- ✅ `argv.py` `validate_and_coerce` — Task 3.
- ✅ `argv.py` `build_argv` (with positional/flags/path-resolution) — Task 4.
- ✅ Backward compat (no `arg_style` / `choices` in old meta files) — Tested in Task 1 and Task 2.
- ✅ `ArgEditor` widget extended (new types, choices sub-row, `arg_style` header) — Task 6.
- ✅ `EditScreen` wiring (`arg_style` + ValidationError catch) — Task 7.
- ✅ `RunScreen` rendering + validation (Select for choice, Input for path, integer rejection, focus retention) — Task 8.
- ✅ `openrouter.py` prompts + `GenerationResult.arg_style` + parser — Task 5.
- ✅ Generate / Prompt screens wire `arg_style` into `Script` — Task 9.
- ✅ All test additions per spec — Tasks 1, 2, 3, 4, 5.
- ✅ Manual acceptance walkthrough — Task 10.

Type-consistency check:
- `ArgValidationError(arg_name, message)` signature consistent across argv.py and tests.
- `validate_and_coerce(arg, raw)` consistent (Tasks 3, 8).
- `build_argv(script, validated)` consistent (Tasks 4, 8).
- `ArgEditor(args, arg_style="positional")` consistent (Tasks 6, 7).
- `ArgEditor.get_arg_style()` consistent (Tasks 6, 7).
- `GenerationResult.arg_style: str = "positional"` consistent (Tasks 5, 9).

No placeholders.
