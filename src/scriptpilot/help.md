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
