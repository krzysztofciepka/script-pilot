from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, model_validator


class ScriptArg(BaseModel):
    """A single argument definition for a script."""

    name: str
    type: Literal["string", "boolean", "integer", "path", "choice"]
    required: bool = True
    default: str | bool | int | None = None
    choices: list[str] | None = None

    @model_validator(mode="after")
    def _validate_choices(self):
        if self.type == "choice":
            if not self.choices:
                raise ValueError("choice arg requires non-empty choices list")
            if any(not c.strip() for c in self.choices):
                raise ValueError("choices must not contain blank entries")
            if self.default is not None and self.default not in self.choices:
                raise ValueError(f"default {self.default!r} not in choices")
        elif self.choices is not None:
            raise ValueError("choices is only valid when type='choice'")
        return self


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
    cwd: str | None = None
    env: dict[str, str] = {}

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


class AppConfig(BaseModel):
    """Application configuration."""

    default_model: str = "openai/gpt-4o"
    python_command: str = "uv run --script"
    editor: str | None = None
    scripts_dir: str | None = None
    theme: Literal["dark", "light"] = "dark"
