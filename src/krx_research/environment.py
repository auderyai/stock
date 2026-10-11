"""Project-local environment resolution for C:\\stock."""
from __future__ import annotations

import os
from pathlib import Path


class EnvironmentResolver:
    """Resolve C:\\stock local and process environment values without exposing secrets."""

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).expanduser().resolve()

    @staticmethod
    def _read(path: Path) -> dict[str, str]:
        values: dict[str, str] = {}
        if not path.is_file():
            return values
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError(f".env {number}행: NAME=VALUE 형식이 아닙니다.")
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key.strip()] = value
        return values

    def shared_env_path(self) -> Path | None:
        """External shared .env files are disabled; C:\\stock\\.env is canonical."""
        return None

    def values(self) -> dict[str, str]:
        values = self._read(self.project_root / ".env")
        values.update({key: value for key, value in os.environ.items() if value is not None})
        return values

    def sources(self) -> tuple[Path, ...]:
        return (self.project_root / ".env",)
