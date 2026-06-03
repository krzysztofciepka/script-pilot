from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scriptpilot.models import Script
from scriptpilot.paths import EXTENSIONS


class ScriptStore:
    """Per-file script persistence.

    Each script is stored as two files in ``self._dir``:
      - ``<id>.<ext>``       — the script body (extension determined by type)
      - ``<id>.meta.json``   — the Script model dumped without ``content``
    """

    def __init__(self, path: Path | None = None):
        self._dir = path or Path.home() / ".scriptpilot" / "scripts"
        self._scripts: dict[str, Script] = {}
        self._load()

    def list(self) -> list[Script]:
        return list(self._scripts.values())

    def get(self, script_id: str) -> Script | None:
        return self._scripts.get(script_id)

    def add(self, script: Script):
        self._write(script)
        self._scripts[script.id] = script

    def update(self, script: Script):
        self._write(script)
        # Drop any stale body files with a different extension (handles type change).
        new_ext = EXTENSIONS[script.type]
        for ext in EXTENSIONS.values():
            if ext == new_ext:
                continue
            (self._dir / f"{script.id}{ext}").unlink(missing_ok=True)
        self._scripts[script.id] = script

    def delete(self, script_id: str):
        for ext in EXTENSIONS.values():
            (self._dir / f"{script_id}{ext}").unlink(missing_ok=True)
        (self._dir / f"{script_id}.meta.json").unlink(missing_ok=True)
        self.transcript_path(script_id).unlink(missing_ok=True)
        self._scripts.pop(script_id, None)

    def path_for(self, script_id: str) -> Path:
        """On-disk path of the script body. Used by executor and editor."""
        script = self._scripts[script_id]
        return self._dir / f"{script_id}{EXTENSIONS[script.type]}"

    def transcript_path(self, script_id: str) -> Path:
        return self._dir / f"{script_id}.messages.json"

    def save_transcript(self, script_id: str, messages: list[dict]):
        self._atomic_write(
            self.transcript_path(script_id), json.dumps(messages, indent=2)
        )

    def load_transcript(self, script_id: str) -> list[dict]:
        path = self.transcript_path(script_id)
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return []

    def _load(self):
        self._dir.mkdir(parents=True, exist_ok=True)
        for meta_path in sorted(self._dir.glob("*.meta.json")):
            stem = meta_path.name[: -len(".meta.json")]
            try:
                meta = json.loads(meta_path.read_text())
                ext = EXTENSIONS[meta["type"]]
                body_path = self._dir / f"{stem}{ext}"
                if not body_path.exists():
                    continue  # orphan meta → skip
                content = body_path.read_text()
                meta["id"] = stem
                script = Script(**meta, content=content)
            except Exception:
                continue  # corrupt meta, missing/invalid type, model error → skip
            self._scripts[script.id] = script

    def _write(self, script: Script):
        body_path = self._dir / f"{script.id}{EXTENSIONS[script.type]}"
        meta_path = self._dir / f"{script.id}.meta.json"

        self._atomic_write(body_path, script.content)

        meta = script.model_dump(exclude={"content"})
        self._atomic_write(meta_path, json.dumps(meta, indent=2))

    def _atomic_write(self, target: Path, text: str):
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        try:
            with open(fd, "w") as f:
                f.write(text)
            Path(tmp).replace(target)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise
