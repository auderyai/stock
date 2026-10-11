from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
import subprocess


_VERSION_RE = re.compile(r"xingAPI_Program\((20\d{2})[._-](\d{2})[._-](\d{2})\)", re.I)


class XingWorkerEnvironmentError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Xing32Status:
    available: bool
    python: Path
    bits: int = 0
    dll: Path | None = None
    dll_loadable: bool = False
    detail: str = ""


class Xing32Environment:
    """32bit DLL runtime only. COM registration is intentionally irrelevant."""

    def __init__(self, project_root: str | Path) -> None:
        self.root = Path(project_root).expanduser().resolve()
        self.python = self.root / ".venv_xing32" / "Scripts" / "python.exe"

    @staticmethod
    def install_root() -> Path:
        explicit = os.environ.get("LS_XING_INSTALL_ROOT", "").strip().strip('"')
        if explicit:
            p = Path(explicit)
            if (p / "XingAPI.dll").is_file():
                return p.resolve()

        base = Path(r"C:\LS_SEC")
        candidates = []
        if base.is_dir():
            for child in base.iterdir():
                if not child.is_dir():
                    continue
                m = _VERSION_RE.fullmatch(child.name)
                if m and (child / "XingAPI.dll").is_file():
                    candidates.append((tuple(map(int, m.groups())), child))
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1].resolve()
        return (base / "xingAPI").resolve()

    def inspect(self) -> Xing32Status:
        if not self.python.is_file():
            return Xing32Status(False, self.python, detail=".venv_xing32이 없습니다.")

        dll = self.install_root() / "XingAPI.dll"
        probe = r"""import ctypes,json,struct,sys
dll=sys.argv[1]
r={'bits':struct.calcsize('P')*8,'dll':dll,'dll_loadable':False,'detail':''}
try:
 lib=ctypes.WinDLL(dll)
 for n in ('ETK_Connect','ETK_Login','ETK_Request','ETK_ReleaseRequestData','ETK_ReleaseMessageData'):
  getattr(lib,n)
 r['dll_loadable']=True
except Exception as e:
 r['detail']=f'{type(e).__name__}: {e}'
print(json.dumps(r,ensure_ascii=False))"""
        try:
            cp = subprocess.run(
                [str(self.python), "-c", probe, str(dll)],
                cwd=self.root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
            if cp.returncode:
                return Xing32Status(False, self.python, dll=dll, detail=(cp.stderr or cp.stdout).strip())
            data = json.loads(cp.stdout.strip().splitlines()[-1])
        except Exception as exc:
            return Xing32Status(False, self.python, dll=dll, detail=f"{type(exc).__name__}: {exc}")

        bits = int(data.get("bits") or 0)
        loadable = bool(data.get("dll_loadable"))
        detail = str(data.get("detail") or "")
        available = bits == 32 and dll.is_file() and loadable
        return Xing32Status(available, self.python, bits, dll, loadable, detail)

    def require(self) -> Path:
        status = self.inspect()
        if not status.available:
            raise XingWorkerEnvironmentError(
                "32bit xingAPI DLL 실행환경을 사용할 수 없습니다. "
                "Python 32bit와 최신 LS XingAPI.dll을 확인하십시오. "
                f"상세: {status.detail or 'unknown'}"
            )
        return self.python

    def process_environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env["NEW_STOCK_ROOT"] = str(self.root)
        env["PYTHONPATH"] = str(self.root / "src")
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["NEW_STOCK_XING_WORKER"] = "1"
        env.setdefault("LS_XING_INSTALL_ROOT", str(self.install_root()))
        return env
