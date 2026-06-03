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
