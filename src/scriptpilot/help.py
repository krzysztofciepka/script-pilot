"""In-app help: chapter loader + auto-generated shortcuts reference."""

from __future__ import annotations

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
