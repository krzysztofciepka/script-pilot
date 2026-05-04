from scriptpilot.widgets.main_panel import (
    _last_nonempty_line,
    _safe_name,
    _try_parse_json,
)


class TestTryParseJson:
    def test_single_line_object(self):
        assert _try_parse_json('{"x": 1}') == {"x": 1}

    def test_single_line_array(self):
        assert _try_parse_json("[1, 2, 3]") == [1, 2, 3]

    def test_multi_line_pretty_printed(self):
        assert _try_parse_json('{\n  "x": 1,\n  "y": 2\n}') == {"x": 1, "y": 2}

    def test_status_line_then_json(self):
        assert _try_parse_json('fetching...\n{"ok": true}') == {"ok": True}

    def test_not_json(self):
        assert _try_parse_json("hello world") is None

    def test_empty(self):
        assert _try_parse_json("") is None

    def test_whitespace_only(self):
        assert _try_parse_json("   \n  ") is None


class TestLastNonemptyLine:
    def test_strips_trailing_blanks(self):
        assert _last_nonempty_line("a\n\n") == "a"

    def test_no_lines(self):
        assert _last_nonempty_line("") == ""

    def test_only_blanks(self):
        assert _last_nonempty_line("\n\n  \n") == ""

    def test_single_line_no_newline(self):
        assert _last_nonempty_line("only") == "only"


class TestSafeName:
    def test_strips_unsafe_chars(self):
        assert _safe_name("My Script!!") == "My-Script"

    def test_keeps_safe_chars(self):
        assert _safe_name("foo_bar.baz-1") == "foo_bar.baz-1"

    def test_empty_returns_default(self):
        assert _safe_name("") == "output"

    def test_all_unsafe_returns_default(self):
        assert _safe_name("!!!") == "output"

    def test_collapses_runs(self):
        assert _safe_name("a   b") == "a-b"
