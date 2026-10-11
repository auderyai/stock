from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from krx_research.project import STOCK_ROOT


REQUIRED_TRS = ("t8424", "t8436", "t1516", "t8429", "t8451", "t1702")
_VERSION_RE = re.compile(r"xingAPI_Program\((20\d{2})[._-](\d{2})[._-](\d{2})\)", re.I)


@dataclass(frozen=True, slots=True)
class XingDllReadiness:
    project_root: Path
    install_root: Path
    dll_path: Path
    transport_ready: bool
    schemas: Mapping[str, Path | None]

    @classmethod
    def discover(cls) -> "XingDllReadiness":
        project = STOCK_ROOT
        install = cls._discover_install_root()
        dll = install / "XingAPI.dll"
        schema_root = project / "resources" / "xing" / "schemas"

        schemas: dict[str, Path | None] = {}
        for tr in REQUIRED_TRS:
            p = schema_root / f"{tr}.json"
            schemas[tr] = p if p.is_file() else None

        worker = project / ".venv_xing32" / "Scripts" / "python.exe"
        transport_ready = dll.is_file() and worker.is_file()

        return cls(project, install, dll, transport_ready, schemas)

    @staticmethod
    def _discover_install_root() -> Path:
        explicit = os.getenv("LS_XING_INSTALL_ROOT", "").strip().strip('"')
        if explicit:
            p = Path(explicit).expanduser()
            if (p / "XingAPI.dll").is_file():
                return p.resolve()

        base = Path(r"C:\LS_SEC")
        dated: list[tuple[tuple[int, int, int], Path]] = []
        if base.is_dir():
            try:
                for child in base.iterdir():
                    if not child.is_dir():
                        continue
                    m = _VERSION_RE.fullmatch(child.name)
                    if m and (child / "XingAPI.dll").is_file():
                        dated.append((tuple(map(int, m.groups())), child))
            except OSError:
                pass
        if dated:
            dated.sort(key=lambda item: item[0], reverse=True)
            return dated[0][1].resolve()

        return (base / "xingAPI").resolve()

    @property
    def missing_schemas(self) -> tuple[str, ...]:
        return tuple(tr for tr, path in self.schemas.items() if path is None)

    @property
    def runtime_ready(self) -> bool:
        return self.transport_ready and not self.missing_schemas

    def require_runtime_ready(self) -> None:
        if not self.transport_ready:
            raise RuntimeError("xingAPI DLL transport가 준비되지 않았습니다.")
        if self.missing_schemas:
            raise RuntimeError(
                "xingAPI DLL packet schema가 준비되지 않았습니다: "
                + ", ".join(self.missing_schemas)
            )
