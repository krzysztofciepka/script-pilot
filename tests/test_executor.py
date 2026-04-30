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
        from scriptpilot.executor import _get_interpreter
        assert _get_interpreter("bash") is not None
        assert _get_interpreter("python") is not None

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
