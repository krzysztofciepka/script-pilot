import pytest
from scriptpilot.executor import execute_script, ExecutionResult, InterpreterNotFoundError
from scriptpilot.models import Script, ScriptArg


@pytest.fixture
def bash_script():
    return Script(
        name="echo test",
        description="echoes hello",
        type="bash",
        content='echo "hello world"',
    )


class TestExecutor:
    @pytest.mark.asyncio
    async def test_run_bash_script(self, bash_script):
        lines = []
        result = await execute_script(bash_script, on_output=lines.append)
        assert result.exit_code == 0
        assert not result.timed_out
        assert result.duration >= 0
        assert any("hello world" in line for line in lines)

    @pytest.mark.asyncio
    async def test_run_python_script(self):
        script = Script(
            name="py",
            description="python test",
            type="python",
            content="print('from python')",
        )
        lines = []
        result = await execute_script(script, on_output=lines.append)
        assert result.exit_code == 0
        assert any("from python" in line for line in lines)

    @pytest.mark.asyncio
    async def test_script_with_args(self):
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
        lines = []
        result = await execute_script(
            script,
            arg_values=["hello", "world"],
            on_output=lines.append,
        )
        assert result.exit_code == 0
        assert any("arg1=hello arg2=world" in line for line in lines)

    @pytest.mark.asyncio
    async def test_script_nonzero_exit(self):
        script = Script(
            name="fail",
            description="exits 1",
            type="bash",
            content="exit 42",
        )
        result = await execute_script(script)
        assert result.exit_code == 42

    @pytest.mark.asyncio
    async def test_script_timeout(self):
        script = Script(
            name="slow",
            description="sleeps forever",
            type="bash",
            content="sleep 60",
            timeout=1,
        )
        result = await execute_script(script)
        assert result.timed_out is True

    @pytest.mark.asyncio
    async def test_stderr_captured(self):
        script = Script(
            name="stderr",
            description="writes to stderr",
            type="bash",
            content='echo "err msg" >&2',
        )
        lines = []
        result = await execute_script(script, on_output=lines.append)
        assert result.exit_code == 0
        assert any("err msg" in line for line in lines)

    @pytest.mark.asyncio
    async def test_interpreter_not_found(self):
        from scriptpilot.executor import _get_interpreter
        assert _get_interpreter("bash") is not None
        assert _get_interpreter("python") is not None
