from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import ListItem, ListView, Label, Input

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
    ScriptList Input {
        display: none;
        height: 3;
    }
    ScriptList Input.visible {
        display: block;
    }
    ScriptList ListView {
        height: 1fr;
    }
    """

    BINDINGS = [("escape", "clear_filter", "Clear filter")]

    def __init__(self, scripts: list[Script] | None = None):
        super().__init__()
        self._scripts: list[Script] = scripts or []
        self._current_query: str = ""

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Filter…", id="filter-input")
        with ListView():
            for script in self._sorted(self._scripts):
                yield ListItem(Label(self._make_label(script)), name=script.id)

    def focus_filter(self):
        """Public entry point for MainScreen's '/' binding."""
        inp = self.query_one("#filter-input", Input)
        inp.add_class("visible")
        inp.focus()

    def action_clear_filter(self):
        inp = self.query_one("#filter-input", Input)
        had_value = bool(inp.value)
        inp.value = ""
        inp.remove_class("visible")
        if had_value:
            self._current_query = ""
            self._render_list()
        self.query_one(ListView).focus()

    def update_scripts(self, scripts: list[Script]):
        """Refresh the list with new script data, preserving the active filter."""
        self._scripts = scripts
        self._render_list()

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "filter-input":
            self._current_query = event.value
            self._render_list()

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "filter-input":
            self.query_one(ListView).focus()

    def on_key(self, event):
        inp = self.query_one("#filter-input", Input)
        if inp.has_focus and event.key == "down":
            self.query_one(ListView).focus()
            event.stop()

    def _render_list(self):
        filtered = [s for s in self._scripts if _matches(s, self._current_query)]
        lv = self.query_one(ListView)
        lv.clear()
        for script in self._sorted(filtered):
            lv.append(ListItem(Label(self._make_label(script)), name=script.id))

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
