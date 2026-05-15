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


class TestScriptArgChoices:
    def test_choice_with_choices_ok(self):
        arg = ScriptArg(name="env", type="choice", choices=["dev", "staging", "prod"])
        assert arg.type == "choice"
        assert arg.choices == ["dev", "staging", "prod"]

    def test_choice_without_choices_rejected(self):
        with pytest.raises(Exception):
            ScriptArg(name="env", type="choice")

    def test_choice_empty_list_rejected(self):
        with pytest.raises(Exception):
            ScriptArg(name="env", type="choice", choices=[])

    def test_choice_blank_string_in_choices_rejected(self):
        with pytest.raises(Exception):
            ScriptArg(name="env", type="choice", choices=["dev", "   "])

    def test_choices_on_non_choice_rejected(self):
        with pytest.raises(Exception):
            ScriptArg(name="x", type="string", choices=["a"])

    def test_choice_default_in_choices_ok(self):
        arg = ScriptArg(
            name="env", type="choice",
            choices=["dev", "prod"], default="dev",
        )
        assert arg.default == "dev"

    def test_choice_default_not_in_choices_rejected(self):
        with pytest.raises(Exception):
            ScriptArg(
                name="env", type="choice",
                choices=["dev", "prod"], default="staging",
            )

    def test_path_type_ok(self):
        arg = ScriptArg(name="manifest", type="path")
        assert arg.type == "path"
        assert arg.choices is None

    def test_path_with_string_default_ok(self):
        arg = ScriptArg(name="manifest", type="path", default="~/foo.yaml")
        assert arg.default == "~/foo.yaml"

    def test_backward_compat_no_choices_field(self):
        """Existing meta files without `choices` load with default None."""
        data = {"name": "x", "type": "string", "required": True, "default": None}
        arg = ScriptArg(**data)
        assert arg.choices is None


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
        assert config.default_model == "blackboxai/minimax/minimax-m2.5"

    def test_custom_model(self):
        config = AppConfig(default_model="anthropic/claude-3.5-sonnet")
        assert config.default_model == "anthropic/claude-3.5-sonnet"


class TestScriptFavorite:
    def test_default_not_favorite(self):
        s = Script(name="x", description="x", type="bash", content="x")
        assert s.favorite is False

    def test_set_favorite(self):
        s = Script(name="x", description="x", type="bash", content="x", favorite=True)
        assert s.favorite is True

    def test_roundtrip_with_favorite(self):
        s = Script(name="x", description="x", type="bash", content="x", favorite=True)
        data = s.model_dump()
        s2 = Script(**data)
        assert s2.favorite is True

    def test_backward_compat_no_favorite_field(self):
        """Existing scripts without favorite field should load as False."""
        data = {"name": "x", "description": "x", "type": "bash", "content": "x", "id": "abc"}
        s = Script(**data)
        assert s.favorite is False


class TestScriptCwdEnv:
    def test_cwd_default_none(self):
        s = Script(name="x", description="x", type="bash", content="x")
        assert s.cwd is None

    def test_cwd_set(self):
        s = Script(name="x", description="x", type="bash", content="x", cwd="~/work")
        assert s.cwd == "~/work"

    def test_env_default_empty(self):
        s = Script(name="x", description="x", type="bash", content="x")
        assert s.env == {}

    def test_env_set(self):
        s = Script(
            name="x", description="x", type="bash", content="x",
            env={"FOO": "bar", "BAZ": "qux"},
        )
        assert s.env == {"FOO": "bar", "BAZ": "qux"}

    def test_roundtrip_with_cwd_and_env(self):
        s = Script(
            name="x", description="x", type="bash", content="x",
            cwd="/tmp", env={"K": "V"},
        )
        data = s.model_dump()
        s2 = Script(**data)
        assert s2.cwd == "/tmp"
        assert s2.env == {"K": "V"}

    def test_backward_compat_no_cwd_no_env(self):
        """Existing meta files without cwd/env load with defaults."""
        data = {
            "name": "x", "description": "x", "type": "bash",
            "content": "x", "id": "abc",
        }
        s = Script(**data)
        assert s.cwd is None
        assert s.env == {}


class TestScriptArgStyle:
    def test_arg_style_default_positional(self):
        s = Script(name="x", description="x", type="bash", content="x")
        assert s.arg_style == "positional"

    def test_arg_style_flags(self):
        s = Script(
            name="x", description="x", type="bash", content="x",
            arg_style="flags",
        )
        assert s.arg_style == "flags"

    def test_arg_style_invalid_rejected(self):
        with pytest.raises(Exception):
            Script(
                name="x", description="x", type="bash", content="x",
                arg_style="kwargs",
            )

    def test_arg_style_roundtrip(self):
        s = Script(
            name="x", description="x", type="bash", content="x",
            arg_style="flags",
        )
        data = s.model_dump()
        s2 = Script(**data)
        assert s2.arg_style == "flags"

    def test_backward_compat_no_arg_style_field(self):
        """Existing meta files without `arg_style` load as positional."""
        data = {
            "name": "x", "description": "x", "type": "bash",
            "content": "x", "id": "abc",
        }
        s = Script(**data)
        assert s.arg_style == "positional"


class TestAppConfigPythonCommand:
    def test_python_command_default(self):
        config = AppConfig()
        assert config.python_command == "uv run --script"

    def test_python_command_custom(self):
        config = AppConfig(python_command="python3")
        assert config.python_command == "python3"

    def test_backward_compat_no_python_command(self):
        config = AppConfig(**{"default_model": "openai/gpt-4o"})
        assert config.python_command == "uv run --script"


class TestAppConfigAuthoring:
    def test_editor_default_none(self):
        config = AppConfig()
        assert config.editor is None

    def test_editor_custom(self):
        config = AppConfig(editor="code --wait")
        assert config.editor == "code --wait"

    def test_scripts_dir_default_none(self):
        config = AppConfig()
        assert config.scripts_dir is None

    def test_scripts_dir_custom(self):
        config = AppConfig(scripts_dir="~/myscripts")
        assert config.scripts_dir == "~/myscripts"

    def test_theme_default_dark(self):
        config = AppConfig()
        assert config.theme == "dark"

    def test_theme_set_light(self):
        config = AppConfig(theme="light")
        assert config.theme == "light"

    def test_theme_invalid_rejected(self):
        with pytest.raises(Exception):
            AppConfig(theme="purple")

    def test_backward_compat_old_config(self):
        """A config dict missing the new fields loads with defaults."""
        config = AppConfig(**{"default_model": "openai/gpt-4o"})
        assert config.editor is None
        assert config.scripts_dir is None
        assert config.theme == "dark"


from scriptpilot.models import OutputLine, RunRecord


class TestRunRecord:
    def test_create_run_record(self):
        r = RunRecord(
            script_id="abc",
            script_name="my script",
            timestamp="2026-04-15T10:30:00",
            exit_code=0,
            timed_out=False,
            duration=1.5,
            lines=[OutputLine("stdout", "hello world")],
        )
        assert r.script_id == "abc"
        assert r.script_name == "my script"
        assert r.exit_code == 0
        assert r.lines == [OutputLine("stdout", "hello world")]

    def test_run_record_serialization_roundtrip(self):
        r = RunRecord(
            script_id="abc",
            script_name="test",
            timestamp="2026-04-15T10:30:00",
            exit_code=1,
            timed_out=True,
            duration=60.0,
            lines=[OutputLine("stderr", "timeout")],
        )
        data = r.model_dump()
        r2 = RunRecord(**data)
        assert r2.exit_code == 1
        assert r2.timed_out is True
        assert r2.lines == [OutputLine("stderr", "timeout")]


class TestOutputLine:
    def test_namedtuple_shape(self):
        ol = OutputLine("stdout", "hello")
        assert ol.stream == "stdout"
        assert ol.line == "hello"
        assert ol[0] == "stdout"
        assert ol[1] == "hello"

    def test_stderr_value(self):
        ol = OutputLine("stderr", "warn")
        assert ol.stream == "stderr"


class TestRunRecordLines:
    def _record(self, lines):
        return RunRecord(
            script_id="x",
            script_name="x",
            timestamp="2026-05-04T00:00:00",
            exit_code=0,
            timed_out=False,
            duration=1.0,
            lines=lines,
        )

    def test_default_lines_empty(self):
        r = RunRecord(
            script_id="x",
            script_name="x",
            timestamp="2026-05-04T00:00:00",
            exit_code=0,
            timed_out=False,
            duration=1.0,
        )
        assert r.lines == []

    def test_combined_text_chronological(self):
        r = self._record([
            OutputLine("stdout", "a"),
            OutputLine("stderr", "warn"),
            OutputLine("stdout", "b"),
        ])
        assert r.combined_text() == "a\nwarn\nb"

    def test_stdout_text_filters(self):
        r = self._record([
            OutputLine("stdout", "a"),
            OutputLine("stderr", "warn"),
            OutputLine("stdout", "b"),
        ])
        assert r.stdout_text() == "a\nb"

    def test_combined_text_empty(self):
        r = self._record([])
        assert r.combined_text() == ""

    def test_round_trip_json(self):
        r = self._record([
            OutputLine("stdout", "a"),
            OutputLine("stderr", "b"),
        ])
        dumped = r.model_dump_json()
        restored = RunRecord.model_validate_json(dumped)
        assert restored.lines == r.lines
        assert isinstance(restored.lines[0], OutputLine)


class TestScriptTags:
    def test_tags_default_empty(self):
        s = Script(name="x", description="y", type="bash", content="echo hi")
        assert s.tags == []

    def test_tags_round_trip(self):
        s = Script(
            name="x", description="y", type="bash", content="echo hi",
            tags=["csv", "jira"],
        )
        data = s.model_dump()
        assert data["tags"] == ["csv", "jira"]
        s2 = Script(**data)
        assert s2.tags == ["csv", "jira"]

    def test_tags_loads_from_meta_without_field(self):
        # Simulate an old meta.json that didn't have `tags`.
        legacy = {
            "id": "abc", "name": "x", "description": "y",
            "type": "bash", "content": "echo hi",
        }
        s = Script(**legacy)
        assert s.tags == []


class TestRunRecordCancelled:
    def test_cancelled_default_false(self):
        r = RunRecord(
            script_id="a", script_name="a",
            timestamp="2026-05-15T10:00:00",
            exit_code=0, timed_out=False, duration=1.0,
        )
        assert r.cancelled is False

    def test_cancelled_round_trip(self):
        r = RunRecord(
            script_id="a", script_name="a",
            timestamp="2026-05-15T10:00:00",
            exit_code=-1, timed_out=False, duration=2.3,
            cancelled=True,
            lines=[OutputLine("stdout", "hi")],
        )
        data = r.model_dump()
        assert data["cancelled"] is True
        r2 = RunRecord(**data)
        assert r2.cancelled is True

    def test_cancelled_loads_legacy_record(self):
        legacy = {
            "script_id": "a", "script_name": "a",
            "timestamp": "2026-05-15T10:00:00",
            "exit_code": 0, "timed_out": False, "duration": 1.0,
            "lines": [],
        }
        r = RunRecord(**legacy)
        assert r.cancelled is False
