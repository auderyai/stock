from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from krx_research.project import STOCK_ROOT

REQUIRED_TRS = ("t8424", "t8436", "t1516", "t8429", "t8451", "t1702")
RES_TRS = ("t8424", "t8436", "t8429", "t8451")
JSON_SCHEMA_TRS = ("t1516", "t1702")


@dataclass(frozen=True, slots=True)
class UnifiedSchemaReadiness:
    project_root: Path

    @classmethod
    def discover(cls) -> "UnifiedSchemaReadiness":
        return cls(STOCK_ROOT)

    @property
    def current_res_dir(self) -> Path:
        return self.project_root / "resources" / "xing" / "current_res"

    @property
    def schema_dir(self) -> Path:
        return self.project_root / "resources" / "xing" / "schemas"

    def tr_ready(self, tr: str) -> bool:
        if tr in RES_TRS:
            return (self.current_res_dir / f"{tr}.res").is_file()
        if tr in JSON_SCHEMA_TRS:
            return (self.schema_dir / f"{tr}.json").is_file()
        return False

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(tr for tr in REQUIRED_TRS if not self.tr_ready(tr))

    @property
    def ready(self) -> bool:
        return not self.missing

    def require_ready(self) -> None:
        if self.missing:
            raise RuntimeError("xingAPI schema 미준비: " + ", ".join(self.missing))
