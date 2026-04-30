# ScriptPilot — Store Scripts as Files on Disk

## Motivation

Today, the entire script library lives in a single `~/.scriptpilot/scripts.json` blob (`src/scriptpilot/storage.py:14`). Moving each script to its own file on disk unlocks:

- Editing a script with `$EDITOR` against a real file
- `git init ~/.scriptpilot/scripts` to version-control the script library
- `rg` / `grep` across the script library outside the TUI
- Trivial export (copy the file) and import (drop a file in)

The single-blob storage is also a poor fit for the future: each new feature (tags, env vars, cwd, etc.) becomes a JSON-schema migration of every user's blob. Per-script metadata files make those changes additive and forward-compatible.

## Scope

**In scope:**
- Refactor `ScriptStore` to read and write per-script files in `~/.scriptpilot/scripts/`.
- Add `ScriptStore.path_for(script_id)` for callers that need the on-disk path.
- Switch the executor to run the on-disk body file directly (drop the per-run tempfile).
- Update all tests for the new contract.

**Out of scope:**
- Migrating the existing `scripts.json` blob (no migration; the new store ignores it).
- Adding new `Script` fields like `cwd`, `env`, `tags` — those are deferred to follow-up tasks. The new layout makes them easy to add later.
- An "import via filesystem scan" action — deferred. Only entries with both meta and body files are loaded.
- Editing a script via `$EDITOR` from inside the TUI — deferred. `path_for()` enables this; the keybinding and screen integration are a separate task.

## On-disk layout

```
~/.scriptpilot/
├── scripts/                    ← new: the script library directory
│   ├── <uuid>.py               ← script body (.py / .sh / .js based on type)
│   ├── <uuid>.meta.json        ← metadata (no `content` field)
│   ├── <uuid>.sh
│   ├── <uuid>.meta.json
│   └── …
├── history.json                ← unchanged
└── config.json                 ← unchanged
```

- The script body and meta file share a UUID stem.
- A "tracked script" requires **both** files to exist. Orphans are skipped silently on load.
- The directory is `git init`-friendly: bodies sit next to one another, metas are JSON, no shared blob to merge-conflict on.

## `meta.json` schema

Each `<uuid>.meta.json` holds the persistable fields of `Script` **except** `content`:

```json
{
  "id": "9b1e…",
  "name": "deploy-staging",
  "description": "Pushes the staging branch and tails logs",
  "type": "bash",
  "args": [
    {"name": "branch", "type": "string", "required": true, "default": null}
  ],
  "timeout": 60,
  "favorite": false
}
```

- `id` is duplicated into the meta JSON (alongside being the filename stem). If the user accidentally renames the file, the meta still self-identifies. The store prefers the filename stem if they disagree (filename is authoritative).
- `content` is **not** in the JSON. It's read from the sibling body file when needed.
- Pydantic ignores unknown keys by default, so older binaries can read newer metas (forward-compatible). Older metas missing newer keys fall back to model defaults.

## `Script` model

`Script` (in `models.py`) is **unchanged**:

- `content: str` remains an in-memory field on the Pydantic model.
- The store decides what gets serialized: meta fields go to `meta.json`, `content` goes to the body file.
- This keeps the model symmetric with how the rest of the codebase already uses `Script`.

## `ScriptStore` API

The constructor's `path` argument now refers to the **directory**, not a JSON file. Default: `~/.scriptpilot/scripts/`.

```python
class ScriptStore:
    def __init__(self, path: Path | None = None):
        self._dir = path or Path.home() / ".scriptpilot" / "scripts"
        self._scripts: dict[str, Script] = {}
        self._load()

    def list(self) -> list[Script]: ...
    def get(self, script_id: str) -> Script | None: ...
    def add(self, script: Script): ...
    def update(self, script: Script): ...
    def delete(self, script_id: str): ...

    # New:
    def path_for(self, script_id: str) -> Path:
        """On-disk path of the script body. Used by executor and editor."""
```

### Behavior per operation

- **`_load()`** — `mkdir -p` the directory if missing, then walk it for `*.meta.json`. For each:
  1. Parse the meta JSON. If unparseable, skip this entry (do not crash other scripts).
  2. Locate the sibling body file using the extension for `meta["type"]`. If missing, skip this entry.
  3. Read the body file's text.
  4. Construct `Script(**meta, content=body_text)`. Override `id` with the filename stem if it differs from `meta["id"]` — the filename is authoritative. (`Script.content` is a required model field with no default, so it must be passed at construction time.)
  5. Insert into `self._scripts`.
- **`add(script)` / `update(script)`** —
  1. Derive body extension from `script.type`.
  2. Atomic-write the body file (`tempfile.mkstemp` in `self._dir`, write, `Path(tmp).replace(target)`).
  3. Atomic-write the meta JSON the same way. Meta JSON is `script.model_dump()` minus `content`.
  4. On `update`, if the existing on-disk body is at a different extension (type changed), `unlink(missing_ok=True)` the old body after the new body is in place.
  5. Update `self._scripts` last.
- **`delete(id)`** —
  1. Unlink the body file (any of the three extensions, `missing_ok=True`).
  2. Unlink the meta file (`missing_ok=True`).
  3. Pop from `self._scripts`.
- **`path_for(id)`** —
  1. Look up the in-memory script by id; raise `KeyError` if unknown.
  2. Return `self._dir / f"{id}{EXTENSIONS[script.type]}"`.

### Atomicity model

Body and meta are independent atomic writes. If meta succeeds but the body write fails (or vice versa), the next load may see an orphan, which is skipped. Acceptable: failures bubble up as exceptions, the user retries, and the loader is robust to half-written state.

### Constructor signature change

This is a **breaking change** for callers that pass an explicit path. Two callers:

- `app.py:33` — `ScriptStore()` with no args; unaffected by the signature semantics.
- `tests/test_storage.py` — passes `tmp_path / "scripts.json"`. Updated to `tmp_path / "scripts"` (a directory).

## Executor change

`executor.execute_script` runs the interpreter directly on the on-disk body file instead of a per-run tempfile.

```python
async def execute_script(
    script: Script,
    arg_values: list[str] | None = None,
    on_output: Callable[[str], None] | None = None,
    *,
    script_path: Path,           # new: provided by caller (via ScriptStore.path_for)
) -> ExecutionResult:
    interpreter = _get_interpreter(script.type)
    if interpreter is None:
        raise InterpreterNotFoundError(...)

    cmd = [interpreter, str(script_path)]
    if arg_values:
        cmd.extend(arg_values)
    # … rest of the asyncio subprocess logic is unchanged …
```

Removals:

- The `tempfile.mkstemp(...)` block and the `try/finally` that unlinks it.
- `os.chmod(tmp_path, 0o755)` for bash. Not needed: the interpreter is invoked as `bash <path>`, not `./<path>`, so the body file does not need to be executable.

Caller update:

- `screens/main.py` — `MainScreen._execute` (the one place that calls `execute_script`) passes `script_path=self._store.path_for(script.id)`. `MainScreen` already holds the store reference.

The "scripts that were never saved" case does not exist: the run screen only runs scripts already loaded from `ScriptStore`.

## Shared extension mapping

Today `EXTENSIONS = {"bash": ".sh", "python": ".py", "js": ".js"}` lives in `executor.py`. After the refactor both `storage.py` and `executor.py` need it. To avoid one importing from the other, move the mapping (and the matching `INTERPRETERS` mapping that stays with the executor's concerns) into a new small module:

- **New file:** `src/scriptpilot/paths.py` — contains `EXTENSIONS` only.

Both `storage.py` and `executor.py` import from `paths.py`. `INTERPRETERS` stays in `executor.py`.

## Tests

### `tests/test_storage.py` — rewritten

The fixture changes from a JSON file to a directory:

```python
@pytest.fixture
def store(tmp_path):
    return ScriptStore(tmp_path / "scripts")
```

Existing cases kept (semantics adjusted to the new contract):
- `test_list_empty`
- `test_add_and_get`
- `test_add_persists_to_disk` — second `ScriptStore` over the same directory sees the script
- `test_list_returns_all` — multiple scripts of mixed types
- `test_update`
- `test_delete` — both body and meta files are removed
- `test_get_nonexistent_returns_none`
- `test_creates_parent_directory` — `ScriptStore(nonexistent_path)` creates the directory on first add

New cases:
- `test_add_writes_body_and_meta_files`
- `test_meta_json_excludes_content`
- `test_load_reads_content_from_body_file`
- `test_orphan_meta_skipped` — meta without body → not in `list()`
- `test_orphan_body_skipped` — body without meta → not in `list()`
- `test_corrupt_meta_skipped` — invalid-JSON meta → that one is skipped, others still load
- `test_update_changes_type_renames_body_file` — `python` → `bash` deletes old `.py`, creates new `.sh`
- `test_path_for_returns_body_path`

Removed cases:
- `test_corrupted_json_backs_up_and_resets` — there is no longer a single JSON blob to corrupt; corruption handling moved to per-meta-file behavior (see `test_corrupt_meta_skipped`).
- `test_atomic_write` — replaced by the structural body+meta tests above.

### `tests/test_executor.py` — updated

Each test that calls `execute_script` now passes `script_path`. A small fixture writes the script body to `tmp_path` and yields the `(script, path)` pair so tests stay concise.

### Other test files

`tests/test_models.py`, `tests/test_history.py`, `tests/test_openrouter.py` — unchanged.

## File summary

**Edited:**
- `src/scriptpilot/storage.py` — rewritten around per-file storage (no migration). New `path_for()`. Constructor takes a directory.
- `src/scriptpilot/executor.py` — drop tempfile, accept `script_path`. `EXTENSIONS` moves out.
- `src/scriptpilot/screens/main.py` — `MainScreen._execute` passes `script_path=self._store.path_for(script.id)` to `execute_script`.
- `tests/test_storage.py` — rewritten around the new contract.
- `tests/test_executor.py` — updated to provide `script_path`.

**New:**
- `src/scriptpilot/paths.py` — single home for the type → extension mapping.

**Unchanged:**
- `src/scriptpilot/models.py` — `Script` keeps `content` as an in-memory field.
- `src/scriptpilot/history.py`, `src/scriptpilot/app.py`, all screens except `main.py`, `src/scriptpilot/openrouter.py`.

## Acceptance criteria

- On first launch with an empty `~/.scriptpilot/`, the new `scripts/` directory is created automatically and the app starts cleanly with an empty list.
- Creating a script via the TUI writes both `<id>.<ext>` and `<id>.meta.json` in `~/.scriptpilot/scripts/`. The body file's contents match the textarea exactly.
- Editing a script via the TUI updates both the body file and `meta.json`. Changing the type renames the body file's extension.
- Deleting a script removes both files.
- Restarting the app loads every previously-saved script with its content, name, args, timeout, and favorite flag intact.
- Orphan files (meta without body, body without meta, unparseable meta) are silently skipped on load; the rest of the library still loads.
- Running a script invokes the interpreter against `<id>.<ext>` directly — no per-run tempfile is created in `/tmp`.
- The existing legacy `~/.scriptpilot/scripts.json` blob (if present) is left untouched on disk and is not read by the new store.
