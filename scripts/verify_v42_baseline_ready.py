from __future__ import annotations

import argparse
import pathlib
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify V41 COMPLETE baseline before V42 installation")
    parser.add_argument("--root", type=pathlib.Path, help="new_stock project root")
    return parser.parse_args()


def resolve_root(value: pathlib.Path | None) -> pathlib.Path:
    if value is not None:
        return value.expanduser().resolve()
    # Installed-copy fallback: <root>/scripts/verify_v42_baseline_ready.py
    return pathlib.Path(__file__).resolve().parents[1]


def main() -> int:
    args = parse_args()
    root = resolve_root(args.root)
    logs = root / "logs"
    candidates = sorted(
        logs.glob("v41_10_db_menu_e2e_*.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        print("V42_BASELINE_READY: FAIL")
        print(f"FAIL: v41_10 COMPLETE log not found under {logs}")
        return 2

    required = [
        "[PASS] Menu 2 end-to-end",
        "[PASS] Menu 7 actual write path",
        "[PASS] Menu 5 end-to-end",
        "V41 DB/MENU INTEGRATION: COMPLETE",
    ]

    # Do not reject the project merely because a newer incomplete diagnostic log exists.
    # Search newest -> oldest and accept the newest log that proves the full baseline.
    for candidate in candidates:
        text = candidate.read_text(encoding="utf-8", errors="replace")
        missing = [item for item in required if item not in text]
        if not missing:
            print(f"V42_BASELINE_READY: PASS ({candidate})")
            return 0

    newest = candidates[0]
    text = newest.read_text(encoding="utf-8", errors="replace")
    missing = [item for item in required if item not in text]
    print("V42_BASELINE_READY: FAIL")
    print(f"FAIL: no COMPLETE V41.10 log found under {logs}")
    print(f"Newest log checked: {newest}")
    print("Missing in newest:", ", ".join(missing))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
