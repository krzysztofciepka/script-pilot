from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import ListItem, ListView, Label

from scriptpilot.models import Script

TYPE_LABELS = {"bash": "SH", "python": "PY", "js": "JS"}


class ScriptSelected(Message):
    """Posted when a script is highlighted in the list (arrow navigation)."""

    def __init__(self, script: Script):
        super().__init__()
        self.script = script


class ScriptRunRequested(Message):
    """Posted when a script is activated (Enter/click) in the list."""

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
        with ListView():
            for script in self._scripts:
                label = f"[{TYPE_LABELS.get(script.type, '??')}] {script.name}"
                yield ListItem(Label(label), name=script.id)

    def update_scripts(self, scripts: list[Script]):
        """Refresh the list with new script data."""
        self._scripts = scripts
        lv = self.query_one(ListView)
        lv.clear()
        for script in scripts:
            label = f"[{TYPE_LABELS.get(script.type, '??')}] {script.name}"
            lv.append(ListItem(Label(label), name=script.id))

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
            self.post_message(ScriptRunRequested(script))
