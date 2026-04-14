from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel


class ScriptArg(BaseModel):
    """A single argument definition for a script."""

    name: str
    type: Literal["string", "boolean", "integer"]
    required: bool = True
    default: str | bool | int | None = None


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


class AppConfig(BaseModel):
    """Application configuration."""

    default_model: str = "openai/gpt-4o"
