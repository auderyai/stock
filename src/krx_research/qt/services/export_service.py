from __future__ import annotations
from pathlib import Path
import pandas as pd

class ExcelExportService:
    """Owns result serialization; widgets never write files directly."""
    def export(self, frame: pd.DataFrame, path: str | Path) -> Path:
        if frame is None or frame.empty:
            raise ValueError("저장할 결과가 없습니다.")
        target = Path(path)
        if target.suffix.lower() != ".xlsx":
            target = target.with_suffix(".xlsx")
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.to_excel(target, index=False)
        return target
