from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import ListItem, ListView, Label
from rich.markup import escape

from scriptpilot.models import Script

TYPE_LABELS = {"bash": "SH", "python": "PY", "js": "JS"}


def _matches(script: Script, query: str) -> bool:
    """Case-insensitive substring match across name, description, and tags."""
    q = query.strip().lower()
    if not q:
        return True
    haystack = " ".join([script.name, script.description, *script.tags]).lower()
    return q in haystack


class ScriptSelected(Message):
    """Posted when a script is highlighted in the list (arrow navigation)."""

    def __init__(self, script: Script):
        super().__init__()
        self.script = script



class ScriptList(Widget):
    """Left panel listing saved scripts."""

    DEFAULT_CSS = """
    ScriptList {
        width: 30;
        dock: left;
        border-right: solid $primary;
    }
    ScriptList ListView {
        height: 1fr;
    }
    """

    def __init__(self, scripts: list[Script] | None = None):
        super().__init__()
        self._scripts: list[Script] = scripts or []

    def compose(self) -> ComposeResult:
        sorted_scripts = self._sorted(self._scripts)
        with ListView():
            for script in sorted_scripts:
                label = self._make_label(script)
                yield ListItem(Label(label), name=script.id)

    def update_scripts(self, scripts: list[Script]):
        """Refresh the list with new script data."""
        self._scripts = scripts
        sorted_scripts = self._sorted(scripts)
        lv = self.query_one(ListView)
        lv.clear()
        for script in sorted_scripts:
            label = self._make_label(script)
            lv.append(ListItem(Label(label), name=script.id))

    @staticmethod
    def _sorted(scripts: list[Script]) -> list[Script]:
        """Sort favorites first, preserve insertion order within groups."""
        favorites = [s for s in scripts if s.favorite]
        others = [s for s in scripts if not s.favorite]
        return favorites + others

    @staticmethod
    def _make_label(script: Script) -> str:
        star = " *" if script.favorite else ""
        base = f"[{TYPE_LABELS.get(script.type, '??')}]{star} {script.name}"
        if script.tags:
            base += f" [dim]{{{', '.join(escape(t) for t in script.tags)}}}[/dim]"
        return base

    def _find_script(self, item_name: str) -> Script | None:
        for script in self._scripts:
            if script.id == item_name:
                return script
        return None

    def on_list_view_highlighted(self, event: ListView.Highlighted):
        if event.item is not None:
            script = self._find_script(event.item.name)
            if script:
                self.post_message(ScriptSelected(script))

    def on_list_view_selected(self, event: ListView.Selected):
        script = self._find_script(event.item.name)
        if script:
            self.post_message(ScriptSelected(script))
