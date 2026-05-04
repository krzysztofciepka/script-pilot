import json
import pytest
from pathlib import Path

from scriptpilot.models import OutputLine, RunRecord
from scriptpilot.history import HistoryStore


@pytest.fixture
def store(tmp_path):
    return HistoryStore(tmp_path / "history.json")


@pytest.fixture
def sample_record():
    return RunRecord(
        script_id="abc",
        script_name="test script",
        timestamp="2026-04-15T10:30:00",
        exit_code=0,
        timed_out=False,
        duration=1.5,
        lines=[OutputLine("stdout", "hello world")],
    )


class TestHistoryStore:
    def test_list_all_empty(self, store):
        assert store.list_all() == []

    def test_add_and_list_all(self, store, sample_record):
        store.add(sample_record)
        records = store.list_all()
        assert len(records) == 1
        assert records[0].script_id == "abc"
        assert records[0].lines == [OutputLine("stdout", "hello world")]

    def test_list_all_newest_first(self, store):
        r1 = RunRecord(
            script_id="a", script_name="a",
            timestamp="2026-04-15T10:00:00",
            exit_code=0, timed_out=False, duration=1.0,
            lines=[OutputLine("stdout", "first")],
        )
        r2 = RunRecord(
            script_id="a", script_name="a",
            timestamp="2026-04-15T11:00:00",
            exit_code=0, timed_out=False, duration=1.0,
            lines=[OutputLine("stdout", "second")],
        )
        store.add(r1)
        store.add(r2)
        records = store.list_all()
        assert records[0].timestamp == "2026-04-15T11:00:00"
        assert records[1].timestamp == "2026-04-15T10:00:00"

    def test_list_for_script(self, store):
        r1 = RunRecord(
            script_id="a", script_name="script a",
            timestamp="2026-04-15T10:00:00",
            exit_code=0, timed_out=False, duration=1.0,
            lines=[OutputLine("stdout", "a")],
        )
        r2 = RunRecord(
            script_id="b", script_name="script b",
            timestamp="2026-04-15T10:00:00",
            exit_code=0, timed_out=False, duration=1.0,
            lines=[OutputLine("stdout", "b")],
        )
        store.add(r1)
        store.add(r2)
        records = store.list_for_script("a")
        assert len(records) == 1
        assert records[0].script_name == "script a"

    def test_persists_to_disk(self, store, sample_record):
        store.add(sample_record)
        store2 = HistoryStore(store._path)
        assert len(store2.list_all()) == 1
        assert store2.list_all()[0].lines == [OutputLine("stdout", "hello world")]

    def test_evicts_oldest_at_cap(self, store):
        for i in range(105):
            r = RunRecord(
                script_id="x", script_name="x",
                timestamp=f"2026-04-15T{i:05d}",
                exit_code=0, timed_out=False, duration=1.0,
                lines=[OutputLine("stdout", f"run {i}")],
            )
            store.add(r)
        records = store.list_all()
        assert len(records) == 100
        timestamps = [r.timestamp for r in records]
        assert "2026-04-15T00000" not in timestamps
        assert "2026-04-15T00104" in timestamps

    def test_creates_parent_directory(self, tmp_path):
        path = tmp_path / "subdir" / "history.json"
        store = HistoryStore(path)
        r = RunRecord(
            script_id="x", script_name="x",
            timestamp="2026-04-15T10:00:00",
            exit_code=0, timed_out=False, duration=1.0,
            lines=[OutputLine("stdout", "x")],
        )
        store.add(r)
        assert path.exists()

    def test_corrupted_json_backs_up_and_resets(self, tmp_path):
        path = tmp_path / "history.json"
        path.write_text("{invalid json!!!")
        store = HistoryStore(path)
        assert store.list_all() == []
        assert (tmp_path / "history.json.bak").exists()
