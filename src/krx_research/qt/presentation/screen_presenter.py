from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
from .column_catalog import COLUMN_LABELS, SCREEN_BASE_COLUMNS, label_for


@dataclass(frozen=True, slots=True)
class PresentedScreen:
    frame: pd.DataFrame
    labels: dict[str, str]
    heading: str


class ScreenResultPresenter:
    """Converts internal data fields into a stable Korean presentation model."""

    def present(self, dataset) -> PresentedScreen:
        source = dataset.rows.drop(columns=["score"], errors="ignore").copy()
        screen_type = str(getattr(dataset, "screen_type", ""))
        columns = [column for column in SCREEN_BASE_COLUMNS if column in source.columns]

        if screen_type == "near_high_52w" and "high_52w" in source.columns:
            columns.append("high_52w")
        if screen_type == "ema_similarity":
            for column in ("ema_order_similarity_pct", "ema_max_gap_difference_pct", "ema_shape_distance_pct", "ema_exact_array_match"):
                if column in source.columns and column not in columns:
                    columns.append(column)
        # Preserve useful columns that are already known to the Korean catalog.
        for column in source.columns:
            if column not in columns and column in COLUMN_LABELS:
                columns.append(column)
        frame = source.loc[:, columns].copy() if columns else source.copy()
        if "ticker" in frame.columns:
            frame["ticker"] = frame["ticker"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
        if "stock_code" in frame.columns:
            frame["stock_code"] = frame["stock_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
        if "estimated_trading_value" in frame.columns:
            frame["estimated_trading_value"] = pd.to_numeric(frame["estimated_trading_value"], errors="coerce") / 100_000_000.0
        labels = {column: label_for(column) for column in frame.columns}

        run = dict(getattr(dataset, "run", {}) or {})
        period_start = str(run.get("period_start") or run.get("as_of_date") or "")
        period_end = str(run.get("period_end") or run.get("as_of_date") or "")
        source_mode = str(run.get("data_source_mode") or "DATABASE").upper()
        source_label = "실시간" if "REAL" in source_mode else "데이터베이스"
        if screen_type == "high_52w":
            # User requested the daily 52-week-high heading without a redundant 기준일 suffix.
            period_text = ""
        else:
            period_text = f"기준일 {period_end}" if period_start == period_end else f"기간 {period_start} ~ {period_end}"
        heading = f"{dataset.title} · {source_label} · {period_text}" if period_text.strip() else f"{dataset.title} · {source_label}"
        return PresentedScreen(frame=frame, labels=labels, heading=heading)
