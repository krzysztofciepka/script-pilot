from scriptpilot.agent.tools import is_denied, run_bash


def test_run_bash_returns_exit_and_output(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    out = run_bash("cat a.txt", tmp_path, timeout=10)
    assert out.startswith("exit 0")
    assert "hello" in out


def test_run_bash_runs_in_cwd(tmp_path):
    (tmp_path / "only-here.txt").write_text("x")
    out = run_bash("ls", tmp_path, timeout=10)
    assert "only-here.txt" in out


def test_run_bash_nonzero_exit(tmp_path):
    out = run_bash("exit 3", tmp_path, timeout=10)
    assert out.startswith("exit 3")


def test_run_bash_timeout(tmp_path):
    out = run_bash("sleep 5", tmp_path, timeout=1)
    assert "timed out" in out.lower()


def test_denylist_blocks_destructive():
    assert is_denied("rm -rf /")
    assert is_denied("sudo reboot")
    assert is_denied("dd if=/dev/zero of=/dev/sda")
    assert not is_denied("cat script.sh")
    assert not is_denied("grep -r foo .")


def test_run_bash_blocks_denied(tmp_path):
    out = run_bash("rm -rf /", tmp_path, timeout=10)
    assert "blocked" in out.lower()


from scriptpilot.agent.session import ChatSession
from scriptpilot.agent.tools import TOOL_SCHEMAS, dispatch_tool


def test_tool_schemas_cover_all_three():
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert names == {"bash", "update_script", "verify"}
    for t in TOOL_SCHEMAS:
        assert t["type"] == "function"
        assert "parameters" in t["function"]


def test_dispatch_bash(tmp_path):
    s = ChatSession.new(tmp_path / "work")
    out = dispatch_tool("bash", {"cmd": "echo hi"}, s, bash_timeout=10)
    assert "hi" in out


def test_dispatch_update_script(tmp_path):
    s = ChatSession.new(tmp_path / "work")
    out = dispatch_tool(
        "update_script", {"code": "echo hi", "meta_patch": {"name": "n"}}, s, bash_timeout=10
    )
    assert s.draft.content == "echo hi"
    assert s.draft.name == "n"
    assert "draft updated" in out


def test_dispatch_verify(tmp_path):
    s = ChatSession.new(tmp_path / "work")
    s.apply_update(code="echo ok", meta_patch=None)
    out = dispatch_tool("verify", {}, s, bash_timeout=10)
    assert "VERIFY PASSED" in out


def test_dispatch_unknown_tool(tmp_path):
    s = ChatSession.new(tmp_path / "work")
    out = dispatch_tool("nope", {}, s, bash_timeout=10)
    assert "unknown tool" in out.lower()
