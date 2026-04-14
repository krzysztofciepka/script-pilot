# Script-Pilot Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add prompt-to-modify, auto-arg extraction, cloning, favorites, run history, and single-binary build to the script-pilot TUI.

**Architecture:** Incremental enhancement of existing architecture. New structured LLM response format (code + args JSON) underpins both generation and modification. New `HistoryStore` for run history. PyInstaller for single binary.

**Tech Stack:** Python 3.10+, Textual, httpx, Pydantic, PyInstaller, pytest, respx

---

## File Structure

| File | Responsibility | Change |
|------|---------------|--------|
| `src/scriptpilot/models.py` | Data models | Add `favorite` to `Script`, add `RunRecord` |
| `src/scriptpilot/openrouter.py` | LLM API client | New system prompts, `GenerationResult`, `parse_generation_response`, `MalformedResponseError`, `modify_script`, retry logic, update `generate_script` |
| `src/scriptpilot/history.py` | Run history persistence | New file: `HistoryStore` class |
| `src/scriptpilot/screens/prompt.py` | Prompt-to-modify modal | New file: `PromptScreen` |
| `src/scriptpilot/screens/generate.py` | AI generation modal | Handle `GenerationResult`, auto-populate args |
| `src/scriptpilot/screens/main.py` | Main screen | New bindings (p, c, f), output collection, history integration |
| `src/scriptpilot/widgets/script_list.py` | Script list widget | Sort favorites first, star display |
| `src/scriptpilot/widgets/main_panel.py` | Detail/output panel | Show last run info |
| `src/scriptpilot/app.py` | App shell | Instantiate `HistoryStore`, pass to `MainScreen` |
| `scripts/build.sh` | Build script | New file: PyInstaller build |
| `.github/workflows/build.yml` | CI | New file: release binary workflow |
| `pyproject.toml` | Project config | Add `pyinstaller` dev dependency |

---

### Task 1: Add `favorite` field to Script model and `RunRecord` model

**Files:**
- Modify: `src/scriptpilot/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write tests for `favorite` field and `RunRecord`**

Add to `tests/test_models.py`:

```python
class TestScriptFavorite:
    def test_default_not_favorite(self):
        s = Script(name="x", description="x", type="bash", content="x")
        assert s.favorite is False

    def test_set_favorite(self):
        s = Script(name="x", description="x", type="bash", content="x", favorite=True)
        assert s.favorite is True

    def test_roundtrip_with_favorite(self):
        s = Script(name="x", description="x", type="bash", content="x", favorite=True)
        data = s.model_dump()
        s2 = Script(**data)
        assert s2.favorite is True

    def test_backward_compat_no_favorite_field(self):
        """Existing scripts without favorite field should load as False."""
        data = {"name": "x", "description": "x", "type": "bash", "content": "x", "id": "abc"}
        s = Script(**data)
        assert s.favorite is False


from scriptpilot.models import RunRecord


class TestRunRecord:
    def test_create_run_record(self):
        r = RunRecord(
            script_id="abc",
            script_name="my script",
            timestamp="2026-04-15T10:30:00",
            exit_code=0,
            timed_out=False,
            duration=1.5,
            output="hello world\n",
        )
        assert r.script_id == "abc"
        assert r.script_name == "my script"
        assert r.exit_code == 0
        assert r.output == "hello world\n"

    def test_run_record_serialization_roundtrip(self):
        r = RunRecord(
            script_id="abc",
            script_name="test",
            timestamp="2026-04-15T10:30:00",
            exit_code=1,
            timed_out=True,
            duration=60.0,
            output="timeout\n",
        )
        data = r.model_dump()
        r2 = RunRecord(**data)
        assert r2.exit_code == 1
        assert r2.timed_out is True
        assert r2.output == "timeout\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/kc/repos/script-pilot && uv run pytest tests/test_models.py -v -k "TestScriptFavorite or TestRunRecord"`

Expected: FAIL — `favorite` field not on `Script`, `RunRecord` not defined.

- [ ] **Step 3: Implement model changes**

In `src/scriptpilot/models.py`, add `favorite` field to `Script` and add `RunRecord` class:

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

    def model_post_init(self, __context):
        if not self.id:
            self.id = str(uuid.uuid4())


class RunRecord(BaseModel):
    """A single script execution record."""

    script_id: str
    script_name: str
    timestamp: str
    exit_code: int
    timed_out: bool
    duration: float
    output: str
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/kc/repos/script-pilot && uv run pytest tests/test_models.py -v`

Expected: ALL PASS (including existing tests — `favorite` default ensures backward compat).

- [ ] **Step 5: Commit**

```bash
cd /home/kc/repos/script-pilot
git add src/scriptpilot/models.py tests/test_models.py
git commit -m "feat: add favorite field to Script and RunRecord model"
```

---

### Task 2: Structured LLM response parser and `GenerationResult`

**Files:**
- Modify: `src/scriptpilot/openrouter.py`
- Test: `tests/test_openrouter.py`

- [ ] **Step 1: Write tests for `parse_generation_response`**

Add to `tests/test_openrouter.py`:

```python
from scriptpilot.openrouter import (
    GenerationResult,
    MalformedResponseError,
    parse_generation_response,
)
from scriptpilot.models import ScriptArg


class TestParseGenerationResponse:
    def test_parse_valid_response(self):
        text = (
            '```bash\necho "hello $1"\n```\n\n'
            '```json\n{"args": [{"name": "greeting", "type": "string", "required": true, "default": ""}]}\n```'
        )
        result = parse_generation_response(text)
        assert isinstance(result, GenerationResult)
        assert 'echo "hello $1"' in result.code
        assert len(result.args) == 1
        assert result.args[0].name == "greeting"
        assert result.args[0].type == "string"

    def test_parse_python_code_block(self):
        text = (
            '```python\nprint("hi")\n```\n\n'
            '```json\n{"args": []}\n```'
        )
        result = parse_generation_response(text)
        assert 'print("hi")' in result.code
        assert result.args == []

    def test_parse_javascript_code_block(self):
        text = (
            '```javascript\nconsole.log("hi")\n```\n\n'
            '```json\n{"args": []}\n```'
        )
        result = parse_generation_response(text)
        assert 'console.log("hi")' in result.code

    def test_parse_empty_args(self):
        text = '```bash\necho hi\n```\n\n```json\n{"args": []}\n```'
        result = parse_generation_response(text)
        assert result.args == []

    def test_parse_multiple_args(self):
        text = (
            '```bash\necho "$1 $2"\n```\n\n'
            '```json\n{"args": ['
            '{"name": "input", "type": "string", "required": true, "default": ""},'
            '{"name": "verbose", "type": "boolean", "required": false, "default": false}'
            ']}\n```'
        )
        result = parse_generation_response(text)
        assert len(result.args) == 2
        assert result.args[0].name == "input"
        assert result.args[1].name == "verbose"
        assert result.args[1].type == "boolean"

    def test_malformed_no_code_block(self):
        text = 'echo "hello"\n\n```json\n{"args": []}\n```'
        with pytest.raises(MalformedResponseError):
            parse_generation_response(text)

    def test_malformed_no_json_block(self):
        text = '```bash\necho hi\n```\n\nno json here'
        with pytest.raises(MalformedResponseError):
            parse_generation_response(text)

    def test_malformed_invalid_json(self):
        text = '```bash\necho hi\n```\n\n```json\n{invalid json}\n```'
        with pytest.raises(MalformedResponseError):
            parse_generation_response(text)

    def test_malformed_missing_args_key(self):
        text = '```bash\necho hi\n```\n\n```json\n{"params": []}\n```'
        with pytest.raises(MalformedResponseError):
            parse_generation_response(text)

    def test_malformed_invalid_arg_type(self):
        text = (
            '```bash\necho hi\n```\n\n'
            '```json\n{"args": [{"name": "x", "type": "float", "required": true, "default": null}]}\n```'
        )
        with pytest.raises(MalformedResponseError):
            parse_generation_response(text)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/kc/repos/script-pilot && uv run pytest tests/test_openrouter.py::TestParseGenerationResponse -v`

Expected: FAIL — `GenerationResult`, `MalformedResponseError`, `parse_generation_response` not defined.

- [ ] **Step 3: Implement parser**

In `src/scriptpilot/openrouter.py`, add after the existing imports and before `OpenRouterClient`:

```python
import json as _json
from dataclasses import dataclass

from scriptpilot.models import ScriptArg


class MalformedResponseError(Exception):
    """Raised when the LLM response does not match the expected format."""


@dataclass
class GenerationResult:
    """Parsed LLM response containing code and argument definitions."""
    code: str
    args: list[ScriptArg]


def parse_generation_response(text: str) -> GenerationResult:
    """Parse an LLM response into code and argument definitions.

    Expects two fenced blocks: a code block and a JSON block with an "args" key.
    """
    # Find all fenced code blocks: ```lang\n...\n```
    blocks = re.findall(r"```(\w*)\n(.*?)```", text, re.DOTALL)
    if not blocks:
        raise MalformedResponseError("No fenced code blocks found")

    code = None
    args_data = None

    for lang, content in blocks:
        if lang == "json":
            try:
                parsed = _json.loads(content.strip())
                if isinstance(parsed, dict) and "args" in parsed:
                    args_data = parsed["args"]
            except _json.JSONDecodeError:
                raise MalformedResponseError("Invalid JSON in args block")
        elif code is None:
            # First non-json code block is the script
            code = content.strip()

    if code is None:
        raise MalformedResponseError("No code block found")
    if args_data is None:
        raise MalformedResponseError("No JSON block with 'args' key found")

    try:
        args = [ScriptArg(**a) for a in args_data]
    except Exception as e:
        raise MalformedResponseError(f"Invalid arg definition: {e}") from e

    return GenerationResult(code=code, args=args)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/kc/repos/script-pilot && uv run pytest tests/test_openrouter.py -v`

Expected: ALL PASS (new and existing tests).

- [ ] **Step 5: Commit**

```bash
cd /home/kc/repos/script-pilot
git add src/scriptpilot/openrouter.py tests/test_openrouter.py
git commit -m "feat: add structured LLM response parser and GenerationResult"
```

---

### Task 3: Update `generate_script` with structured format and retry

**Files:**
- Modify: `src/scriptpilot/openrouter.py`
- Test: `tests/test_openrouter.py`

- [ ] **Step 1: Write tests for updated `generate_script`**

Update `TestOpenRouterClient` in `tests/test_openrouter.py`. The existing tests need updating since `generate_script` now returns `GenerationResult` instead of `str`. Replace the relevant tests:

```python
class TestOpenRouterClient:
    @pytest.fixture
    def client(self):
        return OpenRouterClient(api_key="test-key")

    @respx.mock
    @pytest.mark.asyncio
    async def test_generate_script_returns_generation_result(self, client):
        respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": '```bash\necho "generated"\n```\n\n```json\n{"args": []}\n```'}}
                    ]
                },
            )
        )
        result = await client.generate_script(
            description="echo something",
            language="bash",
            model="openai/gpt-4o",
        )
        assert isinstance(result, GenerationResult)
        assert result.code == 'echo "generated"'
        assert result.args == []

    @respx.mock
    @pytest.mark.asyncio
    async def test_generate_script_with_args(self, client):
        respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": (
                            '```bash\necho "$1"\n```\n\n'
                            '```json\n{"args": [{"name": "msg", "type": "string", "required": true, "default": ""}]}\n```'
                        )}}
                    ]
                },
            )
        )
        result = await client.generate_script(
            description="echo a message",
            language="bash",
            model="openai/gpt-4o",
        )
        assert len(result.args) == 1
        assert result.args[0].name == "msg"

    @respx.mock
    @pytest.mark.asyncio
    async def test_generate_retries_on_malformed(self, client):
        route = respx.post("https://openrouter.ai/api/v1/chat/completions")
        route.side_effect = [
            httpx.Response(200, json={"choices": [{"message": {"content": "no fences here"}}]}),
            httpx.Response(200, json={"choices": [{"message": {"content": '```bash\necho ok\n```\n\n```json\n{"args": []}\n```'}}]}),
        ]
        result = await client.generate_script("test", "bash", "openai/gpt-4o")
        assert result.code == "echo ok"
        assert route.call_count == 2

    @respx.mock
    @pytest.mark.asyncio
    async def test_generate_raises_after_3_retries(self, client):
        respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={"choices": [{"message": {"content": "bad response"}}]},
            )
        )
        with pytest.raises(MalformedResponseError):
            await client.generate_script("test", "bash", "openai/gpt-4o")

    @respx.mock
    @pytest.mark.asyncio
    async def test_auth_error(self, client):
        respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
            return_value=httpx.Response(401, json={"error": "invalid key"})
        )
        with pytest.raises(AuthenticationError):
            await client.generate_script("x", "bash", "openai/gpt-4o")

    @respx.mock
    @pytest.mark.asyncio
    async def test_rate_limit_error(self, client):
        respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
            return_value=httpx.Response(429, json={"error": "rate limited"})
        )
        with pytest.raises(RateLimitError):
            await client.generate_script("x", "bash", "openai/gpt-4o")

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_models(self, client):
        respx.get("https://openrouter.ai/api/v1/models").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "openai/gpt-4o", "name": "GPT-4o"},
                        {"id": "anthropic/claude-3.5-sonnet", "name": "Claude 3.5"},
                    ]
                },
            )
        )
        models = await client.list_models()
        assert len(models) == 2
        assert models[0]["id"] == "openai/gpt-4o"

    @respx.mock
    @pytest.mark.asyncio
    async def test_server_error(self, client):
        respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
            return_value=httpx.Response(500, json={"error": "server error"})
        )
        with pytest.raises(OpenRouterConnectionError):
            await client.generate_script("x", "bash", "openai/gpt-4o")

    @respx.mock
    @pytest.mark.asyncio
    async def test_network_error(self, client):
        respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        with pytest.raises(OpenRouterConnectionError):
            await client.generate_script("x", "bash", "openai/gpt-4o")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/kc/repos/script-pilot && uv run pytest tests/test_openrouter.py::TestOpenRouterClient -v`

Expected: FAIL — `generate_script` still returns `str`, no retry logic.

- [ ] **Step 3: Implement updated `generate_script`**

Replace `SYSTEM_PROMPT` and `generate_script` method in `src/scriptpilot/openrouter.py`:

```python
GENERATE_SYSTEM_PROMPT = (
    "You are a script generator. You MUST output exactly two fenced blocks:\n\n"
    "1. A code block with the script (use ```bash, ```python, or ```javascript as the fence label)\n"
    "2. A JSON block with argument definitions\n\n"
    "The code must be complete, valid, and ready to run. Include brief comments where helpful.\n\n"
    "The JSON block must have this exact format:\n"
    '```json\n{"args": [{"name": "arg_name", "type": "string|integer|boolean", "required": true|false, "default": "value"}]}\n```\n\n'
    "Use an empty args array if the script takes no arguments.\n"
    "Do NOT include any text outside these two blocks."
)
```

Update `generate_script` method:

```python
    async def generate_script(
        self, description: str, language: str, model: str
    ) -> GenerationResult:
        """Generate a script from a natural language description."""
        messages = [
            {"role": "system", "content": GENERATE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Write a {language} script that does the following:\n\n"
                    f"{description}"
                ),
            },
        ]
        return await self._call_with_retry(messages, model)

    async def _call_with_retry(
        self, messages: list[dict], model: str, max_retries: int = 3
    ) -> GenerationResult:
        """Call the API and parse response, retrying on malformed output."""
        last_error = None
        for _ in range(max_retries):
            content = await self._chat(messages, model)
            try:
                return parse_generation_response(content)
            except MalformedResponseError as e:
                last_error = e
                continue
        raise last_error

    async def _chat(self, messages: list[dict], model: str) -> str:
        """Make a chat completion request and return the content string."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"model": model, "messages": messages},
                    timeout=60,
                )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise OpenRouterConnectionError(f"Could not reach OpenRouter: {e}") from e

        if response.status_code == 401:
            raise AuthenticationError("Invalid API key")
        if response.status_code == 429:
            raise RateLimitError("Rate limited by OpenRouter")
        if response.status_code >= 500:
            raise OpenRouterConnectionError("OpenRouter server error")
        response.raise_for_status()

        return response.json()["choices"][0]["message"]["content"]
```

Remove the old `SYSTEM_PROMPT` constant and the old body of `generate_script`. Keep `strip_markdown_fences` (it's still tested and costs nothing to keep).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/kc/repos/script-pilot && uv run pytest tests/test_openrouter.py -v`

Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/kc/repos/script-pilot
git add src/scriptpilot/openrouter.py tests/test_openrouter.py
git commit -m "feat: update generate_script to return GenerationResult with retry"
```

---

### Task 4: Add `modify_script` method to `OpenRouterClient`

**Files:**
- Modify: `src/scriptpilot/openrouter.py`
- Test: `tests/test_openrouter.py`

- [ ] **Step 1: Write tests for `modify_script`**

Add to `tests/test_openrouter.py`:

```python
class TestModifyScript:
    @pytest.fixture
    def client(self):
        return OpenRouterClient(api_key="test-key")

    @respx.mock
    @pytest.mark.asyncio
    async def test_modify_script_returns_generation_result(self, client):
        respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": (
                            '```bash\necho "modified"\n```\n\n'
                            '```json\n{"args": []}\n```'
                        )}}
                    ]
                },
            )
        )
        result = await client.modify_script(
            current_code='echo "original"',
            instruction="change to say modified",
            language="bash",
            model="openai/gpt-4o",
        )
        assert isinstance(result, GenerationResult)
        assert result.code == 'echo "modified"'

    @respx.mock
    @pytest.mark.asyncio
    async def test_modify_script_retries_on_malformed(self, client):
        route = respx.post("https://openrouter.ai/api/v1/chat/completions")
        route.side_effect = [
            httpx.Response(200, json={"choices": [{"message": {"content": "plain text"}}]}),
            httpx.Response(200, json={"choices": [{"message": {"content": '```bash\necho ok\n```\n\n```json\n{"args": []}\n```'}}]}),
        ]
        result = await client.modify_script('echo "old"', "fix it", "bash", "openai/gpt-4o")
        assert result.code == "echo ok"
        assert route.call_count == 2

    @respx.mock
    @pytest.mark.asyncio
    async def test_modify_script_preserves_args(self, client):
        respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": (
                            '```python\nimport sys\nprint(sys.argv[1])\n```\n\n'
                            '```json\n{"args": [{"name": "input_file", "type": "string", "required": true, "default": ""}]}\n```'
                        )}}
                    ]
                },
            )
        )
        result = await client.modify_script(
            current_code='print("hello")',
            instruction="read from a file argument",
            language="python",
            model="openai/gpt-4o",
        )
        assert len(result.args) == 1
        assert result.args[0].name == "input_file"

    @respx.mock
    @pytest.mark.asyncio
    async def test_modify_auth_error(self, client):
        respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
            return_value=httpx.Response(401, json={"error": "invalid key"})
        )
        with pytest.raises(AuthenticationError):
            await client.modify_script("x", "y", "bash", "openai/gpt-4o")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/kc/repos/script-pilot && uv run pytest tests/test_openrouter.py::TestModifyScript -v`

Expected: FAIL — `modify_script` method does not exist.

- [ ] **Step 3: Implement `modify_script`**

Add to `OpenRouterClient` class in `src/scriptpilot/openrouter.py`:

```python
MODIFY_SYSTEM_PROMPT = (
    "You are a script modifier. You will receive an existing script and an instruction "
    "describing what to change. Output the COMPLETE updated script (not a diff). "
    "You MUST output exactly two fenced blocks:\n\n"
    "1. A code block with the full updated script (use ```bash, ```python, or ```javascript)\n"
    "2. A JSON block with argument definitions for the updated script\n\n"
    "The JSON block must have this exact format:\n"
    '```json\n{"args": [{"name": "arg_name", "type": "string|integer|boolean", "required": true|false, "default": "value"}]}\n```\n\n'
    "Use an empty args array if the script takes no arguments.\n"
    "Do NOT include any text outside these two blocks."
)
```

```python
    async def modify_script(
        self,
        current_code: str,
        instruction: str,
        language: str,
        model: str,
    ) -> GenerationResult:
        """Modify an existing script based on a natural language instruction."""
        messages = [
            {"role": "system", "content": MODIFY_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Here is the current {language} script:\n\n"
                    f"```{language}\n{current_code}\n```\n\n"
                    f"Modification instruction: {instruction}"
                ),
            },
        ]
        return await self._call_with_retry(messages, model)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/kc/repos/script-pilot && uv run pytest tests/test_openrouter.py -v`

Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/kc/repos/script-pilot
git add src/scriptpilot/openrouter.py tests/test_openrouter.py
git commit -m "feat: add modify_script method to OpenRouterClient"
```

---

### Task 5: Update `GenerateScreen` for auto-args

**Files:**
- Modify: `src/scriptpilot/screens/generate.py`

- [ ] **Step 1: Update imports and state**

In `src/scriptpilot/screens/generate.py`, update imports:

```python
from scriptpilot.openrouter import (
    OpenRouterClient,
    AuthenticationError,
    GenerationResult,
    RateLimitError,
)
```

Add instance variable in `__init__`:

```python
    def __init__(self, default_model: str = "openai/gpt-4o"):
        super().__init__()
        self._model = default_model
        self._generated = False
        self._result: GenerationResult | None = None
```

- [ ] **Step 2: Update worker result handling**

In `on_worker_state_changed`, update the `SUCCESS` branch to handle `GenerationResult`:

```python
        if event.state == WorkerState.SUCCESS:
            self._result = event.worker.result
            result_area = self.query_one("#result-area", TextArea)
            result_area.read_only = False
            result_area.load_text(self._result.code)
            self.query_one("#save-fields").display = True
            self.query_one("#save-btn", Button).disabled = False
            self.query_one("#retry-btn", Button).disabled = False
            self.query_one("#generate-btn", Button).disabled = False
            self._generated = True
```

- [ ] **Step 3: Update `_do_save` to include auto-extracted args**

```python
    def _do_save(self):
        name = self.query_one("#save-name", Input).value.strip()
        if not name:
            self.notify("Script name is required", severity="error")
            return
        desc = self.query_one("#save-desc", Input).value.strip()
        content = self.query_one("#result-area", TextArea).text
        language = self.query_one("#lang-select", Select).value

        script = Script(
            name=name,
            description=desc,
            type=language,
            content=content,
            args=self._result.args if self._result else [],
        )
        self.dismiss(script)
```

- [ ] **Step 4: Run all tests to verify no regressions**

Run: `cd /home/kc/repos/script-pilot && uv run pytest -v`

Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/kc/repos/script-pilot
git add src/scriptpilot/screens/generate.py
git commit -m "feat: auto-populate script args from LLM generation result"
```

---

### Task 6: Create `PromptScreen` for modifying scripts via LLM

**Files:**
- Create: `src/scriptpilot/screens/prompt.py`

- [ ] **Step 1: Create `PromptScreen`**

Create `src/scriptpilot/screens/prompt.py`:

```python
from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label, TextArea
from textual.worker import Worker, WorkerState

from scriptpilot.models import Script
from scriptpilot.openrouter import (
    AuthenticationError,
    GenerationResult,
    OpenRouterClient,
    RateLimitError,
)

TEXTUAL_LANGUAGES = {"bash": "bash", "python": "python", "js": "javascript"}


class PromptScreen(ModalScreen[Script | None]):
    """Modal screen for modifying a script via LLM prompt."""

    DEFAULT_CSS = """
    PromptScreen {
        align: center middle;
    }
    PromptScreen #prompt-container {
        width: 80%;
        max-width: 100;
        height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    PromptScreen #instruction-area {
        height: 6;
        margin-bottom: 1;
    }
    PromptScreen #preview-area {
        height: 1fr;
        margin-bottom: 1;
    }
    PromptScreen #button-bar {
        height: 3;
        align: right middle;
        dock: bottom;
    }
    PromptScreen #button-bar Button {
        margin-left: 1;
    }
    """

    def __init__(self, script: Script, default_model: str = "openai/gpt-4o"):
        super().__init__()
        self._script = script
        self._model = default_model
        self._result: GenerationResult | None = None

    def compose(self) -> ComposeResult:
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        lang = TEXTUAL_LANGUAGES.get(self._script.type, "bash")
        with Vertical(id="prompt-container"):
            yield Label(f"[bold]Modify: {self._script.name}[/bold]")
            if not api_key:
                yield Label(
                    "[red]Set OPENROUTER_API_KEY environment variable.[/red]",
                    id="no-key-warning",
                )
            yield Label("What should be changed?")
            yield TextArea(id="instruction-area", language=None)
            yield Label("Preview:")
            yield TextArea(
                self._script.content,
                id="preview-area",
                language=lang,
                read_only=True,
            )
            with Horizontal(id="button-bar"):
                yield Button("Cancel", id="cancel-btn")
                yield Button(
                    "Submit",
                    id="submit-btn",
                    variant="primary",
                    disabled=not bool(api_key),
                )
                yield Button("Accept", id="accept-btn", variant="success", disabled=True)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "submit-btn":
            self._do_modify()
        elif event.button.id == "accept-btn":
            self._do_accept()

    def _do_modify(self):
        instruction = self.query_one("#instruction-area", TextArea).text.strip()
        if not instruction:
            self.notify("Please describe what to change", severity="error")
            return

        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self.query_one("#submit-btn", Button).disabled = True
        self.notify("Modifying script...")

        self.run_worker(
            self._modify(api_key, instruction),
            name="modify",
        )

    async def _modify(self, api_key: str, instruction: str):
        client = OpenRouterClient(api_key=api_key)
        return await client.modify_script(
            current_code=self._script.content,
            instruction=instruction,
            language=self._script.type,
            model=self._model,
        )

    def on_worker_state_changed(self, event: Worker.StateChanged):
        if event.worker.name != "modify":
            return
        if event.state == WorkerState.SUCCESS:
            self._result = event.worker.result
            preview = self.query_one("#preview-area", TextArea)
            preview.load_text(self._result.code)
            self.query_one("#accept-btn", Button).disabled = False
            self.query_one("#submit-btn", Button).disabled = False
        elif event.state == WorkerState.ERROR:
            error = event.worker.error
            if isinstance(error, AuthenticationError):
                self.notify("Invalid API key", severity="error")
            elif isinstance(error, RateLimitError):
                self.notify("Rate limited, try again later", severity="error")
            else:
                self.notify(f"Error: {error}", severity="error")
            self.query_one("#submit-btn", Button).disabled = False

    def _do_accept(self):
        if not self._result:
            return
        updated = Script(
            id=self._script.id,
            name=self._script.name,
            description=self._script.description,
            type=self._script.type,
            content=self._result.code,
            args=self._result.args,
            timeout=self._script.timeout,
            favorite=self._script.favorite,
        )
        self.dismiss(updated)
```

- [ ] **Step 2: Run all tests to verify no regressions**

Run: `cd /home/kc/repos/script-pilot && uv run pytest -v`

Expected: ALL PASS.

- [ ] **Step 3: Commit**

```bash
cd /home/kc/repos/script-pilot
git add src/scriptpilot/screens/prompt.py
git commit -m "feat: add PromptScreen for LLM-based script modification"
```

---

### Task 7: Wire up `p`, `c`, `f` keybindings in `MainScreen`

**Files:**
- Modify: `src/scriptpilot/screens/main.py`

- [ ] **Step 1: Add imports**

Add to the imports in `src/scriptpilot/screens/main.py`:

```python
from scriptpilot.screens.prompt import PromptScreen
```

- [ ] **Step 2: Add keybindings**

Update `MainScreen.BINDINGS`:

```python
    BINDINGS = [
        ("n", "new_script", "New"),
        ("e", "edit_script", "Edit"),
        ("d", "delete_script", "Delete"),
        ("r", "run_script", "Run"),
        ("p", "prompt_script", "Prompt"),
        ("c", "clone_script", "Clone"),
        ("f", "toggle_favorite", "Fav"),
    ]
```

- [ ] **Step 3: Add `action_prompt_script`**

Add method to `MainScreen`:

```python
    def action_prompt_script(self):
        if not self._selected_script:
            self.notify("No script selected", severity="warning")
            return

        script = self._selected_script

        def on_result(updated: Script | None):
            if updated:
                self._store.update(updated)
                self._selected_script = updated
                self._refresh_list()
                self.query_one(MainPanel).show_script_details(updated)

        self.app.push_screen(
            PromptScreen(script, default_model=self.app._config.default_model),
            callback=on_result,
        )
```

- [ ] **Step 4: Add `action_clone_script`**

Add method to `MainScreen`:

```python
    def action_clone_script(self):
        if not self._selected_script:
            self.notify("No script selected", severity="warning")
            return

        original = self._selected_script
        clone = Script(
            name=f"{original.name} (copy)",
            description=original.description,
            type=original.type,
            content=original.content,
            args=[ScriptArg(**a.model_dump()) for a in original.args],
            timeout=original.timeout,
            favorite=False,
        )
        self._store.add(clone)
        self._refresh_list()
        self.notify(f"Cloned '{original.name}'")
```

Add `ScriptArg` to the imports from `scriptpilot.models`:

```python
from scriptpilot.models import Script, ScriptArg
```

- [ ] **Step 5: Add `action_toggle_favorite`**

Add method to `MainScreen`:

```python
    def action_toggle_favorite(self):
        if not self._selected_script:
            self.notify("No script selected", severity="warning")
            return

        script = self._selected_script
        updated = Script(
            id=script.id,
            name=script.name,
            description=script.description,
            type=script.type,
            content=script.content,
            args=script.args,
            timeout=script.timeout,
            favorite=not script.favorite,
        )
        self._store.update(updated)
        self._selected_script = updated
        self._refresh_list()
        self.query_one(MainPanel).show_script_details(updated)
        label = "Favorited" if updated.favorite else "Unfavorited"
        self.notify(f"{label} '{updated.name}'")
```

- [ ] **Step 6: Run all tests to verify no regressions**

Run: `cd /home/kc/repos/script-pilot && uv run pytest -v`

Expected: ALL PASS.

- [ ] **Step 7: Commit**

```bash
cd /home/kc/repos/script-pilot
git add src/scriptpilot/screens/main.py
git commit -m "feat: add prompt, clone, and favorite keybindings to MainScreen"
```

---

### Task 8: Favorites display and sorting in `ScriptList`

**Files:**
- Modify: `src/scriptpilot/widgets/script_list.py`

- [ ] **Step 1: Update `compose` to sort and show stars**

In `src/scriptpilot/widgets/script_list.py`, update `compose`:

```python
    def compose(self) -> ComposeResult:
        sorted_scripts = self._sorted(self._scripts)
        with ListView():
            for script in sorted_scripts:
                label = self._make_label(script)
                yield ListItem(Label(label), name=script.id)
```

- [ ] **Step 2: Add helper methods**

Add to `ScriptList`:

```python
    @staticmethod
    def _sorted(scripts: list[Script]) -> list[Script]:
        """Sort favorites first, preserve insertion order within groups."""
        favorites = [s for s in scripts if s.favorite]
        others = [s for s in scripts if not s.favorite]
        return favorites + others

    @staticmethod
    def _make_label(script: Script) -> str:
        star = " *" if script.favorite else ""
        return f"[{TYPE_LABELS.get(script.type, '??')}]{star} {script.name}"
```

- [ ] **Step 3: Update `update_scripts` to use the same logic**

```python
    def update_scripts(self, scripts: list[Script]):
        """Refresh the list with new script data."""
        self._scripts = scripts
        sorted_scripts = self._sorted(scripts)
        lv = self.query_one(ListView)
        lv.clear()
        for script in sorted_scripts:
            label = self._make_label(script)
            lv.append(ListItem(Label(label), name=script.id))
```

- [ ] **Step 4: Run all tests to verify no regressions**

Run: `cd /home/kc/repos/script-pilot && uv run pytest -v`

Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/kc/repos/script-pilot
git add src/scriptpilot/widgets/script_list.py
git commit -m "feat: sort favorites to top and show star in script list"
```

---

### Task 9: `HistoryStore` for run history

**Files:**
- Create: `src/scriptpilot/history.py`
- Test: `tests/test_history.py`

- [ ] **Step 1: Write tests for `HistoryStore`**

Create `tests/test_history.py`:

```python
import json
import pytest
from pathlib import Path

from scriptpilot.models import RunRecord
from scriptpilot.history import HistoryStore


@pytest.fixture
def store(tmp_path):
    return HistoryStore(tmp_path / "history.json")


@pytest.fixture
def sample_record():
    return RunRecord(
        script_id="abc",
        script_name="test script",
        timestamp="2026-04-15T10:30:00",
        exit_code=0,
        timed_out=False,
        duration=1.5,
        output="hello world\n",
    )


class TestHistoryStore:
    def test_list_all_empty(self, store):
        assert store.list_all() == []

    def test_add_and_list_all(self, store, sample_record):
        store.add(sample_record)
        records = store.list_all()
        assert len(records) == 1
        assert records[0].script_id == "abc"
        assert records[0].output == "hello world\n"

    def test_list_all_newest_first(self, store):
        r1 = RunRecord(
            script_id="a", script_name="a",
            timestamp="2026-04-15T10:00:00",
            exit_code=0, timed_out=False, duration=1.0, output="first\n",
        )
        r2 = RunRecord(
            script_id="a", script_name="a",
            timestamp="2026-04-15T11:00:00",
            exit_code=0, timed_out=False, duration=1.0, output="second\n",
        )
        store.add(r1)
        store.add(r2)
        records = store.list_all()
        assert records[0].timestamp == "2026-04-15T11:00:00"
        assert records[1].timestamp == "2026-04-15T10:00:00"

    def test_list_for_script(self, store):
        r1 = RunRecord(
            script_id="a", script_name="script a",
            timestamp="2026-04-15T10:00:00",
            exit_code=0, timed_out=False, duration=1.0, output="a\n",
        )
        r2 = RunRecord(
            script_id="b", script_name="script b",
            timestamp="2026-04-15T10:00:00",
            exit_code=0, timed_out=False, duration=1.0, output="b\n",
        )
        store.add(r1)
        store.add(r2)
        records = store.list_for_script("a")
        assert len(records) == 1
        assert records[0].script_name == "script a"

    def test_persists_to_disk(self, store, sample_record):
        store.add(sample_record)
        store2 = HistoryStore(store._path)
        assert len(store2.list_all()) == 1
        assert store2.list_all()[0].output == "hello world\n"

    def test_evicts_oldest_at_cap(self, store):
        for i in range(105):
            r = RunRecord(
                script_id="x", script_name="x",
                timestamp=f"2026-04-15T{i:05d}",
                exit_code=0, timed_out=False, duration=1.0,
                output=f"run {i}\n",
            )
            store.add(r)
        records = store.list_all()
        assert len(records) == 100
        # Oldest runs (0-4) should have been evicted
        timestamps = [r.timestamp for r in records]
        assert "2026-04-15T00000" not in timestamps
        assert "2026-04-15T00104" in timestamps

    def test_creates_parent_directory(self, tmp_path):
        path = tmp_path / "subdir" / "history.json"
        store = HistoryStore(path)
        r = RunRecord(
            script_id="x", script_name="x",
            timestamp="2026-04-15T10:00:00",
            exit_code=0, timed_out=False, duration=1.0, output="x\n",
        )
        store.add(r)
        assert path.exists()

    def test_corrupted_json_backs_up_and_resets(self, tmp_path):
        path = tmp_path / "history.json"
        path.write_text("{invalid json!!!")
        store = HistoryStore(path)
        assert store.list_all() == []
        assert (tmp_path / "history.json.bak").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/kc/repos/script-pilot && uv run pytest tests/test_history.py -v`

Expected: FAIL — `scriptpilot.history` module does not exist.

- [ ] **Step 3: Implement `HistoryStore`**

Create `src/scriptpilot/history.py`:

```python
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scriptpilot.models import RunRecord

MAX_RECORDS = 100


class HistoryStore:
    """JSON-based run history persistence."""

    def __init__(self, path: Path | None = None):
        self._path = path or Path.home() / ".scriptpilot" / "history.json"
        self._records: list[RunRecord] = []
        self._load()

    def _load(self):
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            for item in data.get("records", []):
                self._records.append(RunRecord(**item))
        except (json.JSONDecodeError, Exception):
            backup = self._path.with_suffix(".json.bak")
            self._path.rename(backup)

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"records": [r.model_dump() for r in self._records]}
        fd, tmp = tempfile.mkstemp(
            dir=self._path.parent, suffix=".tmp"
        )
        try:
            with open(fd, "w") as f:
                json.dump(data, f, indent=2)
            Path(tmp).replace(self._path)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise

    def add(self, record: RunRecord):
        """Append a run record, evicting oldest if over cap."""
        self._records.append(record)
        if len(self._records) > MAX_RECORDS:
            self._records = self._records[-MAX_RECORDS:]
        self._save()

    def list_all(self) -> list[RunRecord]:
        """Return all records, newest first."""
        return list(reversed(self._records))

    def list_for_script(self, script_id: str) -> list[RunRecord]:
        """Return records for a specific script, newest first."""
        return [
            r for r in reversed(self._records)
            if r.script_id == script_id
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/kc/repos/script-pilot && uv run pytest tests/test_history.py -v`

Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/kc/repos/script-pilot
git add src/scriptpilot/history.py tests/test_history.py
git commit -m "feat: add HistoryStore for persisting script run history"
```

---

### Task 10: Integrate run history into execution flow and detail panel

**Files:**
- Modify: `src/scriptpilot/app.py`
- Modify: `src/scriptpilot/screens/main.py`
- Modify: `src/scriptpilot/widgets/main_panel.py`

- [ ] **Step 1: Add `HistoryStore` to `ScriptPilotApp`**

In `src/scriptpilot/app.py`, add import:

```python
from scriptpilot.history import HistoryStore
```

Update `__init__`:

```python
    def __init__(self):
        super().__init__()
        self._store = ScriptStore()
        self._history = HistoryStore()
        self._config = self._load_config()
```

Update `on_mount` to pass history:

```python
    def on_mount(self):
        self.push_screen(MainScreen(self._store, self._history))
```

- [ ] **Step 2: Update `MainScreen` constructor to accept `HistoryStore`**

In `src/scriptpilot/screens/main.py`, add import:

```python
from scriptpilot.history import HistoryStore
```

Update `__init__`:

```python
    def __init__(self, store: ScriptStore, history: HistoryStore):
        super().__init__()
        self._store = store
        self._history = history
        self._selected_script: Script | None = None
```

- [ ] **Step 3: Add output collection and history recording to `_execute`**

Update `_execute` in `MainScreen`:

```python
    def _execute(self, script: Script, arg_values: list[str] | None = None):
        panel = self.query_one(MainPanel)
        panel.show_running(script)

        async def run():
            output_lines: list[str] = []

            def collect_output(line: str):
                output_lines.append(line)
                panel.append_output(line)

            try:
                result = await execute_script(
                    script,
                    arg_values=arg_values,
                    on_output=collect_output,
                )
                panel.show_finished(result.exit_code, result.duration, result.timed_out)

                from datetime import datetime, timezone
                record = RunRecord(
                    script_id=script.id,
                    script_name=script.name,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    exit_code=result.exit_code,
                    timed_out=result.timed_out,
                    duration=result.duration,
                    output="\n".join(output_lines),
                )
                self._history.add(record)
            except InterpreterNotFoundError as e:
                panel.show_error(str(e))
                self.notify(str(e), severity="error")
            except Exception as e:
                panel.show_error(f"Error: {e}")
                self.notify(str(e), severity="error")

        self.run_worker(run(), name="execute", exclusive=True)
```

Add `RunRecord` to the imports from `scriptpilot.models`:

```python
from scriptpilot.models import Script, ScriptArg, RunRecord
```

- [ ] **Step 4: Update `MainPanel` to show last run info**

In `src/scriptpilot/widgets/main_panel.py`, add import:

```python
from scriptpilot.models import Script, RunRecord
```

Update `show_script_details` to accept an optional last run:

```python
    def show_script_details(self, script: Script, last_run: RunRecord | None = None):
        """Display script metadata."""
        self.query_one("#welcome").display = False
        self.query_one("#output-log").display = False
        self.query_one("#status-bar").display = False

        details = self.query_one("#details", Static)
        args_text = ", ".join(a.name for a in script.args) if script.args else "none"
        text = (
            f"[bold]{script.name}[/bold]\n"
            f"{script.description}\n\n"
            f"Type: {script.type}  |  Timeout: {script.timeout}s  |  Args: {args_text}"
        )
        if last_run:
            text += (
                f"\n\n[dim]Last run: {last_run.timestamp}  |  "
                f"Exit: {last_run.exit_code}  |  "
                f"Duration: {last_run.duration:.1f}s[/dim]"
            )
        details.update(text)
        details.display = True
```

- [ ] **Step 5: Update `MainScreen` callers to pass last run**

In `src/scriptpilot/screens/main.py`, update `on_script_selected`:

```python
    def on_script_selected(self, event: ScriptSelected):
        self._selected_script = event.script
        last_run = self._get_last_run(event.script.id)
        self.query_one(MainPanel).show_script_details(event.script, last_run)
```

Add helper method:

```python
    def _get_last_run(self, script_id: str):
        runs = self._history.list_for_script(script_id)
        return runs[0] if runs else None
```

Update all other calls to `show_script_details` in `MainScreen` to also pass last run:

In `action_edit_script` callback:

```python
        def on_result(script: Script | None):
            if script:
                self._store.update(script)
                self._selected_script = script
                self._refresh_list()
                last_run = self._get_last_run(script.id)
                self.query_one(MainPanel).show_script_details(script, last_run)
```

In `action_prompt_script` callback:

```python
        def on_result(updated: Script | None):
            if updated:
                self._store.update(updated)
                self._selected_script = updated
                self._refresh_list()
                last_run = self._get_last_run(updated.id)
                self.query_one(MainPanel).show_script_details(updated, last_run)
```

In `action_toggle_favorite`:

```python
        last_run = self._get_last_run(updated.id)
        self.query_one(MainPanel).show_script_details(updated, last_run)
```

- [ ] **Step 6: Run all tests to verify no regressions**

Run: `cd /home/kc/repos/script-pilot && uv run pytest -v`

Expected: ALL PASS.

- [ ] **Step 7: Commit**

```bash
cd /home/kc/repos/script-pilot
git add src/scriptpilot/app.py src/scriptpilot/screens/main.py src/scriptpilot/widgets/main_panel.py
git commit -m "feat: integrate run history into execution flow and detail panel"
```

---

### Task 11: PyInstaller build script and CI workflow

**Files:**
- Create: `scripts/build.sh`
- Create: `.github/workflows/build.yml`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `pyinstaller` to dev dependencies**

In `pyproject.toml`, update the dev dependency group:

```toml
[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "respx>=0.22",
    "pyinstaller>=6.0",
]
```

- [ ] **Step 2: Create build script**

Create `scripts/build.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "Installing dependencies..."
uv sync --group dev

echo "Building binary..."
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
    src/scriptpilot/__main__.py

echo "Build complete: dist/scriptpilot"
ls -lh dist/scriptpilot
```

Make it executable:

```bash
chmod +x scripts/build.sh
```

- [ ] **Step 3: Create GitHub Actions workflow**

Create `.github/workflows/build.yml`:

```yaml
name: Build Binary

on:
  push:
    tags:
      - 'v*'

permissions:
  contents: write

jobs:
  build-linux:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Set up Python
        run: uv python install 3.12

      - name: Install dependencies
        run: uv sync --group dev

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
            src/scriptpilot/__main__.py

      - name: Upload release asset
        uses: softprops/action-gh-release@v2
        with:
          files: dist/scriptpilot
```

- [ ] **Step 4: Add build artifacts to `.gitignore`**

Create or append to `.gitignore`:

```
build/
dist/
*.spec
__pycache__/
```

- [ ] **Step 5: Run all tests to verify no regressions**

Run: `cd /home/kc/repos/script-pilot && uv run pytest -v`

Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/kc/repos/script-pilot
git add pyproject.toml scripts/build.sh .github/workflows/build.yml .gitignore
git commit -m "feat: add PyInstaller build script and GitHub Actions workflow"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Structured LLM response format — Task 2
- [x] `GenerationResult` dataclass — Task 2
- [x] Response parser with `MalformedResponseError` — Task 2
- [x] Retry logic (3 attempts) — Task 3
- [x] `generate_script` returns `GenerationResult` — Task 3
- [x] `modify_script` method — Task 4
- [x] `PromptScreen` modal — Task 6
- [x] `p` keybinding — Task 7
- [x] Auto-args in `GenerateScreen` — Task 5
- [x] Script cloning with `c` — Task 7
- [x] `favorite` field on `Script` — Task 1
- [x] `f` keybinding for toggle — Task 7
- [x] Favorites sorted first with star — Task 8
- [x] `RunRecord` model — Task 1
- [x] `HistoryStore` with 100-record cap — Task 9
- [x] Output collection in execution — Task 10
- [x] Last run display in detail panel — Task 10
- [x] `HistoryStore` initialized in app — Task 10
- [x] PyInstaller build script — Task 11
- [x] GitHub Actions workflow — Task 11
- [x] `pyinstaller` dev dependency — Task 11

**Placeholder scan:** No TBDs, TODOs, or incomplete sections found.

**Type consistency:**
- `GenerationResult` used consistently in Tasks 2-6
- `MalformedResponseError` used consistently in Tasks 2-4
- `RunRecord` used consistently in Tasks 1, 9, 10
- `HistoryStore` used consistently in Tasks 9, 10
- `ScriptArg` imports added where needed (Task 7)
- `favorite` field referenced consistently in Tasks 1, 7, 8
