"""Verify PostgreSQL or use --configure for private local account setup."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from krx_research.application.postgresql_setup import PostgreSQLSetupService


def verify_connection():
    return PostgreSQLSetupService(ROOT).verify_connection()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configure", action="store_true")
    parser.add_argument("--verify-accounts", action="store_true")
    parser.add_argument("--migrate-to-18", action="store_true")
    parser.add_argument("--inspect-backup", action="store_true")
    parser.add_argument("--verify-restored", type=Path)
    parser.add_argument("--restore-status", action="store_true")
    parser.add_argument("--complete-18", action="store_true")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--expected-size", type=int)
    parser.add_argument("--sha256")
    parser.add_argument("--latest-trade-date")
    args = parser.parse_args()
    if args.complete_18 and not args.verify_restored:
        parser.error("--complete-18은 --verify-restored 보고서와 함께 사용하십시오.")
    if args.restore_status:
        try:
            result = PostgreSQLSetupService(ROOT).restore_status()
        except Exception:
            print("RESTORE_STATUS: UNAVAILABLE")
            return 1
        print("RESTORE_STATUS: " + str(result))
        return 0
    if args.verify_restored:
        try:
            result = PostgreSQLSetupService(ROOT).verify_restored(
                args.verify_restored, complete18=args.complete_18, latest_trade_date=args.latest_trade_date)
        except Exception as error:
            detail = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
            state = getattr(error, "sqlstate", None)
            print(f"RESTORE_VERIFICATION: FAIL {detail if not state else 'SQLSTATE=' + state}")
            return 1
        print(f"RESTORE_VERIFICATION: PASS tables={len(result['table_counts'])} latest_trade_date={result['latest_trade_date']}")
        return 0
    request = dict(backup=args.backup, expected_size=args.expected_size, sha256=args.sha256,
                   latest_trade_date=args.latest_trade_date)
    if (args.migrate_to_18 or args.inspect_backup) and not all(request.values()):
        parser.error("복원에는 --backup, --expected-size, --sha256, --latest-trade-date가 필요합니다.")
    if args.inspect_backup:
        try:
            _, _, directory, _ = PostgreSQLSetupService(ROOT).inspect18(request, print)
        except RuntimeError as error:
            print(str(error))
            return 1
        print("BACKUP_INSPECTION: PASS " + str(directory / "validation.json"))
        return 0
    if args.configure or args.migrate_to_18:
        from krx_research.qt.postgresql_setup import configure
        return configure(ROOT, migration=request if args.migrate_to_18 else None)
    try:
        if args.verify_accounts:
            PostgreSQLSetupService(ROOT).verify_saved()
        verify_connection()
    except Exception:
        print("POSTGRESQL_CONNECTION: FAIL (설정 또는 DB 연결을 확인하십시오.)")
        return 1
    print("POSTGRESQL_CONNECTION: PASS (읽기 전용 연결)")
    if args.verify_accounts:
        print("POSTGRESQL_ACCOUNTS: PASS (읽기·쓰기 연결, 최소 권한)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
