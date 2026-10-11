"""Stable, idempotent audit records for exceptional provider observations."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping

from krx_research.collectors.common import normalize_date, normalize_ticker


def quality_event_records(events: Iterable[Mapping[str, object]]) -> list[tuple[object, ...]]:
    records = []
    for event in events:
        action = event["action"]
        if action not in {
            "no_trade_placeholder",
            "bounds_adjusted_1krw",
            "bounds_adjusted_provider_envelope",
            "bounds_adjusted_sub1000_rounding",
            "bounds_adjusted_tick",
            "nonpositive_price_row_excluded",
        }:
            raise ValueError("Unknown OHLCV quality action")
        raw = event["raw"]
        normalized = event["normalized"]
        for values in (raw, normalized):
            if values is None:
                continue
            if not isinstance(values, Mapping) or set(values) != {
                "open",
                "high",
                "low",
                "close",
                "volume",
            }:
                raise ValueError("Invalid audit OHLCV values")
            if not all(math.isfinite(float(value)) for value in values.values()):
                raise ValueError("Non-finite audit values")
        excluded_actions = {
            "no_trade_placeholder",
            "nonpositive_price_row_excluded",
        }
        if raw is None or (normalized is None) != (action in excluded_actions):
            raise ValueError("Inconsistent OHLCV quality event")
        ticker = normalize_ticker(event["ticker"])
        trade_date = normalize_date(event["trade_date"]).isoformat()
        raw_json = json.dumps(raw, sort_keys=True, allow_nan=False, separators=(",", ":"))
        normalized_json = (
            None
            if normalized is None
            else json.dumps(normalized, sort_keys=True, allow_nan=False, separators=(",", ":"))
        )
        source = str(event["source"])
        version = int(event["policy_version"])
        identity = json.dumps(
            [ticker, trade_date, source, action, version, raw_json, normalized_json],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        records.append(
            (
                hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                ticker,
                trade_date,
                source,
                str(event["source_url"]),
                action,
                version,
                raw_json,
                normalized_json,
                str(event["retrieved_at"]),
            )
        )
    return records
