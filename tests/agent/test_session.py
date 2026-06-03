from scriptpilot.agent.session import ChatSession
from scriptpilot.models import Script


def test_new_session_has_empty_bash_draft(tmp_path):
    s = ChatSession.new(tmp_path / "work")
    assert s.draft.type == "bash"
    assert s.draft.content == ""
    assert s.draft_path.exists()
    assert s.draft_path.name == "script.sh"
    assert s.messages and s.messages[0]["role"] == "system"


def test_from_script_copies_code_and_meta(tmp_path):
    original = Script(name="orig", description="d", type="js", content="console.log(1)")
    s = ChatSession.from_script(original, tmp_path / "work")
    assert s.draft.type == "js"
    assert s.draft_path.name == "script.js"
    assert s.draft_path.read_text() == "console.log(1)"
    assert s.draft.id == original.id


def test_apply_update_writes_code(tmp_path):
    s = ChatSession.new(tmp_path / "work")
    summary = s.apply_update(code="echo hi", meta_patch=None)
    assert s.draft.content == "echo hi"
    assert s.draft_path.read_text() == "echo hi"
    assert "bash" in summary


def test_apply_update_type_change_renames_file(tmp_path):
    s = ChatSession.new(tmp_path / "work")
    old_path = s.draft_path
    s.apply_update(code="print(1)", meta_patch={"type": "python"})
    assert s.draft.type == "python"
    assert s.draft_path.name == "script.py"
    assert not old_path.exists()
    assert s.draft_path.read_text() == "print(1)"


def test_apply_update_sets_args_and_env(tmp_path):
    s = ChatSession.new(tmp_path / "work")
    s.apply_update(
        code=None,
        meta_patch={
            "name": "gcp-trigger",
            "env": {"GCP_PROJECT": "my-proj"},
            "args": [{"name": "region", "type": "string", "required": True}],
        },
    )
    assert s.draft.name == "gcp-trigger"
    assert s.draft.env == {"GCP_PROJECT": "my-proj"}
    assert s.draft.args[0].name == "region"


def test_clear_keeps_draft_resets_messages(tmp_path):
    s = ChatSession.new(tmp_path / "work")
    s.apply_update(code="echo hi", meta_patch=None)
    s.messages.append({"role": "user", "content": "hello"})
    s.clear()
    assert s.draft.content == "echo hi"
    assert len(s.messages) == 1 and s.messages[0]["role"] == "system"


def test_to_script_returns_draft_copy(tmp_path):
    s = ChatSession.new(tmp_path / "work")
    s.apply_update(code="echo hi", meta_patch={"name": "n", "description": "d"})
    script = s.to_script()
    assert script.name == "n"
    assert script.content == "echo hi"
