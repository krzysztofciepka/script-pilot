import pytest

from scriptpilot.argv import ArgValidationError, validate_and_coerce
from scriptpilot.models import ScriptArg


class TestValidateAndCoerceString:
    def test_required_value_ok(self):
        arg = ScriptArg(name="msg", type="string", required=True)
        assert validate_and_coerce(arg, "hello") == "hello"

    def test_required_empty_raises(self):
        arg = ScriptArg(name="msg", type="string", required=True)
        with pytest.raises(ArgValidationError) as ei:
            validate_and_coerce(arg, "")
        assert ei.value.arg_name == "msg"
        assert "required" in ei.value.message.lower()

    def test_optional_empty_returns_empty(self):
        arg = ScriptArg(name="msg", type="string", required=False)
        assert validate_and_coerce(arg, "") == ""


class TestValidateAndCoerceBoolean:
    def test_true(self):
        arg = ScriptArg(name="dry", type="boolean", required=False)
        assert validate_and_coerce(arg, True) is True

    def test_false(self):
        arg = ScriptArg(name="dry", type="boolean", required=False)
        assert validate_and_coerce(arg, False) is False


class TestValidateAndCoerceInteger:
    def test_valid_integer_string(self):
        arg = ScriptArg(name="n", type="integer", required=True)
        assert validate_and_coerce(arg, "42") == "42"

    def test_negative_integer(self):
        arg = ScriptArg(name="n", type="integer", required=True)
        assert validate_and_coerce(arg, "-5") == "-5"

    def test_zero(self):
        arg = ScriptArg(name="n", type="integer", required=False)
        assert validate_and_coerce(arg, "0") == "0"

    def test_non_numeric_raises(self):
        arg = ScriptArg(name="n", type="integer", required=True)
        with pytest.raises(ArgValidationError) as ei:
            validate_and_coerce(arg, "abc")
        assert ei.value.arg_name == "n"
        assert "integer" in ei.value.message.lower()

    def test_float_string_raises(self):
        arg = ScriptArg(name="n", type="integer", required=True)
        with pytest.raises(ArgValidationError):
            validate_and_coerce(arg, "3.14")

    def test_required_empty_raises(self):
        arg = ScriptArg(name="n", type="integer", required=True)
        with pytest.raises(ArgValidationError):
            validate_and_coerce(arg, "")

    def test_optional_empty_returns_empty(self):
        arg = ScriptArg(name="n", type="integer", required=False)
        assert validate_and_coerce(arg, "") == ""


class TestValidateAndCoercePath:
    def test_required_value_ok(self):
        arg = ScriptArg(name="p", type="path", required=True)
        assert validate_and_coerce(arg, "foo.txt") == "foo.txt"

    def test_required_empty_raises(self):
        arg = ScriptArg(name="p", type="path", required=True)
        with pytest.raises(ArgValidationError):
            validate_and_coerce(arg, "")

    def test_optional_empty_returns_empty(self):
        arg = ScriptArg(name="p", type="path", required=False)
        assert validate_and_coerce(arg, "") == ""


class TestValidateAndCoerceChoice:
    def test_valid_choice(self):
        arg = ScriptArg(name="env", type="choice", choices=["dev", "prod"])
        assert validate_and_coerce(arg, "dev") == "dev"

    def test_choice_not_in_list_raises(self):
        arg = ScriptArg(name="env", type="choice", choices=["dev", "prod"])
        with pytest.raises(ArgValidationError) as ei:
            validate_and_coerce(arg, "staging")
        assert ei.value.arg_name == "env"
        assert "one of" in ei.value.message.lower()

    def test_required_empty_raises(self):
        arg = ScriptArg(name="env", type="choice",
                        choices=["dev", "prod"], required=True)
        with pytest.raises(ArgValidationError):
            validate_and_coerce(arg, "")

    def test_optional_empty_returns_empty(self):
        arg = ScriptArg(name="env", type="choice",
                        choices=["dev", "prod"], required=False)
        assert validate_and_coerce(arg, "") == ""


from pathlib import Path

from scriptpilot.argv import build_argv
from scriptpilot.models import Script


def _make_script(args, arg_style="positional", cwd=None):
    return Script(
        name="x", description="x", type="bash", content="x",
        args=args, arg_style=arg_style, cwd=cwd,
    )


class TestBuildArgvPositional:
    def test_string(self):
        s = _make_script([ScriptArg(name="msg", type="string")])
        assert build_argv(s, ["hello"]) == ["hello"]

    def test_integer(self):
        s = _make_script([ScriptArg(name="n", type="integer")])
        assert build_argv(s, ["42"]) == ["42"]

    def test_boolean_true(self):
        s = _make_script([ScriptArg(name="dry", type="boolean")])
        assert build_argv(s, [True]) == ["true"]

    def test_boolean_false(self):
        s = _make_script([ScriptArg(name="dry", type="boolean")])
        assert build_argv(s, [False]) == ["false"]

    def test_optional_string_empty_emits_empty_string(self):
        s = _make_script([ScriptArg(name="msg", type="string", required=False)])
        assert build_argv(s, [""]) == [""]

    def test_choice(self):
        s = _make_script([ScriptArg(name="env", type="choice",
                                    choices=["dev", "prod"])])
        assert build_argv(s, ["dev"]) == ["dev"]

    def test_mixed(self):
        s = _make_script([
            ScriptArg(name="env", type="choice", choices=["dev", "prod"]),
            ScriptArg(name="dry", type="boolean"),
            ScriptArg(name="n", type="integer"),
        ])
        assert build_argv(s, ["dev", True, "42"]) == ["dev", "true", "42"]


class TestBuildArgvFlags:
    def test_string_required(self):
        s = _make_script(
            [ScriptArg(name="msg", type="string")],
            arg_style="flags",
        )
        assert build_argv(s, ["hello"]) == ["--msg", "hello"]

    def test_integer(self):
        s = _make_script(
            [ScriptArg(name="n", type="integer")],
            arg_style="flags",
        )
        assert build_argv(s, ["42"]) == ["--n", "42"]

    def test_boolean_true_emits_flag(self):
        s = _make_script(
            [ScriptArg(name="dry-run", type="boolean")],
            arg_style="flags",
        )
        assert build_argv(s, [True]) == ["--dry-run"]

    def test_boolean_false_omits(self):
        s = _make_script(
            [ScriptArg(name="dry-run", type="boolean")],
            arg_style="flags",
        )
        assert build_argv(s, [False]) == []

    def test_optional_empty_omits_flag(self):
        s = _make_script(
            [ScriptArg(name="msg", type="string", required=False)],
            arg_style="flags",
        )
        assert build_argv(s, [""]) == []

    def test_choice(self):
        s = _make_script(
            [ScriptArg(name="env", type="choice", choices=["dev", "prod"])],
            arg_style="flags",
        )
        assert build_argv(s, ["dev"]) == ["--env", "dev"]

    def test_mixed(self):
        s = _make_script([
            ScriptArg(name="env", type="choice", choices=["dev", "prod"]),
            ScriptArg(name="region", type="string"),
            ScriptArg(name="dry-run", type="boolean", required=False, default=False),
        ], arg_style="flags")
        assert build_argv(s, ["dev", "eu", True]) == [
            "--env", "dev", "--region", "eu", "--dry-run",
        ]


class TestBuildArgvPath:
    def test_relative_resolved_against_cwd(self, tmp_path):
        s = _make_script(
            [ScriptArg(name="p", type="path")],
            cwd=str(tmp_path),
        )
        argv = build_argv(s, ["sub/file.txt"])
        assert argv == [str(tmp_path / "sub/file.txt")]

    def test_absolute_passes_through(self):
        s = _make_script([ScriptArg(name="p", type="path")])
        argv = build_argv(s, ["/etc/hosts"])
        assert argv == ["/etc/hosts"]

    def test_tilde_expanded(self):
        s = _make_script([ScriptArg(name="p", type="path")])
        argv = build_argv(s, ["~/foo.txt"])
        assert argv == [str(Path.home() / "foo.txt")]

    def test_cwd_none_falls_back_to_home(self):
        s = _make_script(
            [ScriptArg(name="p", type="path")],
            cwd=None,
        )
        argv = build_argv(s, ["foo.txt"])
        assert argv == [str(Path.home() / "foo.txt")]

    def test_cwd_empty_falls_back_to_home(self):
        s = _make_script(
            [ScriptArg(name="p", type="path")],
            cwd="",
        )
        argv = build_argv(s, ["foo.txt"])
        assert argv == [str(Path.home() / "foo.txt")]

    def test_cwd_whitespace_falls_back_to_home(self):
        s = _make_script(
            [ScriptArg(name="p", type="path")],
            cwd="   ",
        )
        argv = build_argv(s, ["foo.txt"])
        assert argv == [str(Path.home() / "foo.txt")]

    def test_cwd_with_tilde_expanded(self):
        s = _make_script(
            [ScriptArg(name="p", type="path")],
            cwd="~",
        )
        argv = build_argv(s, ["foo.txt"])
        assert argv == [str(Path.home() / "foo.txt")]

    def test_optional_empty_path_positional_emits_empty(self):
        s = _make_script(
            [ScriptArg(name="p", type="path", required=False)],
        )
        assert build_argv(s, [""]) == [""]

    def test_optional_empty_path_flags_omits(self):
        s = _make_script(
            [ScriptArg(name="p", type="path", required=False)],
            arg_style="flags",
        )
        assert build_argv(s, [""]) == []

    def test_path_in_flags_mode(self, tmp_path):
        s = _make_script(
            [ScriptArg(name="manifest", type="path")],
            arg_style="flags",
            cwd=str(tmp_path),
        )
        argv = build_argv(s, ["a.yaml"])
        assert argv == ["--manifest", str(tmp_path / "a.yaml")]
