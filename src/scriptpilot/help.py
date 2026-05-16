"""In-app help: chapter loader + auto-generated shortcuts reference."""

from __future__ import annotations

import importlib.resources
from dataclasses import dataclass, field


@dataclass
class BindingGroup:
    """A named group of (key, description) pairs for the shortcuts reference."""

    label: str
    items: list[tuple[str, str]] = field(default_factory=list)


def render_shortcuts_table(groups: list[BindingGroup]) -> str:
    """Render binding groups into Markdown. Empty groups are omitted."""
    parts: list[str] = []
    for g in groups:
        if not g.items:
            continue
        parts.append(f"### {g.label}\n")
        parts.append("| Key | Action |")
        parts.append("| --- | --- |")
        for key, desc in g.items:
            parts.append(f"| `{key}` | {desc} |")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _resolve_groups() -> list[tuple[type, str]]:
    """Source-of-truth list of (class, label) pairs whose BINDINGS get documented.

    Lazy imports break the app → screens → help → app cycle.
    """
    from scriptpilot.app import ScriptPilotApp
    from scriptpilot.screens.edit import EditScreen
    from scriptpilot.screens.history import HistoryScreen
    from scriptpilot.screens.json_view import JsonViewScreen
    from scriptpilot.screens.main import MainScreen
    from scriptpilot.widgets.main_panel import MainPanel
    from scriptpilot.widgets.script_list import ScriptList

    return [
        (ScriptPilotApp, "App"),
        (MainScreen, "Main view"),
        (MainPanel, "Output panel"),
        (ScriptList, "Script list"),
        (EditScreen, "Edit screen"),
        (HistoryScreen, "History modal"),
        (JsonViewScreen, "JSON view"),
    ]


def _normalize(binding) -> tuple[str, str] | None:
    """Return (key, description) for a BINDINGS entry, or None if it should be hidden."""
    if isinstance(binding, tuple):
        if len(binding) < 3:
            return None
        key, _action, desc = binding[0], binding[1], binding[2]
        show = binding[3] if len(binding) > 3 else True
    else:
        # Textual Binding object (or compatible).
        key = getattr(binding, "key", None)
        desc = getattr(binding, "description", None)
        show = getattr(binding, "show", True)
        if not key:
            return None
    if not desc or not show:
        return None
    return key, desc


def collect_bindings() -> list[BindingGroup]:
    """Return one BindingGroup per (class, label) in _resolve_groups()."""
    result: list[BindingGroup] = []
    for cls, label in _resolve_groups():
        raw = getattr(cls, "BINDINGS", []) or []
        items: list[tuple[str, str]] = []
        for b in raw:
            n = _normalize(b)
            if n is not None:
                items.append(n)
        result.append(BindingGroup(label=label, items=items))
    return result


PLACEHOLDER = "<!-- SHORTCUTS_TABLE -->"


def load_help_markdown() -> str:
    """Return the help text with the shortcuts placeholder substituted."""
    raw = (importlib.resources.files("scriptpilot") / "help.md").read_text(
        encoding="utf-8"
    )
    table = render_shortcuts_table(collect_bindings())
    return raw.replace(PLACEHOLDER, table)
