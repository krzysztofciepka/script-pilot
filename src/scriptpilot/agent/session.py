from __future__ import annotations

import shutil
from pathlib import Path

from scriptpilot.agent.prompts import system_prompt
from scriptpilot.models import Script, ScriptArg
from scriptpilot.paths import EXTENSIONS

# Fields on Script the agent may patch via update_script.
_PATCHABLE = {
    "name",
    "type",
    "args",
    "env",
    "timeout",
    "cwd",
    "description",
    "arg_style",
    "tags",
}


class ChatSession:
    """A single conversational script-building session.

    Holds the in-memory draft ``Script``, a working directory containing the
    draft body file (so the ``bash`` tool can ``cat`` it), and the running
    message list (system prompt first).
    """

    def __init__(self, draft: Script, work_dir: Path):
        self.draft = draft
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.messages: list[dict] = [{"role": "system", "content": system_prompt()}]
        self._write_draft()

    @classmethod
    def new(cls, work_dir: Path) -> "ChatSession":
        draft = Script(name="", description="", type="bash", content="")
        return cls(draft, work_dir)

    @classmethod
    def from_script(cls, script: Script, work_dir: Path) -> "ChatSession":
        draft = Script(**script.model_dump())
        return cls(draft, work_dir)

    @property
    def draft_path(self) -> Path:
        return self.work_dir / f"script{EXTENSIONS[self.draft.type]}"

    def _write_draft(self):
        self.draft_path.write_text(self.draft.content)

    def apply_update(self, code: str | None, meta_patch: dict | None) -> str:
        old_path = self.draft_path
        data = self.draft.model_dump()
        if meta_patch:
            for key, value in meta_patch.items():
                if key not in _PATCHABLE:
                    continue
                if key == "args":
                    value = [ScriptArg(**a) if isinstance(a, dict) else a for a in value]
                data[key] = value
        if code is not None:
            data["content"] = code
        self.draft = Script(**data)

        # Type change renames the body file.
        if self.draft_path != old_path:
            old_path.unlink(missing_ok=True)
        self._write_draft()
        return self._summary()

    def _summary(self) -> str:
        d = self.draft
        return (
            f"draft updated: name={d.name!r} type={d.type} "
            f"code_len={len(d.content)} args={[a.name for a in d.args]} "
            f"env_keys={list(d.env)}"
        )

    def clear(self):
        self.messages = [{"role": "system", "content": system_prompt()}]

    def to_script(self) -> Script:
        return Script(**self.draft.model_dump())

    def cleanup(self):
        shutil.rmtree(self.work_dir, ignore_errors=True)
