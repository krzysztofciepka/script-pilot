# ScriptPilot

A terminal UI for creating, managing, and executing automation scripts (bash, Python, JavaScript) with optional AI-powered script generation via [blackbox.ai](https://www.blackbox.ai/).

```
┌─────────────────────────────────────────────────────┐
│  ScriptPilot                              [Settings] │
├──────────────┬──────────────────────────────────────┤
│              │                                      │
│  Script List │     Main Panel                       │
│              │     - Script Details                 │
│  > Script 1  │     - Output Terminal                │
│    Script 2  │     - Argument Form                  │
│    Script 3  │     - AI Generation                  │
│              │                                      │
├──────────────┴──────────────────────────────────────┤
│  [r] Run  [e] Edit  [d] Delete  [g] Generate w/ AI  │
└─────────────────────────────────────────────────────┘
```

## Features

- **Script management** — create, edit, and delete bash, Python, and JavaScript scripts
- **Script execution** — run scripts with real-time streaming output, exit codes, and configurable timeouts
- **Argument support** — define typed arguments (string, integer, boolean) with defaults; interactive input form before execution
- **AI generation** — describe what you want in plain English, pick a language, and let an LLM write the script via blackbox.ai
- **Persistence** — scripts and settings saved to `~/.scriptpilot/` across sessions
- **Light/dark themes** — toggle with `t`

## Install

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
uv tool install git+https://github.com/krzysztofciepka/script-pilot.git
```

Or install from a local clone:

```bash
git clone https://github.com/krzysztofciepka/script-pilot.git
cd script-pilot
uv tool install -e .
```

Then run:

```bash
scriptpilot
```

## Upgrading

If you're using the prebuilt Linux x86-64 binary from [releases](https://github.com/krzysztofciepka/script-pilot/releases), upgrade in place:

```bash
scriptpilot --upgrade
```

This downloads the latest release asset, verifies its sha256 against the GitHub API, and atomically replaces the running binary (with rollback on failure).

For `uv tool` installs, run `uv tool upgrade scriptpilot` instead.

## AI Generation (Optional)

To use AI-powered script generation, set your [blackbox.ai](https://www.blackbox.ai/) API key — either as an env var or in `~/.scriptpilot/.env`:

```bash
export BLACKBOX_API_KEY="sk-..."
```

The default model is `blackboxai/minimax/minimax-m2.5`. You can change it in Settings (`s`).

## Reproducible Execution

Each script can pin its **working directory** and **environment variables** in the edit screen, so relative paths and per-script overrides Just Work.

### Per-script `cwd`

Set `Working Directory` in the edit screen to e.g. `~/work/data`. The script runs from that directory; `~` is expanded at run time. Leave blank to use your home directory. A missing or non-directory path fails the run with a clear error.

### Per-script `env`

Add `KEY=VALUE` pairs in the edit screen's Environment Variables section for non-secret overrides like `ENVIRONMENT=staging`. These are merged on top of `os.environ` and the global secrets file (next section).

### Global secrets file

ScriptPilot reads `~/.scriptpilot/.env` on every run. One `KEY=VALUE` per line; `#` comments and blank lines are ignored; surrounding `"..."` or `'...'` are stripped. No interpolation, no `export`, no multiline values.

```
# ~/.scriptpilot/.env
JIRA_TOKEN=eyJhbGciOi...
OPENAI_API_KEY="sk-..."
```

Don't paste tokens into per-script `env` — they live with the script body and would be cloned/shared. Use this file instead.

Precedence (low → high): `os.environ` < `~/.scriptpilot/.env` < per-script `env`.

### Python deps via `uv run --script` (PEP 723)

By default ScriptPilot runs Python scripts with `uv run --script`, so a script with a [PEP 723](https://peps.python.org/pep-0723/) header pulls its deps automatically:

```python
# /// script
# dependencies = ["pandas", "openpyxl"]
# ///
import pandas as pd
print(pd.read_csv("input.csv").shape)
```

Change `Python command` in Settings to `python3` if you don't have [`uv`](https://docs.astral.sh/uv/) installed; PEP 723 won't be honoured in that mode. Bash and JS interpreters (`bash`, `node`) are not configurable.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `j`/`k`, arrows | Navigate script list |
| `r` | Run selected script |
| `n` | New script |
| `e` | Edit selected script |
| `d` | Delete selected script |
| `g` | Generate script with AI |
| `s` | Settings |
| `t` | Toggle light/dark theme |
| `q` | Quit |

## Development

```bash
git clone https://github.com/krzysztofciepka/script-pilot.git
cd script-pilot
uv sync
uv run pytest -v
uv run scriptpilot
```

## License

MIT
