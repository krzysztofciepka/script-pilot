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
