from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import ListItem, ListView, Label

from scriptpilot.models import Script

TYPE_LABELS = {"bash": "SH", "python": "PY", "js": "JS"}


class ScriptSelected(Message):
    """Posted when a script is selected in the list."""

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

    def on_list_view_selected(self, event: ListView.Selected):
        item_name = event.item.name
        for script in self._scripts:
            if script.id == item_name:
                self.post_message(ScriptSelected(script))
                break
