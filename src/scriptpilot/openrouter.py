from __future__ import annotations

import re

import httpx

BASE_URL = "https://openrouter.ai/api/v1"

SYSTEM_PROMPT = (
    "You are a script generator. Output ONLY valid, executable code. "
    "Include brief comments where helpful. "
    "Do NOT include markdown fences, explanations, or any text outside the script. "
    "The script must be complete and ready to run."
)


class AuthenticationError(Exception):
    """Raised when the API key is invalid."""


class RateLimitError(Exception):
    """Raised when rate limited by OpenRouter."""


class OpenRouterConnectionError(Exception):
    """Raised when unable to reach OpenRouter."""


def strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences if present."""
    pattern = r"^```(?:\w+)?\n(.*?)```$"
    match = re.match(pattern, text.strip(), re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


class OpenRouterClient:
    """Async client for the OpenRouter API."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def generate_script(
        self, description: str, language: str, model: str
    ) -> str:
        """Generate a script from a natural language description."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": (
                                    f"Write a {language} script that does the following:\n\n"
                                    f"{description}"
                                ),
                            },
                        ],
                    },
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

        content = response.json()["choices"][0]["message"]["content"]
        return strip_markdown_fences(content)

    async def list_models(self) -> list[dict]:
        """Fetch available models from OpenRouter."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{BASE_URL}/models",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=30,
                )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise OpenRouterConnectionError(f"Could not reach OpenRouter: {e}") from e
        response.raise_for_status()
        return response.json()["data"]
