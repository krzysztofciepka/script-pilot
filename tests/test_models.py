import pytest
from scriptpilot.models import ScriptArg


class TestScriptArg:
    def test_create_string_arg(self):
        arg = ScriptArg(name="env", type="string")
        assert arg.name == "env"
        assert arg.type == "string"
        assert arg.required is True
        assert arg.default is None

    def test_create_boolean_arg_with_default(self):
        arg = ScriptArg(name="dry_run", type="boolean", required=False, default=False)
        assert arg.required is False
        assert arg.default is False

    def test_create_integer_arg(self):
        arg = ScriptArg(name="retries", type="integer", default=3)
        assert arg.type == "integer"
        assert arg.default == 3

    def test_invalid_type_rejected(self):
        with pytest.raises(Exception):
            ScriptArg(name="x", type="float")


from scriptpilot.models import Script


class TestScript:
    def test_create_minimal_script(self):
        s = Script(
            name="hello",
            description="prints hello",
            type="bash",
            content="echo hello",
        )
        assert s.name == "hello"
        assert s.type == "bash"
        assert s.content == "echo hello"
        assert s.args == []
        assert s.timeout == 60
        assert s.id  # auto-generated uuid

    def test_create_script_with_args(self):
        s = Script(
            name="deploy",
            description="deploy app",
            type="bash",
            content="deploy.sh",
            args=[ScriptArg(name="env", type="string")],
            timeout=120,
        )
        assert len(s.args) == 1
        assert s.timeout == 120

    def test_invalid_script_type_rejected(self):
        with pytest.raises(Exception):
            Script(name="x", description="x", type="ruby", content="x")

    def test_script_id_auto_generated(self):
        s1 = Script(name="a", description="a", type="bash", content="a")
        s2 = Script(name="b", description="b", type="bash", content="b")
        assert s1.id != s2.id

    def test_script_serialization_roundtrip(self):
        s = Script(
            name="test",
            description="test script",
            type="python",
            content="print('hi')",
            args=[ScriptArg(name="n", type="integer", default=5)],
        )
        data = s.model_dump()
        s2 = Script(**data)
        assert s2.name == s.name
        assert s2.args[0].default == 5


from scriptpilot.models import AppConfig


class TestAppConfig:
    def test_defaults(self):
        config = AppConfig()
        assert config.default_model == "openai/gpt-4o"

    def test_custom_model(self):
        config = AppConfig(default_model="anthropic/claude-3.5-sonnet")
        assert config.default_model == "anthropic/claude-3.5-sonnet"
