from __future__ import annotations

import pandas as pd


class PatternResultPresenter:
    """Applies one deterministic ranking and column order to every pattern result."""

    IDENTITY = ("rank", "stock_code", "stock_name")
    SIMILARITY = (
        "similarity_pct", "price_similarity_pct", "moving_average_similarity_pct",
        "moving_average_gap_similarity_pct", "volume_similarity_pct",
    )
    EVIDENCE = (
        "moving_average", "pattern_start", "pattern_end", "pattern_days",
        "period_return_pct", "trend_slope_pct", "range_position_pct", "period_range_pct",
        "maximum_gap_pct", "history_range_position_pct",
    )
    LATEST = (
        "db_recent_date", "rise_pct", "open", "high", "low", "close",
        "market_cap_eok", "trading_value_eok",
    )

    def present(self, rows: list[dict] | pd.DataFrame) -> pd.DataFrame:
        frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
        if frame.empty:
            return frame
        if "similarity_pct" not in frame:
            frame["similarity_pct"] = pd.NA
        reference = frame.get("pattern_role", pd.Series(index=frame.index, dtype=str)).eq("기준 패턴")
        frame = frame.assign(_reference=reference, _code=frame.stock_code.astype(str).str.zfill(6))
        frame = frame.sort_values(
            ["_reference", "similarity_pct", "_code"],
            ascending=[False, False, True], kind="mergesort", na_position="last",
        ).reset_index(drop=True)
        rank, ranks = 0, []
        for is_reference in frame._reference:
            if not is_reference: rank += 1
            ranks.append(0 if is_reference else rank)
        frame.insert(1 if "pattern_role" in frame else 0, "rank", ranks)
        frame = frame.drop(columns=["_reference", "_code"])
        frame["stock_code"] = frame.stock_code.astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
        order = (("pattern_role",) if "pattern_role" in frame else ()) + self.IDENTITY + self.SIMILARITY + self.EVIDENCE + self.LATEST
        return frame.loc[:, [column for column in order if column in frame.columns]]
