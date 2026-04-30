# ScriptPilot — execution environment & reproducibility

**Date:** 2026-05-01
**Source task:** `~/Notes/Notes/Tasks/Prywatne/script-pilot2.md`

## Problem

Scripts run from a tempfile in an unknown cwd, with the user's global
`python3` interpreter (no per-script deps), and no access to per-script
secrets. Three coupled changes turn ScriptPilot into a usable home for
"run my CSV / API automation" scripts:

1. Per-script working directory.
2. Python deps via PEP 723 + `uv run --script` (configurable).
3. Per-script env vars merged with a global secrets file.

## Goals

- A Python script with a `# /// script` PEP 723 header runs without
  manual `pip install` / venv juggling.
- A Bash or Python script can read relative paths (`input.csv`) from
  a configured working directory.
- A script that reads `os.environ["JIRA_TOKEN"]` works as long as
  `~/.scriptpilot/.env` defines it. Per-script `env` overrides the
  global secrets file, which in turn overrides `os.environ`.

## Non-goals

- JS dep management. The `js` interpreter stays bare `node`.
- An in-app editor for the secrets file. Users edit
  `~/.scriptpilot/.env` with their own editor.
- A file-picker / "Browse" affordance for `cwd`. Plain text Input
  with `~` expansion is enough for v1.
- Variable interpolation in the secrets file (no `$FOO`, no `export`,
  no multiline values).
- UI tests. EditScreen / SettingsScreen aren't covered today; this
  change doesn't introduce that.

## Design

### Data model (`src/scriptpilot/models.py`)

```python
class Script(BaseModel):
    # ... existing fields ...
    cwd: str | None = None              # NEW. None == home at run time.
    env: dict[str, str] = {}            # NEW. Per-script env overrides.

class AppConfig(BaseModel):
    default_model: str = "openai/gpt-4o"
    python_command: str = "uv run --script"   # NEW.
```

- `cwd` stores the raw user string (e.g. `~/work/data`). Tilde
  expansion happens at execute time so saved values stay portable.
- `env` is a flat `{str: str}` dict.
- Defaults on every new field — existing on-disk meta JSON loads
  cleanly without migration.
- Empty `python_command` falls back to `python3` at execute time.

### Secrets module (new — `src/scriptpilot/secrets.py`)

```python
SECRETS_PATH = Path.home() / ".scriptpilot" / ".env"

def load_secrets(path: Path = SECRETS_PATH) -> dict[str, str]:
    """Parse a tiny dotenv file. Returns {} if missing or unreadable."""
```

Parser scope:

- One `KEY=VALUE` per line; whitespace around `=` allowed.
- Lines starting with `#` are comments; blank lines ignored.
- A matching pair of surrounding `"..."` or `'...'` quotes around the
  value is stripped. Mismatched quotes left as-is.
- Malformed lines (no `=`) are skipped silently.
- No interpolation, no `export` prefix, no multiline values.
- Missing or unreadable file (e.g. permission denied) → `{}`. The
  user not having any secrets is normal, not an error.

### Executor changes (`src/scriptpilot/executor.py`)

Three threads of change to `execute_script`:

**1. Multi-token interpreter command.** Replace `_get_interpreter`
with `_resolve_command(script_type, python_command) -> list[str]`.

```python
INTERPRETERS = {"bash": "bash", "js": "node"}
# "python" resolved dynamically from python_command.

def _resolve_command(script_type: str, python_command: str) -> list[str]:
    if script_type == "python":
        cmd = python_command.strip() or "python3"
        parts = shlex.split(cmd)
    else:
        parts = [INTERPRETERS[script_type]]
    exe = shutil.which(parts[0])
    if exe is None:
        raise InterpreterNotFoundError(f"{parts[0]} not found on PATH")
    return [exe, *parts[1:]]
```

`shutil.which` validates only the first token (`uv`), not the full
string. Trailing flags pass through untouched.

**2. cwd resolution.** New `_resolve_cwd(script_cwd) -> Path` and a
new `ScriptCwdError`:

- `None` or blank → `Path.home()`.
- Otherwise expand `~`, then check existence and that it's a
  directory. If not, raise `ScriptCwdError` with a clear message.
  No silent fallback — that masks the user's intent.

**3. Env merging.** `execute_script` gains a keyword arg
`python_command: str = "python3"` and reads secrets internally:

```python
async def execute_script(
    script: Script,
    arg_values: list[str] | None = None,
    on_output: Callable[[str], None] | None = None,
    *,
    script_path: Path,
    python_command: str = "python3",
) -> ExecutionResult:
    cmd_prefix = _resolve_command(script.type, python_command)
    cwd = _resolve_cwd(script.cwd)
    secrets = load_secrets()
    env = {**os.environ, **secrets, **script.env}

    cmd = [*cmd_prefix, str(script_path), *(arg_values or [])]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(cwd),
        env=env,
        start_new_session=True,
    )
    # ... rest unchanged ...
```

Precedence (low → high): `os.environ` < `secrets` < `script.env`.
Secrets are read live on every run so editing `~/.scriptpilot/.env`
takes effect without restarting the app.

### UI — EnvEditor (new — `src/scriptpilot/widgets/env_editor.py`)

Mirrors `ArgEditor`. Each row is `Input(KEY) + Input(VALUE) + Button(X)`.
A button at the bottom adds a new blank row.

```python
class EnvRow(Widget):
    def to_pair(self) -> tuple[str, str] | None: ...

class EnvEditor(Widget):
    def __init__(self, env: dict[str, str] | None = None): ...
    def get_env(self) -> dict[str, str]: ...
```

`get_env()` skips rows with empty keys. Values may be empty strings.

VALUE Input is **not** masked. These are non-secret per-script
overrides like `ENVIRONMENT=staging`. Real secrets live in the global
file. Spec + README call this out explicitly.

### UI — EditScreen additions (`src/scriptpilot/screens/edit.py`)

Two new fields, above `ArgEditor`:

```python
yield Label("Working Directory:")
yield Input(
    value=s.cwd if (s and s.cwd) else "",
    placeholder="~ (default: home)",
    id="cwd-input",
)
yield ArgEditor(s.args if s else [])
yield EnvEditor(s.env if s else {})
```

`_save` collects:

```python
cwd_str = self.query_one("#cwd-input", Input).value.strip() or None
env = self.query_one(EnvEditor).get_env()
```

…and sets `cwd` / `env` on the saved or newly-created `Script`.

`MainScreen.action_clone_script` also copies `cwd` and `env` onto the
clone.

### UI — SettingsScreen additions (`src/scriptpilot/screens/settings.py`)

Two new lines:

```python
yield Label("Python command:")
yield Input(
    value=self._config.python_command,
    placeholder="uv run --script",
    id="python-cmd-input",
)
yield Label(f"Secrets file: {SECRETS_PATH} [{secrets_status}]")
yield Label("[dim]One KEY=VALUE per line. Edit with your editor.[/dim]")
```

`secrets_status` is `"<n> keys loaded"` if the file exists,
`"not present"` if it doesn't. Read once on screen open.

`_save` writes `python_command` to the new `AppConfig` field. Empty
input falls back to the default `"uv run --script"`.

### MainScreen wiring (`src/scriptpilot/screens/main.py`)

One new keyword arg in `_execute`:

```python
result = await execute_script(
    script,
    arg_values=arg_values,
    on_output=collect_output,
    script_path=self._store.path_for(script.id),
    python_command=self.app._config.python_command,
)
```

Catch `ScriptCwdError` alongside `InterpreterNotFoundError`:

```python
except (InterpreterNotFoundError, ScriptCwdError) as e:
    panel.show_error(str(e))
    self.notify(str(e), severity="error")
```

### Config persistence

No changes. `app.py` already does `AppConfig(**data)` from
`~/.scriptpilot/config.json` and dumps via `model_dump`. The new
`python_command` field rides through automatically; existing config
files load cleanly because the field has a default.

## Testing

### New file — `tests/test_secrets.py`

Pure unit tests on `load_secrets`, no subprocess:

- Missing file → `{}`.
- Empty file → `{}`.
- Comments (`# foo`) and blank lines ignored.
- `KEY=value` parses; whitespace around `=` tolerated.
- Quoted values: `K="v"` and `K='v'` strip the matching quotes;
  mismatched (`K="v'`) leaves them alone.
- Malformed lines (no `=`) skipped, others still parsed.
- Last-key-wins on duplicates.
- Unreadable file (chmod 000) → `{}`, no exception.

### Extensions to `tests/test_executor.py`

- **cwd applied:** bash script runs `pwd`, output equals configured cwd.
- **cwd default:** unset cwd → output equals `Path.home()`.
- **cwd missing dir:** `Script(cwd="/nonexistent/path")` → `ScriptCwdError`.
- **cwd not a directory:** path points at a file → `ScriptCwdError`.
- **cwd `~` expansion:** `cwd="~"` resolves to `Path.home()`.
- **env merging precedence:** monkeypatch `os.environ["X"]="from_env"`,
  monkeypatch `load_secrets` to return `{"X": "from_secrets", "Y":
  "y_secret"}`, set `script.env={"X": "from_script", "Z": "z_script"}`.
  Bash script prints all three. Assert `X=from_script`, `Y=y_secret`,
  `Z=z_script`.
- **per-script env without secrets:** `script.env={"FOO": "bar"}`
  → `echo $FOO` prints `bar`.
- **`python_command` honored:** run a python script with
  `python_command="python3"` (uv-free path) and assert it works. If
  `uv` is on PATH, also run with `python_command="uv run --script"` to
  cover the multi-token path; skip otherwise.
- **`python_command` first-token validation:**
  `python_command="definitely-not-a-real-cmd"` → `InterpreterNotFoundError`.
- **`python_command` empty string** → falls back to `python3`.

Existing tests need only the new keyword arg defaults — pass
`python_command="python3"` where they instantiate Python scripts.

### UI tests

Out of scope. Existing screens aren't covered; this change doesn't
introduce that. Manual smoke check at the end of implementation.

## Acceptance criteria

| Criterion (from task) | How it's met |
|---|---|
| Python script with `# /// script` PEP 723 header runs without manual setup | `python_command="uv run --script"` (default) → uv reads the header, manages venv, installs deps. Manual smoke: a script with `dependencies = ["requests"]`. |
| Bash script with `cwd=~/work/data` and arg `input.csv` resolves the file | `_resolve_cwd` expands `~`, executor passes `cwd=` to subprocess. Covered by cwd test + manual smoke. |
| Script reading `os.environ["JIRA_TOKEN"]` works when `~/.scriptpilot/.env` has it | `load_secrets()` reads the file, merged into subprocess env. Covered by env-merging test + manual smoke. |

## README

One paragraph added describing:

- The optional `~/.scriptpilot/.env` file and its format (KEY=VALUE
  per line, `#` comments, no interpolation).
- The `python_command` setting and the `uv run --script` default
  (link to `uv` docs / PEP 723).
- The per-script `cwd` (with `~` support) and `env` fields, plus a
  reminder that real secrets belong in the global file, not in
  per-script `env`.
