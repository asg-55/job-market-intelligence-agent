from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from threading import RLock
from typing import Any

from .config import CandidateProfile


class ProfileStore:
    """Atomically persists and hot-reloads the private candidate profile."""

    def __init__(self, path: str | Path, template_path: str | Path | None = None) -> None:
        self.path = Path(path)
        self.template_path = Path(template_path) if template_path else None
        self._lock = RLock()
        self._ensure_exists()

    def _ensure_exists(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            return
        if self.template_path and self.template_path.exists():
            shutil.copyfile(self.template_path, self.path)
        else:
            self.save(CandidateProfile())

    def load(self) -> CandidateProfile:
        with self._lock:
            self._ensure_exists()
            return CandidateProfile.from_file(self.path)

    def save(self, profile: CandidateProfile) -> CandidateProfile:
        validated = CandidateProfile.model_validate(profile)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
            with temporary.open("w", encoding="utf-8", newline="\n") as file:
                json.dump(validated.model_dump(mode="json"), file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        return validated.model_copy(deep=True)

    def patch(self, changes: dict[str, Any]) -> CandidateProfile:
        current = self.load().model_dump(mode="json")
        current.update(changes)
        return self.save(CandidateProfile.model_validate(current))
