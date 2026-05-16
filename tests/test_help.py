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


from scriptpilot.help import collect_bindings


class TestCollectBindings:
    def test_app_group_contains_visible_app_keys(self):
        groups = {g.label: g for g in collect_bindings()}
        assert "App" in groups
        keys = {k for k, _ in groups["App"].items}
        # Every currently visible App binding.
        assert {"q", "s", "g", "t"}.issubset(keys)

    def test_main_view_includes_run_and_filter(self):
        groups = {g.label: g for g in collect_bindings()}
        assert "Main view" in groups
        items = dict(groups["Main view"].items)
        assert items["r"] == "Run"
        assert items["slash"] == "Filter"
        assert items["H"] == "History"

    def test_skips_empty_descriptions(self, monkeypatch):
        """Bindings with an empty description string are hidden in Textual; filter them."""
        from scriptpilot import help as help_mod

        class FakeApp:
            BINDINGS = [
                ("a", "noop", "Visible"),
                ("b", "noop", ""),
            ]

        monkeypatch.setattr(help_mod, "_resolve_groups", lambda: [(FakeApp, "Fake")])

        groups = collect_bindings()
        items = dict(groups[0].items)
        assert items == {"a": "Visible"}

    def test_accepts_textual_binding_objects(self, monkeypatch):
        """Textual sometimes stores BINDINGS as Binding(...) objects, not tuples."""
        from scriptpilot import help as help_mod
        from textual.binding import Binding

        class FakeApp:
            BINDINGS = [Binding("x", "noop", "FromObject")]

        monkeypatch.setattr(help_mod, "_resolve_groups", lambda: [(FakeApp, "Fake")])

        groups = collect_bindings()
        items = dict(groups[0].items)
        assert items == {"x": "FromObject"}

    def test_skips_show_false_tuples(self, monkeypatch):
        """4-tuple BINDINGS with show=False are hidden in Textual; filter them."""
        from scriptpilot import help as help_mod

        class FakeApp:
            BINDINGS = [
                ("a", "noop", "Visible", True),
                ("b", "noop", "Hidden", False),
            ]

        monkeypatch.setattr(help_mod, "_resolve_groups", lambda: [(FakeApp, "Fake")])

        items = dict(collect_bindings()[0].items)
        assert items == {"a": "Visible"}

    def test_skips_show_false_binding_objects(self, monkeypatch):
        """Binding(show=False) is hidden in Textual; filter them."""
        from scriptpilot import help as help_mod
        from textual.binding import Binding

        class FakeApp:
            BINDINGS = [
                Binding("a", "noop", "Visible"),
                Binding("b", "noop", "Hidden", show=False),
            ]

        monkeypatch.setattr(help_mod, "_resolve_groups", lambda: [(FakeApp, "Fake")])

        items = dict(collect_bindings()[0].items)
        assert items == {"a": "Visible"}
