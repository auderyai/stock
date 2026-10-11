"""Offline classification and export of unresolved OHLCV history failures."""

from __future__ import annotations

import csv
import datetime as dt
import json
from collections import Counter
from pathlib import Path
from typing import Any

from krx_research.collectors.common import normalize_date
from krx_research.database import ResearchStore

FAILURE_ACTIONS = {
    "adjusted_bounds_review": "조정주가 OHLC 범위 정책 검토 후 해당 종목만 보정",
    "invalid_trading_price": "0원·음수 원천행을 격리하고 대체 원천 확인",
    "malformed_provider_response": "원천 응답 형식 확인 후 해당 종목만 재수집",
    "incomplete_history": (
        "상장일·원천 제공 시작일을 확인하고 부족 구간만 재수집"
    ),
    "no_provider_data": (
        "종목 상태와 상장일을 확인한 뒤 원천 데이터 존재 여부 검토"
    ),
    "transient_network": "현재 프로그램으로 해당 종목만 재시도 가능",
    "adjusted_reference_unavailable": (
        "조정주가 비교 기준을 확보한 뒤 해당 종목만 재수집"
    ),
    "other": "오류 전문을 검토한 뒤 재수집 방법 결정",
}

TRANSIENT_MARKERS = (
    "timeout",
    "timed out",
    "connectionerror",
    "connection error",
    "connection reset",
    "remotedisconnected",
    "temporary failure",
    "temporarily unavailable",
    "too many requests",
    "status code 429",
    "http 429",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
)


def classify_history_failure(message: object) -> dict[str, object]:
    """Classify one stored provider error without changing the database."""

    text = str(message or "")
    lowered = text.lower()
    if "non-positive trading prices" in lowered:
        category = "invalid_trading_price"
    elif "outside audited rounding limits" in lowered:
        category = "adjusted_bounds_review"
    elif "malformed naver" in lowered or "invalid naver date-range" in lowered:
        category = "malformed_provider_response"
    elif (
        "incomplete ohlcv history" in lowered
        or "missing_early_history" in lowered
        or "missing_recent_history" in lowered
        or "unexplained_internal_gap" in lowered
    ):
        category = "incomplete_history"
    elif (
        "returned no ohlcv rows" in lowered
        or "no naver rows" in lowered
        or "no date-range history" in lowered
    ):
        category = "no_provider_data"
    elif any(marker in lowered for marker in TRANSIENT_MARKERS):
        category = "transient_network"
    elif (
        "no adjusted reference" in lowered
        or "adjusted-close mismatch" in lowered
        or "price basis" in lowered
    ):
        category = "adjusted_reference_unavailable"
    else:
        category = "other"
    return {
        "category": category,
        "retryable_now": category == "transient_network",
        "recommended_action": FAILURE_ACTIONS[category],
    }


def audit_history_failures(
    store: ResearchStore,
    start: object,
    end: object,
    *,
    market: str = "ALL",
) -> dict[str, Any]:
    """Build a compact offline audit for one requested history range."""

    start_date = normalize_date(start)
    end_date = normalize_date(end)
    records = store.list_unresolved_ohlcv_history_failures(
        start_date,
        end_date,
        market=market,
    )
    categories: Counter[str] = Counter()
    retryable: list[str] = []
    review_required: list[str] = []
    attempted_failure_rows = 0
    for record in records:
        classification = classify_history_failure(record.get("error_message"))
        record.update(classification)
        category = str(classification["category"])
        categories[category] += 1
        attempted_failure_rows += int(record.get("failure_count") or 0)
        if classification["retryable_now"]:
            retryable.append(str(record["ticker"]))
        else:
            review_required.append(str(record["ticker"]))

    return {
        "status": "clean" if not records else "review_required",
        "requested_start": start_date.isoformat(),
        "requested_end": end_date.isoformat(),
        "market": market.upper(),
        "unresolved_failure_count": len(records),
        "attempted_failure_rows": attempted_failure_rows,
        "category_counts": dict(sorted(categories.items())),
        "retryable_now_count": len(retryable),
        "retryable_now_tickers": retryable,
        "review_required_count": len(review_required),
        "review_required_tickers": review_required,
        "records": records,
        "network_used": False,
        "krx_login_used": False,
    }


def write_history_failure_audit(
    audit: dict[str, Any],
    output_directory: str | Path,
    *,
    generated_at: dt.datetime | None = None,
) -> dict[str, str]:
    """Write UTF-8 JSON and Excel-friendly CSV audit artifacts."""

    directory = Path(output_directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = generated_at or dt.datetime.now().astimezone()
    stamp = timestamp.strftime("%Y%m%d_%H%M%S")
    json_path = directory / f"history_failure_audit_{stamp}.json"
    csv_path = directory / f"history_failure_audit_{stamp}.csv"

    document = {**audit, "generated_at": timestamp.isoformat(timespec="seconds")}
    json_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    fieldnames = [
        "ticker",
        "name",
        "market",
        "category",
        "retryable_now",
        "recommended_action",
        "failure_count",
        "first_failed_at",
        "last_failed_at",
        "stored_rows",
        "stored_start",
        "stored_end",
        "latest_run_id",
        "requested_start",
        "requested_end",
        "error_message",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(document["records"])
    return {"json_path": str(json_path), "csv_path": str(csv_path)}
