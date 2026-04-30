from pathlib import Path

import pytest

from scriptpilot.secrets import load_secrets, SECRETS_PATH


class TestSecretsPath:
    def test_default_path(self):
        assert SECRETS_PATH == Path.home() / ".scriptpilot" / ".env"


class TestLoadSecrets:
    def test_missing_file_returns_empty(self, tmp_path):
        assert load_secrets(tmp_path / "nope.env") == {}

    def test_empty_file_returns_empty(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("")
        assert load_secrets(p) == {}

    def test_simple_key_value(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("KEY=value\n")
        assert load_secrets(p) == {"KEY": "value"}

    def test_whitespace_around_equals(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("KEY = value with spaces\n")
        assert load_secrets(p) == {"KEY": "value with spaces"}

    def test_comments_and_blank_lines_ignored(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("# comment\n\nKEY=v\n# another\n")
        assert load_secrets(p) == {"KEY": "v"}

    def test_double_quoted_value_strips_quotes(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text('KEY="hello world"\n')
        assert load_secrets(p) == {"KEY": "hello world"}

    def test_single_quoted_value_strips_quotes(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("KEY='hello world'\n")
        assert load_secrets(p) == {"KEY": "hello world"}

    def test_mismatched_quotes_left_alone(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("KEY=\"hello'\n")
        assert load_secrets(p) == {"KEY": "\"hello'"}

    def test_malformed_line_skipped(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("noequals\nKEY=v\n")
        assert load_secrets(p) == {"KEY": "v"}

    def test_empty_key_skipped(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("=novalue\nKEY=v\n")
        assert load_secrets(p) == {"KEY": "v"}

    def test_duplicate_keys_last_wins(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("K=first\nK=second\n")
        assert load_secrets(p) == {"K": "second"}

    def test_unreadable_file_returns_empty(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("K=v\n")
        p.chmod(0o000)
        try:
            assert load_secrets(p) == {}
        finally:
            p.chmod(0o644)  # so pytest can clean it up

    def test_value_with_equals_sign(self, tmp_path):
        """A=B=C should parse as A=`B=C` (only first `=` is the separator)."""
        p = tmp_path / ".env"
        p.write_text("A=B=C\n")
        assert load_secrets(p) == {"A": "B=C"}
