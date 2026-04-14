import os
import pytest
import httpx
import respx
from scriptpilot.openrouter import (
    OpenRouterClient,
    AuthenticationError,
    OpenRouterConnectionError,
    RateLimitError,
    strip_markdown_fences,
)
from scriptpilot.openrouter import (
    GenerationResult,
    MalformedResponseError,
    parse_generation_response,
)
from scriptpilot.models import ScriptArg


class TestStripMarkdownFences:
    def test_no_fences(self):
        code = 'echo "hello"'
        assert strip_markdown_fences(code) == code

    def test_strip_backtick_fences(self):
        code = '```bash\necho "hello"\n```'
        assert strip_markdown_fences(code) == 'echo "hello"'

    def test_strip_fences_with_language(self):
        code = '```python\nprint("hi")\n```'
        assert strip_markdown_fences(code) == 'print("hi")'

    def test_strip_fences_no_language(self):
        code = '```\necho hi\n```'
        assert strip_markdown_fences(code) == "echo hi"


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
