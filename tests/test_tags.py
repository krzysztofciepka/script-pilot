from scriptpilot.tags import normalize_tags


class TestNormalizeTags:
    def test_empty_string(self):
        assert normalize_tags("") == []

    def test_whitespace_only(self):
        assert normalize_tags("   ,  , ") == []

    def test_strips_whitespace(self):
        assert normalize_tags("  csv ,   jira ") == ["csv", "jira"]

    def test_lowercases(self):
        assert normalize_tags("CSV, Jira, FOO") == ["csv", "jira", "foo"]

    def test_dedupes_preserve_first_seen_order(self):
        assert normalize_tags("Foo, foo , BAR, bar, Foo") == ["foo", "bar"]

    def test_drops_empty_pieces(self):
        assert normalize_tags("a,,b,,,c") == ["a", "b", "c"]

    def test_single_tag(self):
        assert normalize_tags("daily") == ["daily"]
