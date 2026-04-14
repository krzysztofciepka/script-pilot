from __future__ import annotations

import json as _json
import re
from dataclasses import dataclass

import httpx

from scriptpilot.models import ScriptArg

BASE_URL = "https://openrouter.ai/api/v1"

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


class AuthenticationError(Exception):
    """Raised when the API key is invalid."""


class RateLimitError(Exception):
    """Raised when rate limited by OpenRouter."""


class OpenRouterConnectionError(Exception):
    """Raised when unable to reach OpenRouter."""


class MalformedResponseError(Exception):
    """Raised when the LLM response does not match the expected format."""


@dataclass
class GenerationResult:
    """Parsed LLM response containing code and argument definitions."""
    code: str
    args: list[ScriptArg]


def parse_generation_response(text: str) -> GenerationResult:
    """Parse an LLM response into code and argument definitions."""
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
