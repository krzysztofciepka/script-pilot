from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scriptpilot.models import Script


class ScriptStore:
    """JSON-based script persistence."""

    def __init__(self, path: Path | None = None):
        self._path = path or Path.home() / ".scriptpilot" / "scripts.json"
        self._scripts: dict[str, Script] = {}
        self._load()

    def _load(self):
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            for item in data.get("scripts", []):
                script = Script(**item)
                self._scripts[script.id] = script
        except (json.JSONDecodeError, Exception):
            backup = self._path.with_suffix(".json.bak")
            self._path.rename(backup)

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"scripts": [s.model_dump() for s in self._scripts.values()]}
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

    def list(self) -> list[Script]:
        return list(self._scripts.values())

    def get(self, script_id: str) -> Script | None:
        return self._scripts.get(script_id)

    def add(self, script: Script):
        self._scripts[script.id] = script
        self._save()

    def update(self, script: Script):
        self._scripts[script.id] = script
        self._save()

    def delete(self, script_id: str):
        self._scripts.pop(script_id, None)
        self._save()
