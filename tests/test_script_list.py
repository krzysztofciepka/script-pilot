from scriptpilot.models import Script
from scriptpilot.widgets.script_list import _matches


def _make(name: str = "n", description: str = "d", tags=None) -> Script:
    return Script(
        name=name,
        description=description,
        type="bash",
        content="echo hi",
        tags=tags or [],
    )


class TestMatches:
    def test_empty_query_matches_everything(self):
        assert _matches(_make(), "") is True
        assert _matches(_make(), "   ") is True

    def test_substring_in_name(self):
        s = _make(name="csv-importer")
        assert _matches(s, "csv") is True
        assert _matches(s, "import") is True
        assert _matches(s, "xyz") is False

    def test_substring_in_description(self):
        s = _make(name="x", description="imports daily CSV data")
        assert _matches(s, "daily") is True
        assert _matches(s, "imports") is True

    def test_substring_in_tags(self):
        s = _make(tags=["csv", "jira"])
        assert _matches(s, "jira") is True
        assert _matches(s, "ji") is True

    def test_case_insensitive(self):
        s = _make(name="CSV-Importer", tags=["jira"])
        assert _matches(s, "csv") is True
        assert _matches(s, "JIRA") is True
        assert _matches(s, "Import") is True

    def test_no_match(self):
        s = _make(name="alpha", description="beta", tags=["gamma"])
        assert _matches(s, "delta") is False
