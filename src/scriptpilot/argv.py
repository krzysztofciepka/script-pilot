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


def _resolve_cwd(script_cwd: str | None) -> Path:
    """Mirror executor._resolve_cwd: None/empty/whitespace → home; else expanduser.

    Unlike the executor we do NOT verify the directory exists — that's the
    executor's job at run time. We only need a base Path for joining.
    """
    if not script_cwd or not script_cwd.strip():
        return Path.home()
    return Path(script_cwd).expanduser()


def _resolve_path_value(raw: str, script_cwd: str | None) -> str:
    """Resolve a typed path: expand ~, then join against the script cwd if relative."""
    p = Path(raw).expanduser()
    if p.is_absolute():
        return str(p)
    return str(_resolve_cwd(script_cwd) / p)


def build_argv(script: Script, validated: list[str | bool]) -> list[str]:
    """Build the final argv list for a script run."""
    argv: list[str] = []
    for arg, value in zip(script.args, validated):
        if arg.type == "boolean":
            if script.arg_style == "flags":
                if value:
                    argv.append(f"--{arg.name}")
                # False: omit
            else:
                argv.append("true" if value else "false")
            continue

        # value is a str at this point
        text = value if isinstance(value, str) else str(value)

        if arg.type == "path" and text:
            text = _resolve_path_value(text, script.cwd)

        if script.arg_style == "flags":
            if text == "":
                # optional empty: omit the flag
                continue
            argv.append(f"--{arg.name}")
            argv.append(text)
        else:
            argv.append(text)

    return argv
