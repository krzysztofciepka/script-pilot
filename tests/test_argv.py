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
