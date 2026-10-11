from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from krx_research.project import STOCK_ROOT


_VERSION_RE = re.compile(r"xingAPI_Program\((20\d{2})[._-](\d{2})[._-](\d{2})\)", re.I)


@dataclass(frozen=True, slots=True)
class XingInstallLayout:
    root: Path
    dll: Path
    header_root: Path
    res_root: Path

    REQUIRED_TRS = ("t8424", "t8436", "t1516", "t8429", "t8451", "t1702")

    @staticmethod
    def project_root() -> Path:
        return STOCK_ROOT

    @classmethod
    def discover_root(cls) -> Path:
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
            dated.sort(key=lambda x: x[0], reverse=True)
            return dated[0][1].resolve()

        legacy = base / "xingAPI"
        if (legacy / "XingAPI.dll").is_file():
            return legacy.resolve()

        return (base / "xingAPI_Program(2025.06.07)").resolve()

    @classmethod
    def discover(cls) -> "XingInstallLayout":
        root = cls.discover_root()
        return cls(root, root / "XingAPI.dll", root / "Header", root / "Res")

    def header_files(self) -> tuple[Path, ...]:
        if not self.header_root.is_dir():
            return ()
        return tuple(sorted(p for p in self.header_root.rglob("*.h") if p.is_file()))

    def res_files(self) -> tuple[Path, ...]:
        if not self.res_root.is_dir():
            return ()
        return tuple(sorted(p for p in self.res_root.rglob("*.res") if p.is_file()))

    def required_res(self) -> dict[str, Path | None]:
        result: dict[str, Path | None] = {}
        files = {p.name.lower(): p for p in self.res_files()}
        for tr in self.REQUIRED_TRS:
            result[tr] = files.get(f"{tr}.res".lower())
        return result

    def xing32_python(self) -> Path:
        return self.project_root() / ".venv_xing32" / "Scripts" / "python.exe"

    def probe_exports_32bit(self) -> dict[str, Any]:
        py = self.xing32_python()
        helper = self.project_root() / "scripts" / "probe_xing_dll_exports_32.py"
        if not py.is_file():
            return {"ok": False, "error": f"32bit Python 없음: {py}"}
        if not helper.is_file():
            return {"ok": False, "error": f"helper 없음: {helper}"}
        try:
            cp = subprocess.run(
                [str(py), str(helper), str(self.dll)],
                cwd=self.project_root(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        if cp.returncode != 0:
            return {"ok": False, "error": (cp.stderr or cp.stdout).strip()}
        try:
            return json.loads(cp.stdout.strip().splitlines()[-1])
        except Exception as exc:
            return {"ok": False, "error": f"JSON parse 실패: {exc}; raw={cp.stdout!r}"}
