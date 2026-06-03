# Conversational Script Builder — Design

**Date:** 2026-06-04
**Status:** Approved
**Source:** Task 9 (Prywatne)

## Problem

ScriptPilot generates scripts in a single one-shot LLM request. This produces three concrete problems:

1. **No conversation.** Generation is fire-and-forget; the user cannot iterate, correct, or refine a script by talking to the agent.
2. **No clarifying questions.** When a request is underspecified (e.g. "create a Cloud Build trigger runner"), the one-shot prompt silently guesses instead of asking for the GCP project, credentials path, region, etc.
3. **No self-verification.** Bad output reaches saved scripts unchecked. The reported failure — a script whose body is `node /app/cloud-build-trigger.js` referencing a `.js` file that was never created — is a direct symptom: nothing validates that the script actually runs.

## Goal

Replace one-shot generation with an integrated, clipad-style multi-turn agent that:

- Holds a conversation, asks clarifying questions, and edits the draft across turns.
- Turns the user's answers into real script args/env.
- Self-verifies every draft (layered, side-effect-free) so the JS-class bug cannot reach disk silently.
- Lets the user correct any existing saved script by reopening the conversation.

**Reference:** `~/repos/clipad` — its `agent.go` loop, OpenAI-compatible tool calling, and `bash` tool are the model for this design.

## Non-Goals (YAGNI)

- MCP server / MCP protocol layer (the task's initial framing; explicitly dropped).
- Streaming responses.
- Multiple LLM providers (Blackbox.ai only).
- Slash commands beyond `/clear`.
- Auto-running scripts with real side effects.
- Transcript search/export.

## Architecture

A new package `src/scriptpilot/agent/` holds the agent machinery; the chat UI lives in `src/scriptpilot/screens/chat.py`.

```
User ⇄ Chat screen (Textual)
          │  custom messages (assistant text, tool activity, done, error)
          ▼
   Agent loop  (Textual @work async worker)
     │  OpenAI-compatible /chat/completions  (tools, tool_choice="auto", non-streaming)
     ▼
   Blackbox.ai
     │  tool calls
     ▼
   Tool dispatch:  bash · update_script · verify
     │
     ▼
   Session working dir  ──(Save)──▶  storage (~/.scriptpilot/scripts/<id>/)
```

### Modules

| Module | Responsibility |
|--------|----------------|
| `agent/client.py` | `chat_completion(messages, tools)` against Blackbox.ai; returns assistant message incl. tool calls. Replaces the one-shot calls in `blackbox.py`. |
| `agent/loop.py` | The agent loop: accumulate messages, call client, dispatch tool calls, append `role:"tool"` results, repeat until assistant returns text with no tool calls. Hard cap on tool calls. |
| `agent/tools.py` | Tool JSON schemas + dispatch for `bash`, `update_script`, `verify`. |
| `agent/session.py` | Per-script chat session: working dir, draft `Script`, transcript (message list), `/clear`. |
| `screens/chat.py` | Textual chat screen (transcript pane, draft preview, input, Save/Cancel). |

### Provider

- Same endpoint as today: `https://api.blackbox.ai/v1/chat/completions`.
- Same key: `BLACKBOX_API_KEY` (env or `~/.scriptpilot/.env`).
- Request adds `tools` and `tool_choice: "auto"`; `stream: false`.
- Model: `AppConfig.default_model` (unchanged default).

### Threading

The loop runs in a Textual `@work` worker using async `httpx`. It communicates with the chat screen by posting custom Textual messages (assistant text, tool-call started, tool result, done, error) — mirroring clipad's event channel. Input is disabled while the worker runs.

## Session & Draft Model

When a chat opens, ScriptPilot creates a **session working directory** at `~/.scriptpilot/sessions/<session-id>/` containing the draft script file (`script.sh` / `script.py` / `script.js`, by draft type).

- **New script:** working dir starts with an empty draft file; draft `Script` has default metadata.
- **Existing script:** the saved code is copied into the working dir, and the saved `Script` metadata seeds the draft.

The `bash` tool runs with **cwd = working dir**, so `cat script.js`, `ls`, `grep` see the live draft. `update_script` writes to the working file; `verify` runs against it.

**Save** promotes the draft file + metadata to real storage (`~/.scriptpilot/scripts/<id>/`, via existing `storage.py`), then removes the working dir. **Cancel** discards the working dir.

> Rationale: keeps "draft buffer" semantics (saved store untouched until Save, clean rollback) while still giving the `bash` tool a real filesystem to read.

## Tools

The agent has exactly three tools (coarse, to minimize LLM mistakes).

### `bash(cmd: string)`

Read-oriented shell access; the user explicitly wants `ls`/`grep`/`cat`.

- Runs in the session working dir.
- Timeout `bash_tool_timeout` (default 15s); combined stdout+stderr capped (e.g. 10 KB).
- **Denylist** blocks obviously destructive ops (e.g. `rm -rf /`, `sudo`, `:(){`, `mkfs`, `shutdown`, `reboot`, `dd if=`). Not an allowlist — the user wants broad read access.
- Command is echoed into the chat transcript as a tool-activity line for transparency.
- Returns `exit <code>\n<output>`.

### `update_script(code?: string, meta_patch?: object)`

Writes new draft code and/or applies a metadata patch — this is how clarifying answers ("GCP project = X", "creds at Y") become real script structure.

- `code` (optional): replaces the draft file body.
- `meta_patch` (optional) fields, matching the real `Script` model: `name`, `type` (`bash`/`python`/`js`), `args` (list of `ScriptArg`), `env`, `timeout`, `cwd`, `description`, `arg_style`, `tags`. (Sensitive values like a credentials path are captured as an `env` var or a `path`-typed arg — there is no separate per-script "secrets" field on the model.)
- Changing `type` renames the draft file to the matching extension.
- Returns a summary of the resulting draft (type, name, code length, args, env keys) so the model sees what it produced.

### `verify()`

Layered, side-effect-free verification of the current draft.

- **L1 — syntax/parse:** `bash -n script.sh`, `python -m py_compile script.py`, `node --check script.js`.
- **L2 — resolve:** interpreter exists on PATH; entrypoint file exists; **scan the body for references to sibling files/paths that don't exist** (catches `node cloud-build-trigger.js` when no such file was written) and flag interpreter/type mismatches (e.g. a `bash`-typed script that just shells out to `node missing.js`).
- **L3 — safe-only run:** only when the agent passes `safe: true` *and* the proposed invocation looks side-effect-free (e.g. `--help`, documented dry-run flags). Otherwise skipped. Never runs destructive operations.
- Returns structured pass/fail per layer with messages, so the agent can self-correct and re-verify.

The system prompt instructs the agent to call `verify()` and resolve failures before telling the user the script is ready.

## Chat UI (`screens/chat.py`)

Replaces `screens/generate.py`.

- **Transcript pane** (scrollable): user messages, agent text, and compact tool-activity lines (`▸ bash: cat script.js`, `▸ update_script`, `▸ verify ✓`/`✗`).
- **Draft preview pane:** current draft code + detected type/name/args/env, refreshed on each `update_script`.
- **Input box** (bottom): Enter sends; disabled with a "thinking…" indicator while the worker runs.
- **Actions:** Save (commit draft → storage), Cancel (discard).

### Entry points (unified surface)

- **New script** → chat with empty draft.
- **Existing script** → "edit with agent" opens chat; working dir seeded from saved code; transcript restored.

### Slash commands

- `/clear` — resets the conversation: wipes the transcript and the agent message history, **keeps the current draft**. Only slash command in scope.

## Persistence

- **Transcript** (the message list needed for agent context) is stored as `messages.json` in the script's storage dir for **saved** scripts; reopening restores full history (the default behavior the user requested).
- For a **new, not-yet-saved** script, transcript + draft live only in the session working dir; on first Save they move into the new script's storage dir.
- `bash`/`verify` raw outputs are **not** persisted long-term — only conversational messages and the tool calls/results required for context — so `messages.json` does not balloon.

## Config

Reuse `BLACKBOX_API_KEY` and `default_model`. Add two `AppConfig` fields:

- `agent_max_tool_calls: int = 25` — hard cap on tool calls per loop run (runaway guard, like clipad's `maxToolCalls`).
- `bash_tool_timeout: int = 15` — seconds for the `bash` tool.

Settings screen displays both read-only.

## Testing (TDD)

- **Tools:** `bash` denylist + timeout + cwd; `update_script` code/meta patching incl. type-change file rename; `verify` per layer, **including the missing-sibling-file detection** that catches the JS bug.
- **Session:** working-dir lifecycle (create/seed/promote-on-save/cleanup), `/clear`.
- **Persistence:** transcript persist + restore for saved scripts; new→save migration.
- **Agent loop:** mock Blackbox endpoint with `respx` (existing dev dep) — assert tool-call dispatch, `role:"tool"` feedback, multi-turn accumulation, tool-call cap enforcement.
- **Verify integration:** real `bash -n` / `py_compile` / `node --check` against fixtures; skip the node case if `node` is absent (`node` is present in dev env: v26.1.0).

## Files Removed / Replaced

- `screens/generate.py` — removed (replaced by `screens/chat.py`).
- One-shot `generate_script` / `modify_script` in `blackbox.py` — removed; `blackbox.py` either becomes `agent/client.py` or is reduced to the shared HTTP plumbing.
- Any main-screen wiring that opens the generate modal is repointed to the chat screen.
