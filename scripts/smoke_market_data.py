from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from krx_research.collectors import compare_ohlcv_sources, fetch_security_master


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live login-free market-data checks.")
    parser.add_argument("--ticker", default="005930")
    parser.add_argument("--start", default="2026-08-24")
    parser.add_argument("--end", default="2026-08-31")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    master = fetch_security_master()
    comparison = compare_ohlcv_sources(args.ticker, args.start, args.end)
    classified = int(master["industry"].notna().sum())
    candidate = int(master["industry"].isna().sum())

    result = {
        "security_master_rows": len(master),
        "industry_classified": classified,
        "industry_candidates": candidate,
        "listing_source": master["source"].iloc[0],
        "filtered_invalid_ticker_codes": master.attrs.get(
            "filtered_invalid_ticker_codes", {}
        ),
        "ohlcv": asdict(comparison),
        "krx_login_used": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if len(master) < 2_000:
        print("ERROR: security master has unexpectedly few rows.")
        return 1
    if comparison.common_rows == 0:
        print("ERROR: the two OHLCV providers have no common dates.")
        return 2
    if not comparison.close_values_match:
        print("ERROR: adjusted close values differ between providers.")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
