from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from krx_research.project import STOCK_ROOT


_VERSION_RE = re.compile(r"xingAPI_Program\((20\d{2})[._-](\d{2})[._-](\d{2})\)", re.I)
CURRENT_RES_TRS = ("t8424", "t8436", "t8429", "t8451")
BLOCKED_TRS = ("t1516", "t1702")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True, slots=True)
class ManagedResRecord:
    tr: str
    source: Path
    target: Path
    sha256: str
    variant: str


class CurrentXingResManager:
    def __init__(self, project_root: str | Path | None = None) -> None:
        self.project_root = (
            Path(project_root).resolve()
            if project_root
            else STOCK_ROOT
        )
        self.install_root = self._discover_install_root()
        self.source_res = self.install_root / "Res"
        self.managed_res = self.project_root / "resources" / "xing" / "current_res"
        self.manifest_path = self.managed_res / "manifest.json"

    @staticmethod
    def _discover_install_root() -> Path:
        explicit = os.getenv("LS_XING_INSTALL_ROOT", "").strip().strip('"')
        if explicit:
            p = Path(explicit).expanduser()
            if p.is_dir():
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

        legacy = base / "xingAPI"
        return legacy.resolve()

    def discover(self) -> dict[str, list[Path]]:
        result: dict[str, list[Path]] = {}
        for tr in CURRENT_RES_TRS:
            candidates = []
            for name in (f"{tr}.res", f"{tr}_2.res"):
                p = self.source_res / name
                if p.is_file():
                    candidates.append(p)
            result[tr] = candidates
        return result

    def import_current(self) -> list[ManagedResRecord]:
        discovered = self.discover()
        missing = [tr for tr, files in discovered.items() if not files]
        if missing:
            raise RuntimeError(
                "최신 설치본에서 현재 사용 가능한 RES가 누락되었습니다: "
                + ", ".join(missing)
            )

        self.managed_res.mkdir(parents=True, exist_ok=True)
        records: list[ManagedResRecord] = []

        for tr, files in discovered.items():
            for source in files:
                target = self.managed_res / source.name
                shutil.copy2(source, target)
                records.append(
                    ManagedResRecord(
                        tr=tr,
                        source=source,
                        target=target,
                        sha256=sha256(target),
                        variant="_2" if source.stem.endswith("_2") else "base",
                    )
                )

        manifest = {
            "install_root": str(self.install_root),
            "source_res": str(self.source_res),
            "managed_res": str(self.managed_res),
            "current_res_trs": list(CURRENT_RES_TRS),
            "blocked_trs": list(BLOCKED_TRS),
            "files": [
                {
                    "tr": r.tr,
                    "variant": r.variant,
                    "source": str(r.source),
                    "target": str(r.target),
                    "sha256": r.sha256,
                }
                for r in records
            ],
        }
        self.manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return records

    def status(self) -> dict[str, object]:
        discovered = self.discover()
        return {
            "install_root": self.install_root,
            "source_res": self.source_res,
            "managed_res": self.managed_res,
            "discovered": discovered,
            "blocked": BLOCKED_TRS,
            "manifest": self.manifest_path if self.manifest_path.is_file() else None,
        }
