import os
import pytest
import httpx
import respx
from scriptpilot.openrouter import (
    OpenRouterClient,
    AuthenticationError,
    RateLimitError,
    strip_markdown_fences,
)


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
    async def test_generate_script(self, client):
        respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": 'echo "generated"'}}
                    ]
                },
            )
        )
        result = await client.generate_script(
            description="echo something",
            language="bash",
            model="openai/gpt-4o",
        )
        assert result == 'echo "generated"'

    @respx.mock
    @pytest.mark.asyncio
    async def test_generate_strips_fences(self, client):
        respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": '```bash\necho hi\n```'}}
                    ]
                },
            )
        )
        result = await client.generate_script(
            description="echo", language="bash", model="openai/gpt-4o"
        )
        assert result == "echo hi"

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
