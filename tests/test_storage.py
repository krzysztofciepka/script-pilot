import json
import pytest
from pathlib import Path

from scriptpilot.models import Script, ScriptArg
from scriptpilot.storage import ScriptStore


@pytest.fixture
def store(tmp_path):
    return ScriptStore(tmp_path / "scripts.json")


@pytest.fixture
def sample_script():
    return Script(
        name="hello",
        description="prints hello",
        type="bash",
        content="echo hello",
    )


class TestScriptStore:
    def test_list_empty(self, store):
        assert store.list() == []

    def test_add_and_get(self, store, sample_script):
        store.add(sample_script)
        result = store.get(sample_script.id)
        assert result is not None
        assert result.name == "hello"

    def test_add_persists_to_disk(self, store, sample_script):
        store.add(sample_script)
        store2 = ScriptStore(store._path)
        assert len(store2.list()) == 1

    def test_list_returns_all(self, store):
        s1 = Script(name="a", description="a", type="bash", content="a")
        s2 = Script(name="b", description="b", type="python", content="b")
        store.add(s1)
        store.add(s2)
        assert len(store.list()) == 2

    def test_update(self, store, sample_script):
        store.add(sample_script)
        sample_script.name = "updated"
        store.update(sample_script)
        result = store.get(sample_script.id)
        assert result.name == "updated"

    def test_delete(self, store, sample_script):
        store.add(sample_script)
        store.delete(sample_script.id)
        assert store.get(sample_script.id) is None
        assert store.list() == []

    def test_get_nonexistent_returns_none(self, store):
        assert store.get("nonexistent") is None

    def test_creates_parent_directory(self, tmp_path):
        path = tmp_path / "subdir" / "scripts.json"
        store = ScriptStore(path)
        s = Script(name="x", description="x", type="bash", content="x")
        store.add(s)
        assert path.exists()

    def test_corrupted_json_backs_up_and_resets(self, tmp_path):
        path = tmp_path / "scripts.json"
        path.write_text("{invalid json!!!")
        store = ScriptStore(path)
        assert store.list() == []
        assert (tmp_path / "scripts.json.bak").exists()

    def test_atomic_write(self, store, sample_script):
        store.add(sample_script)
        data = json.loads(store._path.read_text())
        assert "scripts" in data
