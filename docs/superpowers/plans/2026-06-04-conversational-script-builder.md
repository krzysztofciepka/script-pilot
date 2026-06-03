# Conversational Script Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace ScriptPilot's one-shot AI generate/modify flows with an integrated, clipad-style multi-turn agent that converses, asks clarifying questions, edits a draft script across turns via tools, and self-verifies the draft before it is saved.

**Architecture:** A new `src/scriptpilot/agent/` package holds the agent machinery: a low-level Blackbox chat client (tool-calling), a per-session draft model backed by a working directory, three coarse tools (`bash`, `update_script`, `verify`), and an async agent loop. A new `screens/chat.py` Textual screen drives the conversation. The old `GenerateScreen`/`PromptScreen` and the one-shot helpers in `blackbox.py` are removed.

**Tech Stack:** Python 3.10+, Textual (TUI), httpx (async HTTP), Pydantic v2 (models), pytest + pytest-asyncio + respx (tests). Provider: Blackbox.ai OpenAI-compatible `/chat/completions` with `tools`.

---

## File Structure

**Create:**
- `src/scriptpilot/agent/__init__.py` — package marker + public exports.
- `src/scriptpilot/agent/prompts.py` — the builder agent system prompt.
- `src/scriptpilot/agent/verify.py` — layered, side-effect-free draft verification.
- `src/scriptpilot/agent/session.py` — `ChatSession`: working dir, draft `Script`, message list, `/clear`, draft updates.
- `src/scriptpilot/agent/tools.py` — tool JSON schemas, `bash` runner, `dispatch_tool`.
- `src/scriptpilot/agent/loop.py` — `AgentEvent` + `run_agent_loop`.
- `src/scriptpilot/screens/chat.py` — `ChatScreen` Textual UI.
- `tests/agent/test_verify.py`, `tests/agent/test_session.py`, `tests/agent/test_tools.py`, `tests/agent/test_loop.py`, `tests/test_chat_screen.py`.

**Modify:**
- `src/scriptpilot/blackbox.py` — reduce to shared HTTP layer + add `chat_completion`.
- `src/scriptpilot/models.py` — add two `AppConfig` fields.
- `src/scriptpilot/storage.py` — add transcript persistence.
- `src/scriptpilot/screens/main.py` — repoint `p` (prompt) action to `ChatScreen`.
- `src/scriptpilot/app.py` — repoint `g` (generate) action to `ChatScreen`; remove `GenerateScreen` import.
- `README.md` — document the conversational builder.

**Delete:**
- `src/scriptpilot/screens/generate.py`, `src/scriptpilot/screens/prompt.py`.
- `tests/test_blackbox.py` is rewritten (old one-shot tests removed).

---

## Task 1: Reduce `blackbox.py` to a shared HTTP layer with `chat_completion`

**Files:**
- Modify: `src/scriptpilot/blackbox.py`
- Test: `tests/test_blackbox.py` (replace entire file)

- [ ] **Step 1: Replace the test file with tool-calling tests**

Overwrite `tests/test_blackbox.py` with:

```python
import httpx
import pytest
import respx

from scriptpilot.blackbox import (
    AuthenticationError,
    BlackboxConnectionError,
    RateLimitError,
    chat_completion,
    get_api_key,
)

BASE = "https://api.blackbox.ai/v1/chat/completions"


@respx.mock
async def test_chat_completion_returns_assistant_message():
    respx.post(BASE).mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "hi"}}]},
        )
    )
    msg = await chat_completion(
        [{"role": "user", "content": "hello"}], "model-x", api_key="k"
    )
    assert msg["content"] == "hi"


@respx.mock
async def test_chat_completion_passes_tools_and_tool_choice():
    route = respx.post(BASE).mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": ""}}]}
        )
    )
    tools = [{"type": "function", "function": {"name": "t", "parameters": {}}}]
    await chat_completion([], "m", api_key="k", tools=tools)
    sent = respx.calls.last.request
    import json
    body = json.loads(sent.content)
    assert body["tools"] == tools
    assert body["tool_choice"] == "auto"


@respx.mock
async def test_chat_completion_returns_tool_calls():
    respx.post(BASE).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {"name": "bash", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ]
            },
        )
    )
    msg = await chat_completion([], "m", api_key="k")
    assert msg["tool_calls"][0]["function"]["name"] == "bash"


@respx.mock
async def test_chat_completion_auth_error():
    respx.post(BASE).mock(return_value=httpx.Response(401))
    with pytest.raises(AuthenticationError):
        await chat_completion([], "m", api_key="bad")


@respx.mock
async def test_chat_completion_rate_limit():
    respx.post(BASE).mock(return_value=httpx.Response(429))
    with pytest.raises(RateLimitError):
        await chat_completion([], "m", api_key="k")


@respx.mock
async def test_chat_completion_server_error_is_connection_error():
    respx.post(BASE).mock(return_value=httpx.Response(500))
    with pytest.raises(BlackboxConnectionError):
        await chat_completion([], "m", api_key="k")


def test_get_api_key_prefers_env(monkeypatch):
    monkeypatch.setenv("BLACKBOX_API_KEY", "env-key")
    assert get_api_key() == "env-key"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_blackbox.py -q`
Expected: FAIL — `ImportError: cannot import name 'chat_completion'`.

- [ ] **Step 3: Rewrite `blackbox.py` to the reduced shared layer**

Overwrite `src/scriptpilot/blackbox.py` with:

```python
from __future__ import annotations

import os

import httpx

from scriptpilot.secrets import load_secrets

BASE_URL = "https://api.blackbox.ai/v1"
API_KEY_ENV = "BLACKBOX_API_KEY"


class AuthenticationError(Exception):
    """Raised when the API key is invalid."""


class RateLimitError(Exception):
    """Raised when rate limited by Blackbox."""


class BlackboxConnectionError(Exception):
    """Raised when unable to reach Blackbox."""


def get_api_key() -> str:
    """Resolve the Blackbox API key from env, falling back to ~/.scriptpilot/.env."""
    key = os.environ.get(API_KEY_ENV, "").strip()
    if key:
        return key
    return load_secrets().get(API_KEY_ENV, "").strip()


async def chat_completion(
    messages: list[dict],
    model: str,
    *,
    api_key: str,
    tools: list[dict] | None = None,
    timeout: int = 120,
) -> dict:
    """POST a chat-completion request; return the assistant message dict.

    The returned dict has ``role`` and ``content`` and may carry ``tool_calls``
    when the model invokes tools. Raises AuthenticationError / RateLimitError /
    BlackboxConnectionError on the corresponding failures.
    """
    payload: dict = {"model": model, "messages": messages}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout,
            )
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        raise BlackboxConnectionError(f"Could not reach Blackbox: {e}") from e

    if response.status_code == 401:
        raise AuthenticationError("Invalid API key")
    if response.status_code == 429:
        raise RateLimitError("Rate limited by Blackbox")
    if response.status_code >= 500:
        raise BlackboxConnectionError("Blackbox server error")
    response.raise_for_status()

    return response.json()["choices"][0]["message"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_blackbox.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/blackbox.py tests/test_blackbox.py
git commit -m "refactor: reduce blackbox.py to shared chat_completion with tool calling"
```

---

## Task 2: Add agent config fields to `AppConfig`

**Files:**
- Modify: `src/scriptpilot/models.py:81-88`
- Test: `tests/test_models.py` (append; create if absent)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_models.py` (create the file with `from scriptpilot.models import AppConfig` at top if it does not exist):

```python
def test_appconfig_agent_defaults():
    from scriptpilot.models import AppConfig
    cfg = AppConfig()
    assert cfg.agent_max_tool_calls == 25
    assert cfg.bash_tool_timeout == 15


def test_appconfig_agent_fields_override():
    from scriptpilot.models import AppConfig
    cfg = AppConfig(agent_max_tool_calls=5, bash_tool_timeout=30)
    assert cfg.agent_max_tool_calls == 5
    assert cfg.bash_tool_timeout == 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -q`
Expected: FAIL — `AttributeError`/validation: no `agent_max_tool_calls`.

- [ ] **Step 3: Add the fields**

In `src/scriptpilot/models.py`, change the `AppConfig` class body to:

```python
class AppConfig(BaseModel):
    """Application configuration."""

    default_model: str = "blackboxai/minimax/minimax-m2.5"
    python_command: str = "uv run --script"
    editor: str | None = None
    scripts_dir: str | None = None
    theme: Literal["dark", "light"] = "dark"
    agent_max_tool_calls: int = 25
    bash_tool_timeout: int = 15
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/models.py tests/test_models.py
git commit -m "feat: add agent_max_tool_calls and bash_tool_timeout config"
```

---

## Task 3: Layered draft verification (`agent/verify.py`)

**Files:**
- Create: `src/scriptpilot/agent/__init__.py` (empty), `src/scriptpilot/agent/verify.py`
- Test: `tests/agent/__init__.py` (empty), `tests/agent/test_verify.py`

- [ ] **Step 1: Create the empty package markers**

Create `src/scriptpilot/agent/__init__.py` with a single line:

```python
"""Conversational script-builder agent."""
```

Create `tests/agent/__init__.py` as an empty file (touch it; no content needed).

- [ ] **Step 2: Write the failing tests**

Create `tests/agent/test_verify.py`:

```python
import shutil
from pathlib import Path

import pytest

from scriptpilot.agent.verify import find_missing_references, verify_draft


def test_find_missing_references_flags_node_call_to_absent_file(tmp_path):
    content = "node /app/cloud-build-trigger.js\n"
    missing = find_missing_references("js", content, tmp_path)
    assert "/app/cloud-build-trigger.js" in missing


def test_find_missing_references_ignores_existing_sibling(tmp_path):
    (tmp_path / "helper.js").write_text("console.log(1)")
    content = "node helper.js\n"
    missing = find_missing_references("js", content, tmp_path)
    assert missing == []


def test_verify_draft_bash_syntax_error_fails(tmp_path):
    p = tmp_path / "script.sh"
    p.write_text("if then fi\n")  # invalid bash
    result = verify_draft("bash", p)
    assert not result.ok
    assert any(l.name == "syntax" and not l.passed for l in result.layers)


def test_verify_draft_valid_bash_passes(tmp_path):
    p = tmp_path / "script.sh"
    p.write_text("echo hello\n")
    result = verify_draft("bash", p)
    assert result.ok


def test_verify_draft_python_syntax_error_fails(tmp_path):
    p = tmp_path / "script.py"
    p.write_text("def (:\n")
    result = verify_draft("python", p)
    assert not result.ok


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_verify_draft_js_missing_reference_fails(tmp_path):
    p = tmp_path / "script.js"
    # Syntactically valid JS, but shells out to a file that does not exist.
    p.write_text("const x = 1;\n// node /app/cloud-build-trigger.js\n")
    result = verify_draft("js", p)
    assert not result.ok
    assert any(l.name == "resolve" and not l.passed for l in result.layers)


def test_verify_draft_safe_run_executes(tmp_path):
    p = tmp_path / "script.sh"
    p.write_text('echo "ran with $1"\n')
    result = verify_draft("bash", p, safe_run=["--help"])
    assert result.ok
    assert any(l.name == "run" for l in result.layers)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/agent/test_verify.py -q`
Expected: FAIL — `ModuleNotFoundError: scriptpilot.agent.verify`.

- [ ] **Step 4: Implement `agent/verify.py`**

Create `src/scriptpilot/agent/verify.py`:

```python
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from scriptpilot.paths import EXTENSIONS

# Interpreter used to syntax-check each script type. ``None`` means resolved
# dynamically (handled inline below).
_SYNTAX_CHECK = {
    "bash": ["bash", "-n"],
    "python": ["python3", "-m", "py_compile"],
    "js": ["node", "--check"],
}

_INTERPRETERS = {"bash": "bash", "python": "python3", "js": "node"}

# Matches an interpreter invoking a script file, e.g. ``node foo.js`` or
# ``python3 /app/run.py``. Group 1 is the referenced path.
_REF_RE = re.compile(
    r"\b(?:node|python3?|bash|sh)\s+([^\s;|&'\"]+\.(?:js|mjs|cjs|py|sh))"
)


@dataclass
class LayerResult:
    name: str  # "syntax" | "resolve" | "run"
    passed: bool
    detail: str


@dataclass
class VerifyResult:
    ok: bool
    layers: list[LayerResult] = field(default_factory=list)

    def summary(self) -> str:
        head = "VERIFY PASSED" if self.ok else "VERIFY FAILED"
        body = "\n".join(
            f"  [{'ok' if l.passed else 'FAIL'}] {l.name}: {l.detail}"
            for l in self.layers
        )
        return f"{head}\n{body}"


def find_missing_references(script_type: str, content: str, base_dir: Path) -> list[str]:
    """Return referenced script paths that do not exist on disk.

    Catches the classic bug where the body is e.g. ``node
    /app/cloud-build-trigger.js`` but no such file was written. A referenced
    path is resolved relative to ``base_dir`` (absolute paths used as-is) and
    reported when it is missing and is not the draft file itself.
    """
    missing: list[str] = []
    draft_name = f"script{EXTENSIONS.get(script_type, '')}"
    for raw in _REF_RE.findall(content):
        ref = Path(raw)
        resolved = ref if ref.is_absolute() else (base_dir / ref)
        if resolved.name == draft_name:
            continue
        if not resolved.exists():
            missing.append(raw)
    return missing


def _run_check(argv: list[str], timeout: int = 20) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except FileNotFoundError as e:
        return False, str(e)
    detail = (proc.stderr or proc.stdout or "").strip()[:500]
    return proc.returncode == 0, detail or f"exit {proc.returncode}"


def verify_draft(
    script_type: str,
    draft_path: Path,
    *,
    safe_run: list[str] | None = None,
) -> VerifyResult:
    """Verify a draft in side-effect-free layers.

    L1 syntax: ``bash -n`` / ``python -m py_compile`` / ``node --check``.
    L2 resolve: interpreter on PATH; entrypoint exists; no missing references.
    L3 run: only when ``safe_run`` argv is provided (e.g. ``["--help"]``).
    """
    layers: list[LayerResult] = []
    content = draft_path.read_text() if draft_path.exists() else ""

    # L1 — syntax
    check = _SYNTAX_CHECK.get(script_type)
    if check is None:
        layers.append(LayerResult("syntax", False, f"unknown type {script_type!r}"))
        return VerifyResult(ok=False, layers=layers)
    ok, detail = _run_check([*check, str(draft_path)])
    layers.append(LayerResult("syntax", ok, "valid syntax" if ok else detail))
    if not ok:
        return VerifyResult(ok=False, layers=layers)

    # L2 — resolve
    interp = _INTERPRETERS[script_type]
    problems: list[str] = []
    if shutil.which(interp) is None:
        problems.append(f"interpreter {interp!r} not on PATH")
    if not draft_path.exists():
        problems.append("entrypoint file missing")
    missing = find_missing_references(script_type, content, draft_path.parent)
    if missing:
        problems.append("references missing files: " + ", ".join(missing))
    resolve_ok = not problems
    layers.append(
        LayerResult("resolve", resolve_ok, "resolved" if resolve_ok else "; ".join(problems))
    )
    if not resolve_ok:
        return VerifyResult(ok=False, layers=layers)

    # L3 — safe run (opt-in)
    if safe_run is not None:
        argv = [interp, str(draft_path), *safe_run]
        ok, detail = _run_check(argv)
        layers.append(LayerResult("run", ok, detail))
        if not ok:
            return VerifyResult(ok=False, layers=layers)

    return VerifyResult(ok=True, layers=layers)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/agent/test_verify.py -q`
Expected: PASS (node test skipped if node absent; node IS present in this env: v26.1.0).

- [ ] **Step 6: Commit**

```bash
git add src/scriptpilot/agent/__init__.py src/scriptpilot/agent/verify.py tests/agent/__init__.py tests/agent/test_verify.py
git commit -m "feat: layered side-effect-free draft verification"
```

---

## Task 4: `ChatSession` — working dir, draft, updates, clear

**Files:**
- Create: `src/scriptpilot/agent/session.py`
- Test: `tests/agent/test_session.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/agent/test_session.py`:

```python
from scriptpilot.agent.session import ChatSession
from scriptpilot.models import Script


def test_new_session_has_empty_bash_draft(tmp_path):
    s = ChatSession.new(tmp_path / "work")
    assert s.draft.type == "bash"
    assert s.draft.content == ""
    assert s.draft_path.exists()
    assert s.draft_path.name == "script.sh"
    assert s.messages and s.messages[0]["role"] == "system"


def test_from_script_copies_code_and_meta(tmp_path):
    original = Script(name="orig", description="d", type="js", content="console.log(1)")
    s = ChatSession.from_script(original, tmp_path / "work")
    assert s.draft.type == "js"
    assert s.draft_path.name == "script.js"
    assert s.draft_path.read_text() == "console.log(1)"
    # Draft is a copy: mutating it must not touch the original.
    assert s.draft.id == original.id


def test_apply_update_writes_code(tmp_path):
    s = ChatSession.new(tmp_path / "work")
    summary = s.apply_update(code="echo hi", meta_patch=None)
    assert s.draft.content == "echo hi"
    assert s.draft_path.read_text() == "echo hi"
    assert "bash" in summary


def test_apply_update_type_change_renames_file(tmp_path):
    s = ChatSession.new(tmp_path / "work")
    old_path = s.draft_path
    s.apply_update(code="print(1)", meta_patch={"type": "python"})
    assert s.draft.type == "python"
    assert s.draft_path.name == "script.py"
    assert not old_path.exists()
    assert s.draft_path.read_text() == "print(1)"


def test_apply_update_sets_args_and_env(tmp_path):
    s = ChatSession.new(tmp_path / "work")
    s.apply_update(
        code=None,
        meta_patch={
            "name": "gcp-trigger",
            "env": {"GCP_PROJECT": "my-proj"},
            "args": [{"name": "region", "type": "string", "required": True}],
        },
    )
    assert s.draft.name == "gcp-trigger"
    assert s.draft.env == {"GCP_PROJECT": "my-proj"}
    assert s.draft.args[0].name == "region"


def test_clear_keeps_draft_resets_messages(tmp_path):
    s = ChatSession.new(tmp_path / "work")
    s.apply_update(code="echo hi", meta_patch=None)
    s.messages.append({"role": "user", "content": "hello"})
    s.clear()
    assert s.draft.content == "echo hi"  # draft kept
    assert len(s.messages) == 1 and s.messages[0]["role"] == "system"  # only system


def test_to_script_returns_draft_copy(tmp_path):
    s = ChatSession.new(tmp_path / "work")
    s.apply_update(code="echo hi", meta_patch={"name": "n", "description": "d"})
    script = s.to_script()
    assert script.name == "n"
    assert script.content == "echo hi"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/agent/test_session.py -q`
Expected: FAIL — `ModuleNotFoundError: scriptpilot.agent.session`.

- [ ] **Step 3: Implement `agent/session.py`**

Create `src/scriptpilot/agent/session.py`:

```python
from __future__ import annotations

import shutil
from pathlib import Path

from scriptpilot.agent.prompts import system_prompt
from scriptpilot.models import Script, ScriptArg
from scriptpilot.paths import EXTENSIONS

# Fields on Script the agent may patch via update_script.
_PATCHABLE = {
    "name",
    "type",
    "args",
    "env",
    "timeout",
    "cwd",
    "description",
    "arg_style",
    "tags",
}


class ChatSession:
    """A single conversational script-building session.

    Holds the in-memory draft ``Script``, a working directory containing the
    draft body file (so the ``bash`` tool can ``cat`` it), and the running
    message list (system prompt first).
    """

    def __init__(self, draft: Script, work_dir: Path):
        self.draft = draft
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.messages: list[dict] = [{"role": "system", "content": system_prompt()}]
        self._write_draft()

    @classmethod
    def new(cls, work_dir: Path) -> "ChatSession":
        draft = Script(name="", description="", type="bash", content="")
        return cls(draft, work_dir)

    @classmethod
    def from_script(cls, script: Script, work_dir: Path) -> "ChatSession":
        draft = Script(**script.model_dump())
        return cls(draft, work_dir)

    @property
    def draft_path(self) -> Path:
        return self.work_dir / f"script{EXTENSIONS[self.draft.type]}"

    def _write_draft(self):
        self.draft_path.write_text(self.draft.content)

    def apply_update(self, code: str | None, meta_patch: dict | None) -> str:
        old_path = self.draft_path
        data = self.draft.model_dump()
        if meta_patch:
            for key, value in meta_patch.items():
                if key not in _PATCHABLE:
                    continue
                if key == "args":
                    value = [ScriptArg(**a) if isinstance(a, dict) else a for a in value]
                data[key] = value
        if code is not None:
            data["content"] = code
        self.draft = Script(**data)

        # Type change renames the body file.
        if self.draft_path != old_path:
            old_path.unlink(missing_ok=True)
        self._write_draft()
        return self._summary()

    def _summary(self) -> str:
        d = self.draft
        return (
            f"draft updated: name={d.name!r} type={d.type} "
            f"code_len={len(d.content)} args={[a.name for a in d.args]} "
            f"env_keys={list(d.env)}"
        )

    def clear(self):
        self.messages = [{"role": "system", "content": system_prompt()}]

    def to_script(self) -> Script:
        return Script(**self.draft.model_dump())

    def cleanup(self):
        shutil.rmtree(self.work_dir, ignore_errors=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/agent/test_session.py -q`
Expected: FAIL — `ModuleNotFoundError: scriptpilot.agent.prompts` (created next task). This is expected; proceed to Task 5 which creates `prompts.py`, then re-run.

> Note: Task 5 must land before this task's tests can pass. If executing strictly task-by-task, create the minimal `prompts.py` from Task 5 Step 3 first, then return here.

- [ ] **Step 5: Commit (after Task 5's `prompts.py` exists and tests pass)**

```bash
git add src/scriptpilot/agent/session.py tests/agent/test_session.py
git commit -m "feat: ChatSession draft model with working dir and updates"
```

---

## Task 5: Builder agent system prompt (`agent/prompts.py`)

**Files:**
- Create: `src/scriptpilot/agent/prompts.py`
- Test: `tests/agent/test_prompts.py`

- [ ] **Step 1: Write the failing test**

Create `tests/agent/test_prompts.py`:

```python
from scriptpilot.agent.prompts import system_prompt


def test_system_prompt_mentions_tools_and_behaviors():
    p = system_prompt().lower()
    for token in ("bash", "update_script", "verify", "clarify", "script.sh"):
        assert token in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agent/test_prompts.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `agent/prompts.py`**

Create `src/scriptpilot/agent/prompts.py`:

```python
from __future__ import annotations

_SYSTEM_PROMPT = """\
You are ScriptPilot's script-building agent. You collaborate with the user to \
build a single automation script through a multi-turn conversation.

You have three tools:
- bash(cmd): run a read-oriented shell command in the session working directory. \
The current draft is the file `script.sh`, `script.py`, or `script.js` (by type) \
in that directory — use `cat script.sh` (etc.), `ls`, and `grep` to inspect it. \
Do NOT rely on memory of the code; read it when you need it.
- update_script(code, meta_patch): write new draft code and/or patch metadata. \
meta_patch may set name, description, type (bash|python|js), args, env, timeout, \
cwd, arg_style, tags. Turn the user's answers into real structure: a GCP project \
becomes an env var or arg; a credentials path becomes a `path`-typed arg or env var.
- verify(safe_run): run layered, side-effect-free checks on the current draft \
(syntax, interpreter/file resolution, and — only when you pass a safe_run argv \
like ["--help"] — a safe execution). 

Rules:
- ASK CLARIFYING QUESTIONS whenever the request is underspecified. Example: for a \
"cloud build trigger runner", ask for the GCP project, region, and where the \
credentials JSON lives before writing code that assumes them.
- After writing or changing the script, CALL verify() and fix any failures before \
telling the user it is ready. Never claim the script works without verifying.
- Keep the script self-contained: do not shell out to other script files that you \
have not created. A `js` script's body must be JavaScript, not a shell line that \
runs `node some-other-file.js`.
- Be concise. When you are done and the draft is verified, tell the user it is \
ready to save.
"""


def system_prompt() -> str:
    return _SYSTEM_PROMPT
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/agent/test_prompts.py tests/agent/test_session.py -q`
Expected: PASS (both files; session tests now resolve `prompts`).

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/agent/prompts.py tests/agent/test_prompts.py src/scriptpilot/agent/session.py tests/agent/test_session.py
git commit -m "feat: builder agent system prompt + ChatSession"
```

---

## Task 6: `bash` tool runner with denylist and timeout

**Files:**
- Create: `src/scriptpilot/agent/tools.py`
- Test: `tests/agent/test_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/agent/test_tools.py`:

```python
from scriptpilot.agent.tools import is_denied, run_bash


def test_run_bash_returns_exit_and_output(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    out = run_bash("cat a.txt", tmp_path, timeout=10)
    assert out.startswith("exit 0")
    assert "hello" in out


def test_run_bash_runs_in_cwd(tmp_path):
    (tmp_path / "only-here.txt").write_text("x")
    out = run_bash("ls", tmp_path, timeout=10)
    assert "only-here.txt" in out


def test_run_bash_nonzero_exit(tmp_path):
    out = run_bash("exit 3", tmp_path, timeout=10)
    assert out.startswith("exit 3")


def test_run_bash_timeout(tmp_path):
    out = run_bash("sleep 5", tmp_path, timeout=1)
    assert "timed out" in out.lower()


def test_denylist_blocks_destructive():
    assert is_denied("rm -rf /")
    assert is_denied("sudo reboot")
    assert is_denied("dd if=/dev/zero of=/dev/sda")
    assert not is_denied("cat script.sh")
    assert not is_denied("grep -r foo .")


def test_run_bash_blocks_denied(tmp_path):
    out = run_bash("rm -rf /", tmp_path, timeout=10)
    assert "blocked" in out.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/agent/test_tools.py -q`
Expected: FAIL — `ModuleNotFoundError: scriptpilot.agent.tools`.

- [ ] **Step 3: Implement the `bash` runner in `agent/tools.py`**

Create `src/scriptpilot/agent/tools.py`:

```python
from __future__ import annotations

import re
import subprocess
from pathlib import Path

_MAX_OUTPUT = 10_000  # chars

_DENY_PATTERNS = [
    r"\brm\s+-[a-z]*r[a-z]*f?\s+/",  # rm -rf /
    r"\bsudo\b",
    r"\bmkfs\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bdd\s+if=",
    r":\(\)\s*\{",  # fork bomb
]
_DENY_RE = [re.compile(p) for p in _DENY_PATTERNS]


def is_denied(cmd: str) -> bool:
    """True when the command matches an obviously destructive pattern."""
    return any(r.search(cmd) for r in _DENY_RE)


def run_bash(cmd: str, cwd: Path, timeout: int) -> str:
    """Run a shell command in ``cwd``; return ``exit <code>\\n<output>``."""
    if is_denied(cmd):
        return "blocked: command matches a destructive-operation denylist"
    try:
        proc = subprocess.run(
            ["bash", "-c", cmd],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"exit -1\nbash command timed out after {timeout}s"
    output = (proc.stdout or "") + (proc.stderr or "")
    if len(output) > _MAX_OUTPUT:
        output = output[:_MAX_OUTPUT] + "\n…[output truncated]"
    return f"exit {proc.returncode}\n{output}".rstrip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/agent/test_tools.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/agent/tools.py tests/agent/test_tools.py
git commit -m "feat: bash tool runner with denylist and timeout"
```

---

## Task 7: Tool schemas + `dispatch_tool`

**Files:**
- Modify: `src/scriptpilot/agent/tools.py`
- Test: `tests/agent/test_tools.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/agent/test_tools.py`:

```python
from scriptpilot.agent.session import ChatSession
from scriptpilot.agent.tools import TOOL_SCHEMAS, dispatch_tool


def test_tool_schemas_cover_all_three():
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert names == {"bash", "update_script", "verify"}
    for t in TOOL_SCHEMAS:
        assert t["type"] == "function"
        assert "parameters" in t["function"]


def test_dispatch_bash(tmp_path):
    s = ChatSession.new(tmp_path / "work")
    out = dispatch_tool("bash", {"cmd": "echo hi"}, s, bash_timeout=10)
    assert "hi" in out


def test_dispatch_update_script(tmp_path):
    s = ChatSession.new(tmp_path / "work")
    out = dispatch_tool(
        "update_script", {"code": "echo hi", "meta_patch": {"name": "n"}}, s, bash_timeout=10
    )
    assert s.draft.content == "echo hi"
    assert s.draft.name == "n"
    assert "draft updated" in out


def test_dispatch_verify(tmp_path):
    s = ChatSession.new(tmp_path / "work")
    s.apply_update(code="echo ok", meta_patch=None)
    out = dispatch_tool("verify", {}, s, bash_timeout=10)
    assert "VERIFY PASSED" in out


def test_dispatch_unknown_tool(tmp_path):
    s = ChatSession.new(tmp_path / "work")
    out = dispatch_tool("nope", {}, s, bash_timeout=10)
    assert "unknown tool" in out.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/agent/test_tools.py -q`
Expected: FAIL — `ImportError: cannot import name 'TOOL_SCHEMAS'`.

- [ ] **Step 3: Add schemas + dispatch to `agent/tools.py`**

Append to `src/scriptpilot/agent/tools.py` (add the import line at the top, below the existing imports):

```python
from scriptpilot.agent.verify import verify_draft
```

Then append at the end of the file:

```python
TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": (
                "Run a read-oriented bash command (ls, cat, grep, …) in the "
                "session working directory. The draft is script.sh/.py/.js there."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "The bash command."}
                },
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_script",
            "description": (
                "Write new draft code and/or patch metadata (name, description, "
                "type, args, env, timeout, cwd, arg_style, tags)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Full new script body."},
                    "meta_patch": {
                        "type": "object",
                        "description": "Partial Script metadata to merge.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify",
            "description": (
                "Verify the current draft (syntax, file/interpreter resolution, "
                "and an optional safe run). Pass safe_run only for side-effect-free "
                "invocations like ['--help']."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "safe_run": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional safe argv to execute, e.g. ['--help'].",
                    }
                },
            },
        },
    },
]


def dispatch_tool(name: str, arguments: dict, session, *, bash_timeout: int) -> str:
    """Execute a tool call against ``session``; return the tool result text."""
    if name == "bash":
        return run_bash(arguments.get("cmd", ""), session.work_dir, bash_timeout)
    if name == "update_script":
        return session.apply_update(
            code=arguments.get("code"), meta_patch=arguments.get("meta_patch")
        )
    if name == "verify":
        result = verify_draft(
            session.draft.type, session.draft_path, safe_run=arguments.get("safe_run")
        )
        return result.summary()
    return f"unknown tool: {name}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/agent/test_tools.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/agent/tools.py tests/agent/test_tools.py
git commit -m "feat: tool schemas and dispatch (bash/update_script/verify)"
```

---

## Task 8: Agent loop (`agent/loop.py`)

**Files:**
- Create: `src/scriptpilot/agent/loop.py`
- Test: `tests/agent/test_loop.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/agent/test_loop.py`:

```python
import json

import httpx
import respx

from scriptpilot.agent.loop import AgentEvent, run_agent_loop
from scriptpilot.agent.session import ChatSession

BASE = "https://api.blackbox.ai/v1/chat/completions"


def _assistant(content="", tool_calls=None):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return httpx.Response(200, json={"choices": [{"message": msg}]})


def _collect():
    events: list[AgentEvent] = []
    return events, lambda e: events.append(e)


@respx.mock
async def test_loop_text_only_emits_done(tmp_path):
    respx.post(BASE).mock(return_value=_assistant(content="Hello, what should it do?"))
    s = ChatSession.new(tmp_path / "w")
    s.messages.append({"role": "user", "content": "hi"})
    events, emit = _collect()
    await run_agent_loop(s, "m", "key", max_tool_calls=25, bash_timeout=10, emit=emit)
    kinds = [e.kind for e in events]
    assert "assistant_text" in kinds
    assert kinds[-1] == "done"


@respx.mock
async def test_loop_dispatches_tool_then_finishes(tmp_path):
    tool_call = [{"id": "c1", "type": "function",
                  "function": {"name": "update_script",
                               "arguments": json.dumps({"code": "echo hi"})}}]
    respx.post(BASE).side_effect = [
        _assistant(content="", tool_calls=tool_call),
        _assistant(content="Done, the script is ready."),
    ]
    s = ChatSession.new(tmp_path / "w")
    s.messages.append({"role": "user", "content": "make it echo hi"})
    events, emit = _collect()
    await run_agent_loop(s, "m", "key", max_tool_calls=25, bash_timeout=10, emit=emit)
    assert s.draft.content == "echo hi"
    # A tool result message was appended for the tool call.
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "c1"
               for m in s.messages)
    assert [e.kind for e in events][-1] == "done"
    assert any(e.kind == "tool_result" for e in events)


@respx.mock
async def test_loop_respects_tool_call_cap(tmp_path):
    # Always returns a tool call → would loop forever without the cap.
    tool_call = [{"id": "c", "type": "function",
                  "function": {"name": "bash", "arguments": json.dumps({"cmd": "echo x"})}}]
    respx.post(BASE).mock(return_value=_assistant(content="", tool_calls=tool_call))
    s = ChatSession.new(tmp_path / "w")
    s.messages.append({"role": "user", "content": "go"})
    events, emit = _collect()
    await run_agent_loop(s, "m", "key", max_tool_calls=3, bash_timeout=10, emit=emit)
    tool_results = [e for e in events if e.kind == "tool_result"]
    assert len(tool_results) <= 3
    assert events[-1].kind in ("done", "error")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/agent/test_loop.py -q`
Expected: FAIL — `ModuleNotFoundError: scriptpilot.agent.loop`.

- [ ] **Step 3: Implement `agent/loop.py`**

Create `src/scriptpilot/agent/loop.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from scriptpilot.agent.session import ChatSession
from scriptpilot.agent.tools import TOOL_SCHEMAS, dispatch_tool
from scriptpilot.blackbox import chat_completion


@dataclass
class AgentEvent:
    kind: str  # "assistant_text" | "tool_started" | "tool_result" | "done" | "error"
    text: str = ""
    tool: str = ""


EmitFn = Callable[[AgentEvent], None]


async def run_agent_loop(
    session: ChatSession,
    model: str,
    api_key: str,
    *,
    max_tool_calls: int,
    bash_timeout: int,
    emit: EmitFn,
) -> None:
    """Drive the agent until it returns text with no tool calls (or hits the cap).

    Appends assistant + tool messages onto ``session.messages`` as it goes and
    reports progress through ``emit``. Exceptions are reported as an ``error``
    event rather than propagated.
    """
    calls = 0
    try:
        while True:
            assistant = await chat_completion(
                session.messages, model, api_key=api_key, tools=TOOL_SCHEMAS
            )
            session.messages.append(assistant)

            content = assistant.get("content") or ""
            if content.strip():
                emit(AgentEvent("assistant_text", text=content))

            tool_calls = assistant.get("tool_calls") or []
            if not tool_calls:
                emit(AgentEvent("done"))
                return

            for tc in tool_calls:
                if calls >= max_tool_calls:
                    session.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": "tool-call limit reached; stopping.",
                        }
                    )
                    emit(AgentEvent("done"))
                    return
                calls += 1
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                emit(AgentEvent("tool_started", tool=name))
                result = dispatch_tool(name, args, session, bash_timeout=bash_timeout)
                session.messages.append(
                    {"role": "tool", "tool_call_id": tc["id"], "content": result}
                )
                emit(AgentEvent("tool_result", tool=name, text=result))
    except Exception as e:  # surfaced to the UI, never crashes the worker
        emit(AgentEvent("error", text=str(e)))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/agent/test_loop.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/agent/loop.py tests/agent/test_loop.py
git commit -m "feat: multi-turn agent loop with tool dispatch and cap"
```

---

## Task 9: Transcript persistence in `ScriptStore`

**Files:**
- Modify: `src/scriptpilot/storage.py`
- Test: `tests/test_storage_transcript.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_storage_transcript.py`:

```python
from scriptpilot.models import Script
from scriptpilot.storage import ScriptStore


def test_load_transcript_missing_returns_empty(tmp_path):
    store = ScriptStore(path=tmp_path)
    assert store.load_transcript("nope") == []


def test_save_and_load_transcript_roundtrip(tmp_path):
    store = ScriptStore(path=tmp_path)
    script = Script(name="n", description="d", type="bash", content="echo hi")
    store.add(script)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]
    store.save_transcript(script.id, messages)
    assert store.load_transcript(script.id) == messages


def test_delete_removes_transcript(tmp_path):
    store = ScriptStore(path=tmp_path)
    script = Script(name="n", description="d", type="bash", content="x")
    store.add(script)
    store.save_transcript(script.id, [{"role": "user", "content": "hi"}])
    store.delete(script.id)
    assert store.load_transcript(script.id) == []
    assert not (tmp_path / f"{script.id}.messages.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_storage_transcript.py -q`
Expected: FAIL — `AttributeError: 'ScriptStore' object has no attribute 'load_transcript'`.

- [ ] **Step 3: Add transcript methods to `ScriptStore`**

In `src/scriptpilot/storage.py`, add these methods to the `ScriptStore` class (place after `path_for`):

```python
    def transcript_path(self, script_id: str) -> Path:
        return self._dir / f"{script_id}.messages.json"

    def save_transcript(self, script_id: str, messages: list[dict]):
        self._atomic_write(
            self.transcript_path(script_id), json.dumps(messages, indent=2)
        )

    def load_transcript(self, script_id: str) -> list[dict]:
        path = self.transcript_path(script_id)
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return []
```

Then update `delete` to also remove the transcript. Change the `delete` method body to:

```python
    def delete(self, script_id: str):
        for ext in EXTENSIONS.values():
            (self._dir / f"{script_id}{ext}").unlink(missing_ok=True)
        (self._dir / f"{script_id}.meta.json").unlink(missing_ok=True)
        self.transcript_path(script_id).unlink(missing_ok=True)
        self._scripts.pop(script_id, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_storage_transcript.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/storage.py tests/test_storage_transcript.py
git commit -m "feat: persist per-script chat transcript in ScriptStore"
```

---

## Task 10: `ChatScreen` Textual UI (`screens/chat.py`)

**Files:**
- Create: `src/scriptpilot/screens/chat.py`
- Test: `tests/test_chat_screen.py`

This screen drives the conversation. It accepts an optional existing `Script` (None ⇒ new), a `ScriptStore` (for transcript load/save), and config values. On submit it appends a user message and runs `run_agent_loop` in a Textual worker, posting `AgentMessage` events back to the UI. `/clear` resets the conversation. Save returns the draft `Script` (and persists the transcript) via `dismiss`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_chat_screen.py`:

```python
import httpx
import respx

from scriptpilot.app import ScriptPilotApp
from scriptpilot.screens.chat import ChatScreen
from scriptpilot.storage import ScriptStore

BASE = "https://api.blackbox.ai/v1/chat/completions"


def _assistant(content):
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})


async def test_clear_command_resets_transcript(tmp_path):
    store = ScriptStore(path=tmp_path)
    app = ScriptPilotApp()
    async with app.run_test() as pilot:
        screen = ChatScreen(store=store, script=None, model="m", api_key="k",
                            max_tool_calls=25, bash_timeout=10)
        await app.push_screen(screen)
        await pilot.pause()
        screen._append_transcript("user", "something")
        screen._handle_input("/clear")
        await pilot.pause()
        # Only the system message remains in the session.
        assert len(screen.session.messages) == 1
        assert screen.session.messages[0]["role"] == "system"


@respx.mock
async def test_send_message_runs_agent_and_shows_reply(tmp_path):
    respx.post(BASE).mock(return_value=_assistant("Ready to save."))
    store = ScriptStore(path=tmp_path)
    app = ScriptPilotApp()
    async with app.run_test() as pilot:
        screen = ChatScreen(store=store, script=None, model="m", api_key="k",
                            max_tool_calls=25, bash_timeout=10)
        await app.push_screen(screen)
        await pilot.pause()
        screen._handle_input("make a hello script")
        # Wait for the agent worker to finish.
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "Ready to save" in screen._log_text
```

> Note: the assertion uses `screen._log_text`, an accumulating string the screen maintains for testability (defined in the implementation below).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat_screen.py -q`
Expected: FAIL — `ModuleNotFoundError: scriptpilot.screens.chat`.

- [ ] **Step 3: Implement `screens/chat.py`**

Create `src/scriptpilot/screens/chat.py`:

```python
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RichLog, TextArea

from scriptpilot.agent.loop import AgentEvent, run_agent_loop
from scriptpilot.agent.session import ChatSession
from scriptpilot.models import Script
from scriptpilot.storage import ScriptStore

TEXTUAL_LANGUAGES = {"bash": "bash", "python": "python", "js": "javascript"}


class ChatScreen(ModalScreen[Script | None]):
    """Conversational script builder for new and existing scripts."""

    DEFAULT_CSS = """
    ChatScreen { align: center middle; }
    ChatScreen #chat-container {
        width: 90%; height: 90%;
        background: $surface; border: solid $primary; padding: 1 2;
    }
    ChatScreen #chat-body { height: 1fr; }
    ChatScreen #chat-log { width: 1fr; border: round $panel; padding: 0 1; }
    ChatScreen #draft-preview { width: 1fr; }
    ChatScreen #chat-input { dock: bottom; }
    ChatScreen #chat-buttons { height: 3; align: right middle; dock: bottom; }
    ChatScreen #chat-buttons Button { margin-left: 1; }
    """

    def __init__(
        self,
        *,
        store: ScriptStore,
        script: Script | None,
        model: str,
        api_key: str,
        max_tool_calls: int,
        bash_timeout: int,
    ):
        super().__init__()
        self._store = store
        self._existing = script
        self._model = model
        self._api_key = api_key
        self._max_tool_calls = max_tool_calls
        self._bash_timeout = bash_timeout
        self._log_text = ""  # accumulating transcript text (testability)

        work_dir = self._store._dir.parent / "sessions" / Script(
            name="", description="", type="bash", content=""
        ).id
        if script is None:
            self.session = ChatSession.new(work_dir)
        else:
            self.session = ChatSession.from_script(script, work_dir)
            saved = self._store.load_transcript(script.id)
            if saved:
                self.session.messages = saved

    def compose(self) -> ComposeResult:
        title = "New script" if self._existing is None else f"Edit: {self._existing.name}"
        with Vertical(id="chat-container"):
            yield Label(f"[bold]{title}[/bold]  (type /clear to reset)")
            with Horizontal(id="chat-body"):
                yield RichLog(id="chat-log", wrap=True, markup=True)
                yield TextArea(
                    self.session.draft.content,
                    id="draft-preview",
                    language=TEXTUAL_LANGUAGES.get(self.session.draft.type, "bash"),
                    read_only=True,
                )
            yield Input(id="chat-input", placeholder="Describe or refine the script…")
            with Horizontal(id="chat-buttons"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Save", id="save-btn", variant="success")

    def on_mount(self):
        # Replay any restored conversation (skip the system message).
        for msg in self.session.messages[1:]:
            role = msg.get("role")
            if role == "user":
                self._append_transcript("user", msg.get("content", ""))
            elif role == "assistant" and (msg.get("content") or "").strip():
                self._append_transcript("agent", msg["content"])

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "chat-input":
            text = event.value.strip()
            event.input.value = ""
            if text:
                self._handle_input(text)

    def _handle_input(self, text: str):
        if text == "/clear":
            self.session.clear()
            self.query_one("#chat-log", RichLog).clear()
            self._log_text = ""
            self._append_transcript("system", "(conversation cleared)")
            return
        self._append_transcript("user", text)
        self.session.messages.append({"role": "user", "content": text})
        self.query_one("#chat-input", Input).disabled = True
        self.run_worker(self._run_agent(), name="agent", exclusive=True)

    async def _run_agent(self):
        # The agent loop runs as an async worker in the event loop (not a
        # thread), so emit can update widgets directly.
        await run_agent_loop(
            self.session,
            self._model,
            self._api_key,
            max_tool_calls=self._max_tool_calls,
            bash_timeout=self._bash_timeout,
            emit=self._apply_event,
        )

    def _apply_event(self, ev: AgentEvent):
        if ev.kind == "assistant_text":
            self._append_transcript("agent", ev.text)
        elif ev.kind == "tool_started":
            self._append_transcript("tool", f"▸ {ev.tool}")
        elif ev.kind == "tool_result":
            self._refresh_preview()
        elif ev.kind == "error":
            self._append_transcript("error", ev.text)
            self.query_one("#chat-input", Input).disabled = False
        elif ev.kind == "done":
            self._refresh_preview()
            self.query_one("#chat-input", Input).disabled = False
            self.query_one("#chat-input", Input).focus()

    def _append_transcript(self, who: str, text: str):
        colors = {"user": "cyan", "agent": "green", "tool": "yellow",
                  "error": "red", "system": "dim"}
        label = {"user": "you", "agent": "agent", "tool": "", "error": "error",
                 "system": ""}[who]
        prefix = f"[{colors[who]}]{label}:[/] " if label else ""
        line = f"{prefix}{text}"
        self._log_text += text + "\n"
        self.query_one("#chat-log", RichLog).write(line)

    def _refresh_preview(self):
        preview = self.query_one("#draft-preview", TextArea)
        preview.language = TEXTUAL_LANGUAGES.get(self.session.draft.type, "bash")
        preview.load_text(self.session.draft.content)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel-btn":
            self.session.cleanup()
            self.dismiss(None)
        elif event.button.id == "save-btn":
            self._do_save()

    def _do_save(self):
        if not self.session.draft.name.strip():
            self.notify("Ask the agent to set a name, or it can't be saved.",
                        severity="error")
            return
        if not self.session.draft.content.strip():
            self.notify("Nothing to save yet.", severity="error")
            return
        script = self.session.to_script()
        # Preserve the id when editing an existing script.
        if self._existing is not None:
            script.id = self._existing.id
        self.session.cleanup()
        self.dismiss(script)
```

> `emit` calls `self._apply_event` directly. This is safe because `run_worker` with a coroutine schedules an async task on Textual's event loop (same thread as the UI), so widget mutations from within the loop are valid — no cross-thread `post_message` needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_chat_screen.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/screens/chat.py tests/test_chat_screen.py
git commit -m "feat: ChatScreen conversational builder UI"
```

---

## Task 11: Wire `ChatScreen` into the app; remove old screens

**Files:**
- Modify: `src/scriptpilot/app.py`, `src/scriptpilot/screens/main.py`
- Delete: `src/scriptpilot/screens/generate.py`, `src/scriptpilot/screens/prompt.py`
- Test: existing suite (regression)

- [ ] **Step 1: Repoint the `g` (generate) action in `app.py`**

In `src/scriptpilot/app.py`, replace the `GenerateScreen` import line:

```python
from scriptpilot.screens.generate import GenerateScreen
```

with:

```python
from scriptpilot.screens.chat import ChatScreen
from scriptpilot.blackbox import get_api_key
```

Then replace the `action_generate` method body with:

```python
    def action_generate(self):
        def on_result(script: Script | None):
            if script:
                self._store.add(script)
                self._store.save_transcript(script.id, [])  # fresh transcript slot
                for screen in self.screen_stack:
                    if isinstance(screen, MainScreen):
                        screen._refresh_list()
                        break
                self.notify(f"Script '{script.name}' saved")

        self.push_screen(
            ChatScreen(
                store=self._store,
                script=None,
                model=self._config.default_model,
                api_key=get_api_key(),
                max_tool_calls=self._config.agent_max_tool_calls,
                bash_timeout=self._config.bash_tool_timeout,
            ),
            callback=on_result,
        )
```

- [ ] **Step 2: Repoint the `p` (prompt) action in `main.py`**

In `src/scriptpilot/screens/main.py`, replace the import:

```python
from scriptpilot.screens.prompt import PromptScreen
```

with:

```python
from scriptpilot.screens.chat import ChatScreen
from scriptpilot.blackbox import get_api_key
```

Then replace the `action_prompt_script` method body with:

```python
    def action_prompt_script(self):
        if not self._selected_script:
            self.notify("No script selected", severity="warning")
            return

        script = self._selected_script
        cfg = self.app._config

        def on_result(updated: Script | None):
            if updated:
                self._store.update(updated)
                self._store.save_transcript(
                    updated.id, []
                )  # transcript persisted by screen on save is optional; reset slot
                self._selected_script = updated
                self._refresh_list()
                last_run = self._get_last_run(updated.id)
                self.query_one(MainPanel).show_script_details(updated, last_run)

        self.app.push_screen(
            ChatScreen(
                store=self._store,
                script=script,
                model=cfg.default_model,
                api_key=get_api_key(),
                max_tool_calls=cfg.agent_max_tool_calls,
                bash_timeout=cfg.bash_tool_timeout,
            ),
            callback=on_result,
        )
```

> Transcript persistence on Save: to keep the saved conversation, the `ChatScreen._do_save` may also call `self._store.save_transcript(script.id, self.session.messages)` before dismiss. Add that single line in `_do_save` right before `self.session.cleanup()` so reopening restores history. (Do this now.)

In `src/scriptpilot/screens/chat.py`, in `_do_save`, insert before `self.session.cleanup()`:

```python
        self._store.save_transcript(script.id, self.session.messages)
```

(The `app.action_generate`/`action_prompt_script` `save_transcript(..., [])` calls are redundant once the screen persists on save; remove those two redundant lines to avoid clobbering — i.e. delete the `self._store.save_transcript(script.id, [])` line in `action_generate` and the one in `action_prompt_script`.)

- [ ] **Step 3: Delete the obsolete screens**

```bash
git rm src/scriptpilot/screens/generate.py src/scriptpilot/screens/prompt.py
```

- [ ] **Step 4: Run the full suite to verify no regressions**

Run: `uv run pytest -q`
Expected: PASS. If any test imports `GenerateScreen` or `PromptScreen`, delete or update that test (e.g. an old `tests/test_generate_screen.py` / `tests/test_prompt_screen.py`) — search with `grep -rn "GenerateScreen\|PromptScreen" tests/`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: wire ChatScreen for generate (g) and prompt (p); remove one-shot screens"
```

---

## Task 12: Settings display + README

**Files:**
- Modify: `src/scriptpilot/screens/settings.py`, `README.md`
- Test: existing suite

- [ ] **Step 1: Show the two agent settings (read-only) in the settings screen**

Read `src/scriptpilot/screens/settings.py` first. Following the existing pattern used for `python_command`, add two read-only `Label`s near the model/python-command section displaying `agent_max_tool_calls` and `bash_tool_timeout` from the passed-in `AppConfig`, e.g.:

```python
            yield Label(f"Agent max tool calls: {self._config.agent_max_tool_calls}")
            yield Label(f"Bash tool timeout (s): {self._config.bash_tool_timeout}")
```

Place these inside the same container that renders the other config fields. Do not add inputs (these are tuned via `~/.scriptpilot/config.json`).

- [ ] **Step 2: Run the suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 3: Update `README.md`**

In `README.md`, replace any description of one-shot "Generate"/"Prompt" AI features with the conversational builder. Add a short section:

```markdown
### Conversational script builder

Press `g` to build a new script by chatting with the agent, or `p` to refine the
selected script. The agent asks clarifying questions (e.g. GCP project, credentials
path), edits a draft across turns, and self-verifies it (syntax + interpreter/file
resolution + optional safe run) before you Save. Type `/clear` to restart the
conversation. Requires `BLACKBOX_API_KEY`.
```

- [ ] **Step 4: Commit**

```bash
git add src/scriptpilot/screens/settings.py README.md
git commit -m "docs: settings display + README for conversational builder"
```

---

## Task 13: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `uv run pytest -q`
Expected: PASS — all tests green.

- [ ] **Step 2: Import smoke test**

Run: `uv run python -c "import scriptpilot.app, scriptpilot.screens.chat, scriptpilot.agent.loop"`
Expected: no output, exit 0 (no import errors).

- [ ] **Step 3: Launch smoke test (manual)**

Run: `uv run scriptpilot` (with `BLACKBOX_API_KEY` set), press `g`, ask for a trivial bash script, confirm the agent replies, the draft preview updates, `verify` runs, and Save returns to the list. Press `q` to quit.

- [ ] **Step 4: Confirm no dangling references**

Run: `grep -rn "GenerateScreen\|PromptScreen\|generate_script\|modify_script\|parse_generation_response" src/ tests/`
Expected: no matches.

---

## Self-Review Notes

- **Spec coverage:** conversational/agent-driven (Tasks 8, 10) · correct existing scripts (Tasks 10–11, `p` action) · clarifying questions (Task 5 prompt) · turn answers into args/env (Task 4 `apply_update`, Task 7 dispatch) · JS missing-file bug fix (Task 3 `find_missing_references`) · self-verification (Tasks 3, 7) · draft buffer + Save (Tasks 4, 10) · per-script transcript + `/clear` (Tasks 9, 10) · no MCP (none added) · config fields (Task 2) · remove old one-shot flows (Task 11). All spec sections map to a task.
- **Ordering caveat:** Task 4's tests depend on Task 5's `prompts.py`; Task 4 Step 4 calls this out explicitly. If executing strictly in order, create `prompts.py` (Task 5 Step 3) before running Task 4's tests.
- **Type consistency:** `chat_completion(messages, model, *, api_key, tools=None)` used identically in Task 1 (def), Task 8 (loop), and Task 10 (via loop). `dispatch_tool(name, arguments, session, *, bash_timeout)` consistent across Tasks 7, 8. `AgentEvent(kind, text, tool)` consistent across Tasks 8, 10. `verify_draft(script_type, draft_path, *, safe_run=None)` consistent across Tasks 3, 7.
