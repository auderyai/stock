from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.cloud_sync.credentials import DriveCredentials
from krx_research.cloud_sync.drive import GoogleDriveTransientError
from krx_research.cloud_sync.service import (
    StockDriveSyncService,
    SyncContext,
    TransientSourceError,
)


def _date(value: str) -> date:
    return date.fromisoformat(value)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="암호화 Google Drive PostgreSQL 증분 동기화")
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("bootstrap", help="로컬 DB에서 암호화된 초기 작업 상태 생성·업로드")
    sub.add_parser("sync-local", help="Drive 일일 변경분을 로컬 PostgreSQL에 멱등 반영")
    sub.add_parser("verify", help="비밀값 출력 없이 Drive 메타데이터 확인")
    local_base = sub.add_parser(
        "publish-local-base", help="검증된 로컬 메뉴 2 일일자료를 Drive에 게시"
    )
    local_base.add_argument("--date", type=_date, required=True)
    local_progress = sub.add_parser(
        "publish-local-progress", help="검증된 로컬 일일 진행자료를 Drive 복구점으로 게시"
    )
    local_progress.add_argument("--date", type=_date, required=True)
    cloud = sub.add_parser("cloud-run", help="GitHub Actions 메뉴 2·5·7 실행")
    cloud.add_argument("--date", type=_date)
    cloud.add_argument(
        "--stage",
        choices=("menu2", "menu5", "menu7", "remaining", "all"),
        default="menu2",
        help="한 번에 저장할 독립 단계(기본: menu2)",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    log_path = ROOT / "logs" / "cloud_sync" / "drive_sync.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"{started} START command={args.command}\n")
    try:
        if sys.platform == "win32" and args.command != "cloud-run":
            credentials = DriveCredentials.from_windows_store(
                ROOT / "config" / "google_drive_oauth.dpapi"
            )
        else:
            credentials = DriveCredentials.from_environment()
        service = StockDriveSyncService(SyncContext(ROOT, credentials))
        if args.command == "bootstrap":
            result = service.bootstrap()
        elif args.command == "sync-local":
            result = service.sync_local()
        elif args.command == "verify":
            result = service.verify()
        elif args.command == "publish-local-base":
            result = service.publish_local_base(args.date)
        elif args.command == "publish-local-progress":
            result = service.publish_local_progress(args.date)
        else:
            target = args.date or datetime.now(ZoneInfo("Asia/Seoul")).date()
            result = service.cloud_run(target, stage=args.stage)
        with log_path.open("a", encoding="utf-8") as log:
            log.write(
                f"{datetime.now().astimezone().isoformat(timespec='seconds')} "
                f"SUCCESS command={args.command} status={result.get('status', 'complete')}\n"
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"감사 로그: {log_path}")
        return 0
    except (TransientSourceError, GoogleDriveTransientError) as exc:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(
                f"{datetime.now().astimezone().isoformat(timespec='seconds')} "
                f"TRANSIENT command={args.command} error={type(exc).__name__}\n"
            )
        print(f"[TRANSIENT] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 75
    except Exception as exc:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(
                f"{datetime.now().astimezone().isoformat(timespec='seconds')} "
                f"FAILED command={args.command} error={type(exc).__name__}\n"
            )
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"감사 로그: {log_path}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
