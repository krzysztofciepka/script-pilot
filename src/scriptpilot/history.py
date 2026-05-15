from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scriptpilot.models import RunRecord

MAX_RECORDS = 100


class HistoryStore:
    """JSON-based run history persistence."""

    def __init__(self, path: Path | None = None):
        self._path = path or Path.home() / ".scriptpilot" / "history.json"
        self._records: list[RunRecord] = []
        self._load()

    def _load(self):
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            for item in data.get("records", []):
                self._records.append(RunRecord(**item))
        except (json.JSONDecodeError, Exception):
            backup = self._path.with_suffix(".json.bak")
            self._path.rename(backup)

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"records": [r.model_dump() for r in self._records]}
        fd, tmp = tempfile.mkstemp(
            dir=self._path.parent, suffix=".tmp"
        )
        try:
            with open(fd, "w") as f:
                json.dump(data, f, indent=2)
            Path(tmp).replace(self._path)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise

    def add(self, record: RunRecord):
        """Append a run record, evicting oldest if over cap."""
        self._records.append(record)
        if len(self._records) > MAX_RECORDS:
            self._records = self._records[-MAX_RECORDS:]
        self._save()

    def list_all(self) -> list[RunRecord]:
        """Return all records, newest first."""
        return list(reversed(self._records))

    def list_for_script(self, script_id: str) -> list[RunRecord]:
        """Return records for a specific script, newest first."""
        return [
            r for r in reversed(self._records)
            if r.script_id == script_id
        ]


def format_history_row(r: RunRecord) -> str:
    """Render a single RunRecord as a one-line label for the history modal."""
    ts = r.timestamp.replace("T", " ").split(".")[0].split("+")[0]
    if r.cancelled:
        status = "[yellow]cancelled[/yellow]"
    elif r.timed_out:
        status = "[red]timed out[/red]"
    elif r.exit_code == 0:
        status = "[green]exit 0[/green]"
    else:
        status = f"[red]exit {r.exit_code}[/red]"
    return f"{ts}  {r.script_name:<22.22}  {status}  {r.duration:.1f}s"
