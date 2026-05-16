from __future__ import annotations

from scriptpilot.help import BindingGroup, render_shortcuts_table


class TestRenderShortcutsTable:
    def test_emits_heading_and_markdown_table_per_group(self):
        groups = [
            BindingGroup(
                label="App",
                items=[("q", "Quit"), ("?", "Help")],
            ),
            BindingGroup(
                label="Main view",
                items=[("slash", "Filter"), ("r", "Run")],
            ),
        ]

        out = render_shortcuts_table(groups)

        assert "### App" in out
        assert "### Main view" in out
        # Header row of a GitHub-style Markdown table
        assert "| Key | Action |" in out
        assert "| --- | --- |" in out
        # Keys wrapped in inline code
        assert "| `q` | Quit |" in out
        assert "| `?` | Help |" in out
        assert "| `slash` | Filter |" in out
        assert "| `r` | Run |" in out

    def test_empty_group_is_omitted(self):
        groups = [
            BindingGroup(label="Empty", items=[]),
            BindingGroup(label="Real", items=[("q", "Quit")]),
        ]

        out = render_shortcuts_table(groups)

        assert "### Empty" not in out
        assert "### Real" in out
