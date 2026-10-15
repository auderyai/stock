from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TableSpec:
    relation: str
    key_columns: tuple[str, ...]
    snapshot_days: int | None = None
    delta_date_column: str | None = None
    full_in_delta: bool = False

    @property
    def schema(self) -> str:
        return self.relation.split(".", 1)[0]

    @property
    def table(self) -> str:
        return self.relation.split(".", 1)[1]


WORKER_TABLES: tuple[TableSpec, ...] = (
    TableSpec("market_core.cloud_stock_universe", ("stock_code",), full_in_delta=True),
    TableSpec(
        "market_core.venue_ohlcv_daily",
        ("venue", "stock_code", "trade_date"),
        120,
        "trade_date",
    ),
    TableSpec(
        "market_core.ls_investor_t1702_raw",
        ("stock_code", "trade_date", "metric_code", "side_code", "exchange_code"),
        120,
        "trade_date",
    ),
    TableSpec(
        "market_core.ls_investor_t1702_checkpoint",
        ("stock_code", "trade_date", "exchange_code"),
        120,
        "trade_date",
    ),
)


ARCHIVE_FORMAT_VERSION = 1
