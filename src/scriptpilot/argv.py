from __future__ import annotations

from pathlib import Path

from scriptpilot.models import Script, ScriptArg


class ArgValidationError(Exception):
    """Raised when a typed value fails validation."""

    def __init__(self, arg_name: str, message: str):
        super().__init__(message)
        self.arg_name = arg_name
        self.message = message


def validate_and_coerce(arg: ScriptArg, raw: str | bool) -> str | bool:
    """Validate one raw value against an arg definition.

    `raw` is whatever the form widget produced: `bool` from a Switch,
    `str` from an Input or Select. Returns the validated value, still as
    a str/bool (no path resolution or argv-style framing yet). Raises
    `ArgValidationError` on bad input.
    """
    if arg.type == "boolean":
        return bool(raw)

    text = raw if isinstance(raw, str) else str(raw)

    if not text:
        if arg.required:
            raise ArgValidationError(
                arg.name, f"'{arg.name}' is required"
            )
        return ""

    if arg.type == "integer":
        try:
            int(text)
        except ValueError:
            raise ArgValidationError(
                arg.name, f"'{arg.name}' must be an integer"
            ) from None
        return text

    if arg.type == "choice":
        if arg.choices is None or text not in arg.choices:
            allowed = ", ".join(arg.choices or [])
            raise ArgValidationError(
                arg.name, f"'{arg.name}' must be one of: {allowed}"
            )
        return text

    # string and path: any non-empty value passes; path resolution
    # happens later in build_argv.
    return text
