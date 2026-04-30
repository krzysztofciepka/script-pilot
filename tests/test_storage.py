import json
import pytest
from pathlib import Path

from scriptpilot.models import Script, ScriptArg
from scriptpilot.storage import ScriptStore


@pytest.fixture
def store(tmp_path):
    return ScriptStore(tmp_path / "scripts")


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
        assert result.content == "echo hello"

    def test_add_persists_to_disk(self, tmp_path, sample_script):
        s1 = ScriptStore(tmp_path / "scripts")
        s1.add(sample_script)
        s2 = ScriptStore(tmp_path / "scripts")
        loaded = s2.get(sample_script.id)
        assert loaded is not None
        assert loaded.name == "hello"
        assert loaded.content == "echo hello"

    def test_list_returns_all(self, store):
        s1 = Script(name="a", description="a", type="bash", content="echo a")
        s2 = Script(name="b", description="b", type="python", content="print('b')")
        s3 = Script(name="c", description="c", type="js", content="console.log('c')")
        store.add(s1)
        store.add(s2)
        store.add(s3)
        assert len(store.list()) == 3

    def test_update_changes_name(self, store, sample_script):
        store.add(sample_script)
        sample_script.name = "updated"
        store.update(sample_script)
        result = store.get(sample_script.id)
        assert result.name == "updated"

    def test_update_changes_content(self, store, sample_script):
        store.add(sample_script)
        sample_script.content = "echo NEW"
        store.update(sample_script)

        # Reload from disk and verify content was written.
        store2 = ScriptStore(store._dir)
        assert store2.get(sample_script.id).content == "echo NEW"

    def test_update_changes_type_renames_body_file(self, store, sample_script):
        # Start as bash → file lands at <id>.sh
        store.add(sample_script)
        old_path = store._dir / f"{sample_script.id}.sh"
        assert old_path.exists()

        # Change type to python; old .sh must be gone, new .py must exist.
        sample_script.type = "python"
        sample_script.content = "print('hi')"
        store.update(sample_script)

        new_path = store._dir / f"{sample_script.id}.py"
        assert new_path.exists()
        assert not old_path.exists()
        assert new_path.read_text() == "print('hi')"

    def test_delete(self, store, sample_script):
        store.add(sample_script)
        body_path = store._dir / f"{sample_script.id}.sh"
        meta_path = store._dir / f"{sample_script.id}.meta.json"
        assert body_path.exists() and meta_path.exists()

        store.delete(sample_script.id)

        assert store.get(sample_script.id) is None
        assert store.list() == []
        assert not body_path.exists()
        assert not meta_path.exists()

    def test_get_nonexistent_returns_none(self, store):
        assert store.get("nonexistent") is None

    def test_creates_directory_on_init(self, tmp_path):
        target = tmp_path / "deeply" / "nested" / "scripts"
        ScriptStore(target)
        assert target.exists()

    def test_add_writes_body_and_meta_files(self, store, sample_script):
        store.add(sample_script)
        body = store._dir / f"{sample_script.id}.sh"
        meta = store._dir / f"{sample_script.id}.meta.json"
        assert body.exists()
        assert meta.exists()
        assert body.read_text() == "echo hello"

    def test_meta_json_excludes_content(self, store, sample_script):
        store.add(sample_script)
        meta = store._dir / f"{sample_script.id}.meta.json"
        data = json.loads(meta.read_text())
        assert "content" not in data
        assert data["name"] == "hello"
        assert data["type"] == "bash"
        assert data["id"] == sample_script.id

    def test_path_for_returns_body_path(self, store, sample_script):
        store.add(sample_script)
        path = store.path_for(sample_script.id)
        assert path == store._dir / f"{sample_script.id}.sh"
        assert path.exists()

    def test_path_for_unknown_id_raises(self, store):
        with pytest.raises(KeyError):
            store.path_for("does-not-exist")

    def test_orphan_meta_skipped(self, tmp_path, sample_script):
        # Create a meta file with no matching body.
        store = ScriptStore(tmp_path / "scripts")
        store.add(sample_script)
        body = store._dir / f"{sample_script.id}.sh"
        body.unlink()  # leave only the meta

        # New instance must not raise and must skip the orphan.
        store2 = ScriptStore(tmp_path / "scripts")
        assert store2.list() == []

    def test_orphan_body_skipped(self, tmp_path):
        # Body file with no meta sibling — never even considered.
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "stray.sh").write_text("echo stray")

        store = ScriptStore(scripts_dir)
        assert store.list() == []

    def test_corrupt_meta_skipped(self, tmp_path, sample_script):
        # One good script + one broken meta. Good one must still load.
        store = ScriptStore(tmp_path / "scripts")
        store.add(sample_script)
        (store._dir / "broken.meta.json").write_text("{not valid json")

        store2 = ScriptStore(tmp_path / "scripts")
        loaded = store2.list()
        assert len(loaded) == 1
        assert loaded[0].id == sample_script.id

    def test_meta_with_args_round_trips(self, tmp_path):
        store = ScriptStore(tmp_path / "scripts")
        script = Script(
            name="args",
            description="has args",
            type="python",
            content="import sys; print(sys.argv)",
            args=[
                ScriptArg(name="x", type="string", required=True),
                ScriptArg(name="y", type="integer", required=False, default=7),
            ],
            timeout=30,
            favorite=True,
        )
        store.add(script)

        store2 = ScriptStore(tmp_path / "scripts")
        loaded = store2.get(script.id)
        assert loaded is not None
        assert loaded.timeout == 30
        assert loaded.favorite is True
        assert len(loaded.args) == 2
        assert loaded.args[0].name == "x"
        assert loaded.args[1].default == 7
