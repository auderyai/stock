from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.cloud_sync.credentials import DriveCredentials
from krx_research.cloud_sync.drive import GoogleDriveClient
from krx_research.financial_backfill.client import OpenDartClient, OpenDartTransientError
from krx_research.financial_backfill.service import (
    DEFAULT_YEARS,
    FinancialBackfillContext,
    FinancialBackfillService,
)


def _years(value: str) -> tuple[int, ...]:
    try:
        years = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("사업연도는 쉼표로 구분한 숫자여야 합니다.") from exc
    if not years:
        raise argparse.ArgumentTypeError("사업연도가 필요합니다.")
    return years


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="OpenDART 분기별 수집 → DuckDB 검증 → 암호화 Drive → 로컬 PostgreSQL"
    )
    result.add_argument(
        "--years", type=_years, default=DEFAULT_YEARS,
        help="현재 가용 기간과 완료 사업연도를 진행할 내림차순 연도",
    )
    commands = result.add_subparsers(dest="command", required=True)
    cloud = commands.add_parser("cloud-menu5", help="다음 미완료 분기를 클라우드에서 수집")
    cloud.add_argument("--year", type=int, help="지정하지 않으면 다음 허용 연도")
    cloud.add_argument("--batch-size", type=int, default=100)
    cloud.add_argument("--max-batches", type=int, default=0, help="0은 해당 분기 전체")
    local = commands.add_parser("sync-local", help="완료 연도를 로컬 PostgreSQL에 반영")
    local.add_argument("--year", type=int, required=True)
    commands.add_parser(
        "sync-ready-local", help="Drive에서 완료된 다음 연도만 로컬 PostgreSQL에 반영"
    )
    commands.add_parser("status", help="Drive 체크포인트 상태 확인")
    return result


def _credentials(command: str) -> DriveCredentials:
    if sys.platform == "win32" and command != "cloud-menu5":
        return DriveCredentials.from_windows_store(ROOT / "config" / "google_drive_oauth.dpapi")
    return DriveCredentials.from_environment()


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    credentials = _credentials(args.command)
    try:
        with GoogleDriveClient(
            client_id=credentials.client_id,
            client_secret=credentials.client_secret,
            refresh_token=credentials.refresh_token,
            root_folder_id=credentials.root_folder_id,
        ) as drive:
            context = FinancialBackfillContext(ROOT, drive, credentials.archive_key)
            if args.command == "cloud-menu5":
                api_key = os.getenv("OPENDART_API_KEY", "")
                with OpenDartClient(api_key) as client:
                    service = FinancialBackfillService(context, client)
                    result = (
                        service.cloud_collect(
                            args.year, years=args.years,
                            batch_size=args.batch_size, max_batches=args.max_batches,
                        )
                        if args.year
                        else service.cloud_collect_next(
                            years=args.years, batch_size=args.batch_size,
                            max_batches=args.max_batches,
                        )
                    )
            else:
                service = FinancialBackfillService(context, client=None)
                result = (
                    service.sync_local(args.year, years=args.years)
                    if args.command == "sync-local"
                    else service.sync_ready_local(years=args.years)
                    if args.command == "sync-ready-local"
                    else service.status(args.years)
                )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except OpenDartTransientError as exc:
        print(f"[TRANSIENT] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 75
    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
