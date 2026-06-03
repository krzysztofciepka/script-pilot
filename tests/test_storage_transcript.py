from scriptpilot.models import Script
from scriptpilot.storage import ScriptStore


def test_load_transcript_missing_returns_empty(tmp_path):
    store = ScriptStore(path=tmp_path)
    assert store.load_transcript("nope") == []


def test_save_and_load_transcript_roundtrip(tmp_path):
    store = ScriptStore(path=tmp_path)
    script = Script(name="n", description="d", type="bash", content="echo hi")
    store.add(script)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]
    store.save_transcript(script.id, messages)
    assert store.load_transcript(script.id) == messages


def test_delete_removes_transcript(tmp_path):
    store = ScriptStore(path=tmp_path)
    script = Script(name="n", description="d", type="bash", content="x")
    store.add(script)
    store.save_transcript(script.id, [{"role": "user", "content": "hi"}])
    store.delete(script.id)
    assert store.load_transcript(script.id) == []
    assert not (tmp_path / f"{script.id}.messages.json").exists()
