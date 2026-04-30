import pytest
from pathlib import Path

from scriptpilot.executor import execute_script, ExecutionResult, InterpreterNotFoundError
from scriptpilot.models import Script, ScriptArg
from scriptpilot.paths import EXTENSIONS


def _materialize(script: Script, tmp_path: Path) -> Path:
    """Write the script body to tmp_path and return its path."""
    body = tmp_path / f"{script.id}{EXTENSIONS[script.type]}"
    body.write_text(script.content)
    return body


@pytest.fixture
def bash_script(tmp_path):
    script = Script(
        name="echo test",
        description="echoes hello",
        type="bash",
        content='echo "hello world"',
    )
    return script, _materialize(script, tmp_path)


class TestExecutor:
    @pytest.mark.asyncio
    async def test_run_bash_script(self, bash_script):
        script, path = bash_script
        lines = []
        result = await execute_script(script, on_output=lines.append, script_path=path)
        assert result.exit_code == 0
        assert not result.timed_out
        assert result.duration >= 0
        assert any("hello world" in line for line in lines)

    @pytest.mark.asyncio
    async def test_run_python_script(self, tmp_path):
        script = Script(
            name="py",
            description="python test",
            type="python",
            content="print('from python')",
        )
        path = _materialize(script, tmp_path)
        lines = []
        result = await execute_script(script, on_output=lines.append, script_path=path)
        assert result.exit_code == 0
        assert any("from python" in line for line in lines)

    @pytest.mark.asyncio
    async def test_script_with_args(self, tmp_path):
        script = Script(
            name="args test",
            description="echoes args",
            type="bash",
            content='echo "arg1=$1 arg2=$2"',
            args=[
                ScriptArg(name="first", type="string"),
                ScriptArg(name="second", type="string"),
            ],
        )
        path = _materialize(script, tmp_path)
        lines = []
        result = await execute_script(
            script,
            arg_values=["hello", "world"],
            on_output=lines.append,
            script_path=path,
        )
        assert result.exit_code == 0
        assert any("arg1=hello arg2=world" in line for line in lines)

    @pytest.mark.asyncio
    async def test_script_nonzero_exit(self, tmp_path):
        script = Script(
            name="fail",
            description="exits 1",
            type="bash",
            content="exit 42",
        )
        path = _materialize(script, tmp_path)
        result = await execute_script(script, script_path=path)
        assert result.exit_code == 42

    @pytest.mark.asyncio
    async def test_script_timeout(self, tmp_path):
        script = Script(
            name="slow",
            description="sleeps forever",
            type="bash",
            content="sleep 60",
            timeout=1,
        )
        path = _materialize(script, tmp_path)
        result = await execute_script(script, script_path=path)
        assert result.timed_out is True

    @pytest.mark.asyncio
    async def test_stderr_captured(self, tmp_path):
        script = Script(
            name="stderr",
            description="writes to stderr",
            type="bash",
            content='echo "err msg" >&2',
        )
        path = _materialize(script, tmp_path)
        lines = []
        result = await execute_script(script, on_output=lines.append, script_path=path)
        assert result.exit_code == 0
        assert any("err msg" in line for line in lines)

    @pytest.mark.asyncio
    async def test_interpreter_present_on_path(self):
        from scriptpilot.executor import _resolve_command
        # bash and js are static lookups; python uses python_command.
        assert _resolve_command("bash", "python3")[0]
        assert _resolve_command("python", "python3")[0]

    @pytest.mark.asyncio
    async def test_interpreter_not_found_raises(self, tmp_path, monkeypatch):
        import shutil
        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        script = Script(
            name="missing",
            description="missing interpreter",
            type="bash",
            content="echo hi",
        )
        path = _materialize(script, tmp_path)
        with pytest.raises(InterpreterNotFoundError, match="bash not found"):
            await execute_script(script, script_path=path)


class TestResolveCommand:
    def test_bash_unchanged(self):
        from scriptpilot.executor import _resolve_command
        cmd = _resolve_command("bash", "uv run --script")
        assert cmd[0].endswith("/bash") or cmd[0] == "bash"
        assert len(cmd) == 1

    def test_python_single_token(self):
        from scriptpilot.executor import _resolve_command
        cmd = _resolve_command("python", "python3")
        assert len(cmd) == 1
        assert cmd[0].endswith("/python3") or cmd[0] == "python3"

    def test_python_multi_token_splits(self, monkeypatch):
        import shutil
        from scriptpilot.executor import _resolve_command
        # Pretend `uv` is on PATH at /usr/bin/uv.
        monkeypatch.setattr(shutil, "which", lambda c: f"/usr/bin/{c}" if c == "uv" else None)
        cmd = _resolve_command("python", "uv run --script")
        assert cmd == ["/usr/bin/uv", "run", "--script"]

    def test_python_empty_falls_back_to_python3(self, monkeypatch):
        import shutil
        from scriptpilot.executor import _resolve_command
        monkeypatch.setattr(shutil, "which", lambda c: f"/usr/bin/{c}" if c == "python3" else None)
        cmd = _resolve_command("python", "")
        assert cmd == ["/usr/bin/python3"]

    def test_python_whitespace_falls_back_to_python3(self, monkeypatch):
        import shutil
        from scriptpilot.executor import _resolve_command
        monkeypatch.setattr(shutil, "which", lambda c: f"/usr/bin/{c}" if c == "python3" else None)
        cmd = _resolve_command("python", "   ")
        assert cmd == ["/usr/bin/python3"]

    def test_python_first_token_validated(self, monkeypatch):
        import shutil
        from scriptpilot.executor import _resolve_command, InterpreterNotFoundError
        monkeypatch.setattr(shutil, "which", lambda c: None)
        with pytest.raises(InterpreterNotFoundError, match="definitely-not-real"):
            _resolve_command("python", "definitely-not-real --flag")


class TestExecuteScriptPythonCommand:
    @pytest.mark.asyncio
    async def test_python_command_python3(self, tmp_path):
        """Default 'python3' path runs without uv."""
        script = Script(
            name="py",
            description="python test",
            type="python",
            content="print('hi from py')",
        )
        path = _materialize(script, tmp_path)
        lines = []
        result = await execute_script(
            script,
            on_output=lines.append,
            script_path=path,
            python_command="python3",
        )
        assert result.exit_code == 0
        assert any("hi from py" in line for line in lines)

    @pytest.mark.asyncio
    async def test_python_command_unknown_raises(self, tmp_path):
        from scriptpilot.executor import InterpreterNotFoundError
        script = Script(
            name="py",
            description="python test",
            type="python",
            content="print('hi')",
        )
        path = _materialize(script, tmp_path)
        with pytest.raises(InterpreterNotFoundError, match="definitely-not-real"):
            await execute_script(
                script,
                script_path=path,
                python_command="definitely-not-real --flag",
            )


class TestResolveCwd:
    def test_none_returns_home(self):
        from scriptpilot.executor import _resolve_cwd
        assert _resolve_cwd(None) == Path.home()

    def test_empty_returns_home(self):
        from scriptpilot.executor import _resolve_cwd
        assert _resolve_cwd("") == Path.home()
        assert _resolve_cwd("   ") == Path.home()

    def test_existing_dir(self, tmp_path):
        from scriptpilot.executor import _resolve_cwd
        assert _resolve_cwd(str(tmp_path)) == tmp_path

    def test_tilde_expansion(self):
        from scriptpilot.executor import _resolve_cwd
        assert _resolve_cwd("~") == Path.home()

    def test_missing_dir_raises(self):
        from scriptpilot.executor import _resolve_cwd, ScriptCwdError
        with pytest.raises(ScriptCwdError, match="cwd does not exist"):
            _resolve_cwd("/nonexistent/path/that/cannot/be/real")

    def test_file_not_directory_raises(self, tmp_path):
        from scriptpilot.executor import _resolve_cwd, ScriptCwdError
        f = tmp_path / "afile"
        f.write_text("hi")
        with pytest.raises(ScriptCwdError, match="not a directory"):
            _resolve_cwd(str(f))


class TestExecuteScriptCwd:
    @pytest.mark.asyncio
    async def test_cwd_applied(self, tmp_path):
        script = Script(
            name="pwd",
            description="prints pwd",
            type="bash",
            content="pwd",
            cwd=str(tmp_path),
        )
        path = _materialize(script, tmp_path)
        lines = []
        result = await execute_script(
            script, on_output=lines.append, script_path=path,
        )
        assert result.exit_code == 0
        # Resolve to handle macOS /private/var symlink quirks.
        assert any(str(tmp_path.resolve()) in line for line in lines)

    @pytest.mark.asyncio
    async def test_cwd_default_is_home(self, tmp_path):
        script = Script(
            name="pwd",
            description="prints pwd",
            type="bash",
            content="pwd",
        )
        path = _materialize(script, tmp_path)
        lines = []
        result = await execute_script(
            script, on_output=lines.append, script_path=path,
        )
        assert result.exit_code == 0
        assert any(str(Path.home()) in line for line in lines)

    @pytest.mark.asyncio
    async def test_cwd_missing_raises(self, tmp_path):
        from scriptpilot.executor import ScriptCwdError
        script = Script(
            name="pwd",
            description="prints pwd",
            type="bash",
            content="pwd",
            cwd="/nonexistent/path/that/cannot/be/real",
        )
        path = _materialize(script, tmp_path)
        with pytest.raises(ScriptCwdError, match="cwd does not exist"):
            await execute_script(script, script_path=path)


class TestExecuteScriptEnv:
    @pytest.mark.asyncio
    async def test_per_script_env_applied(self, tmp_path):
        script = Script(
            name="env",
            description="echoes FOO",
            type="bash",
            content='echo "FOO=$FOO"',
            env={"FOO": "bar"},
        )
        path = _materialize(script, tmp_path)
        lines = []
        result = await execute_script(
            script, on_output=lines.append, script_path=path,
        )
        assert result.exit_code == 0
        assert any("FOO=bar" in line for line in lines)

    @pytest.mark.asyncio
    async def test_secrets_loaded_into_env(self, tmp_path, monkeypatch):
        from scriptpilot import executor as executor_mod
        monkeypatch.setattr(
            executor_mod, "load_secrets",
            lambda: {"JIRA_TOKEN": "secret123"},
        )
        script = Script(
            name="secrets",
            description="echoes JIRA_TOKEN",
            type="bash",
            content='echo "JIRA_TOKEN=$JIRA_TOKEN"',
        )
        path = _materialize(script, tmp_path)
        lines = []
        result = await execute_script(
            script, on_output=lines.append, script_path=path,
        )
        assert result.exit_code == 0
        assert any("JIRA_TOKEN=secret123" in line for line in lines)

    @pytest.mark.asyncio
    async def test_env_precedence_script_overrides_secrets_overrides_os(
        self, tmp_path, monkeypatch
    ):
        """script.env > secrets > os.environ."""
        from scriptpilot import executor as executor_mod
        monkeypatch.setenv("X", "from_env")
        monkeypatch.setenv("Y", "y_from_env")
        monkeypatch.setattr(
            executor_mod, "load_secrets",
            lambda: {"X": "from_secrets", "Y": "y_from_secrets", "Z": "z_secret"},
        )
        script = Script(
            name="prec",
            description="prints precedence",
            type="bash",
            content='echo "X=$X"; echo "Y=$Y"; echo "Z=$Z"',
            env={"X": "from_script"},
        )
        path = _materialize(script, tmp_path)
        lines = []
        result = await execute_script(
            script, on_output=lines.append, script_path=path,
        )
        assert result.exit_code == 0
        assert any("X=from_script" in line for line in lines)
        assert any("Y=y_from_secrets" in line for line in lines)
        assert any("Z=z_secret" in line for line in lines)
