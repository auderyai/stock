from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .config import DataEngineSettings
from .postgresql import BaseDataRepository
from .providers import MARKETS, PykrxBaseProvider
from .screener import evaluate_screens
from .service import MarketDataService
from .updater import IncrementalBaseUpdater


def _today_kst() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


DATA_FINAL_TIME_KST = time(20, 10)


def resolve_scheduled_update_date(
    requested: date | None,
    *,
    now: datetime | None = None,
) -> date:
    """Choose the latest date whose daily exchange facts can be final.

    A run before 20:10 KST targets the previous weekday instead of requesting
    a date whose official daily facts are not final. The provider still
    validates exchange holidays.
    """

    current = now or datetime.now(ZoneInfo("Asia/Seoul"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    else:
        current = current.astimezone(ZoneInfo("Asia/Seoul"))
    today = current.date()
    selected = min(requested or today, today)
    if selected == today and current.time().replace(tzinfo=None) < DATA_FINAL_TIME_KST:
        selected -= timedelta(days=1)
    while selected.weekday() >= 5:
        selected -= timedelta(days=1)
    return selected


def _parse_date(value: str) -> date:
    try:
        return pd.Timestamp(value).date()
    except Exception as exc:
        raise argparse.ArgumentTypeError(f"날짜 형식 오류: {value}") from exc


def _repository() -> BaseDataRepository:
    settings = DataEngineSettings.from_environment()
    return BaseDataRepository(settings)


def _print_frame(frame: pd.DataFrame, tail: int = 30) -> None:
    if frame.empty:
        print("조회 결과가 없습니다.")
        return
    with pd.option_context("display.max_columns", 100, "display.width", 240):
        print(frame.tail(tail).to_string())


def command_setup(_: argparse.Namespace) -> int:
    with _repository() as repository:
        repository.initialize_schema()
        identity = repository.database_identity()
        print(json.dumps(identity, ensure_ascii=False, indent=2, default=str))
        print("market_core 스키마 v30 준비 완료")
    return 0


def command_update(args: argparse.Namespace) -> int:
    requested_date = args.as_of or _today_kst()
    target_date = resolve_scheduled_update_date(requested_date)
    if target_date != requested_date:
        print(
            "[KRX DAILY] 수집 기준일 자동 조정: "
            f"{requested_date.isoformat()} -> {target_date.isoformat()} "
            "(20:10 KST 이전 또는 주말)"
        )
    with _repository() as repository:
        provider = PykrxBaseProvider(
            repository.settings.provider_delay_seconds,
            fallback_universe=repository.get_security_master_frame(),
        )
        updater = IncrementalBaseUpdater(repository, provider)
        result = updater.update_date(
            target_date,
            markets=args.markets,
            include_investor=not args.no_investor,
            force=args.force,
        )
        payload = result.__dict__.copy() if hasattr(result, "__dict__") else {
            "target_date": result.target_date,
            "ohlcv_rows": result.ohlcv_rows,
            "investor_rows": result.investor_rows,
            "markets_completed": result.markets_completed,
            "skipped": result.skipped,
            "messages": result.messages,
            "metadata": result.metadata,
        }
        database_latest = repository.latest_ohlcv_date()
        payload["database_latest_ohlcv_date"] = database_latest
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        if database_latest is None or database_latest < target_date:
            print(
                "[ERROR] 갱신 후 PostgreSQL 가격 기준일이 목표일보다 이전입니다: "
                f"DB={database_latest}, 목표={target_date.isoformat()}"
            )
            return 2
    return 0 if result.metadata.get("status", "completed") == "completed" else 2


def command_backfill_investor(args: argparse.Namespace) -> int:
    dates = [timestamp.date() for timestamp in pd.bdate_range(args.start, args.end)]
    if len(dates) > args.max_days:
        raise RuntimeError(
            f"요청 범위가 {len(dates)} 영업일입니다. 확인 후 --max-days {len(dates)} 이상으로 다시 실행하십시오."
        )
    totals = {"days": 0, "investor_rows": 0, "skipped": 0, "partial": 0}
    with _repository() as repository:
        provider = PykrxBaseProvider(repository.settings.provider_delay_seconds)
        updater = IncrementalBaseUpdater(repository, provider)
        for selected_date in dates:
            result = updater.update_date(
                selected_date,
                markets=args.markets,
                include_prices=False,
                include_investor=True,
                force=args.force,
            )
            totals["days"] += 1
            totals["investor_rows"] += result.investor_rows
            totals["skipped"] += int(result.skipped)
            totals["partial"] += int(result.metadata.get("status") == "partial")
            print(
                f"{selected_date}: investor_rows={result.investor_rows:,}, "
                f"status={result.metadata.get('status', 'skipped')}"
            )
    print(json.dumps(totals, ensure_ascii=False, indent=2))
    return 0 if totals["partial"] == 0 else 2


def command_query(args: argparse.Namespace) -> int:
    with _repository() as repository:
        service = MarketDataService(
            repository,
            cache_size=repository.settings.cache_size,
            cache_ttl_seconds=repository.settings.cache_ttl_seconds,
        )
        if args.investor:
            frame = service.get_investor_flow(
                args.ticker,
                args.timeframe,
                args.start,
                args.end,
                include_totals=True,
                pivot=args.pivot,
                unit=args.unit,
            )
        else:
            frame = service.get_bars(
                args.ticker,
                args.timeframe,
                args.start,
                args.end,
                limit=args.limit,
                indicators=args.indicators,
            )
        if args.output:
            output = Path(args.output).resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(output, encoding="utf-8-sig")
            print(f"저장: {output}")
        _print_frame(frame, args.tail)
    return 0


def command_screen(args: argparse.Namespace) -> int:
    with _repository() as repository:
        service = MarketDataService(repository)
        frame = service.get_indicators(args.ticker, args.timeframe, end=args.as_of)
        print(json.dumps(evaluate_screens(frame), ensure_ascii=False, indent=2, default=str))
    return 0


def command_status(_: argparse.Namespace) -> int:
    with _repository() as repository:
        summary = repository.summary()
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


def command_archive(args: argparse.Namespace) -> int:
    if not args.apply:
        print("DRY RUN: 원천 시장 스키마의 기술지표 테이블을 legacy_archive로 이동합니다.")
        print("적용하려면 --apply를 추가하십시오.")
        return 0
    with _repository() as repository:
        repository.initialize_schema()
        archived = repository.archive_derived_tables()
        print("이동 완료:", ", ".join(archived) if archived else "대상 없음")
    return 0


def command_restore(args: argparse.Namespace) -> int:
    if not args.apply:
        print("DRY RUN: legacy_archive의 기술지표 테이블을 원래 시장 스키마로 복원합니다.")
        print("적용하려면 --apply를 추가하십시오.")
        return 0
    with _repository() as repository:
        restored = repository.restore_derived_tables()
        print("복원 완료:", ", ".join(restored) if restored else "대상 없음")
    return 0


def command_purge(args: argparse.Namespace) -> int:
    if args.confirm != "DROP_DERIVED_DATA":
        print("취소: --confirm DROP_DERIVED_DATA가 필요합니다.", file=sys.stderr)
        return 2
    with _repository() as repository:
        dropped = repository.purge_archived_derived_tables(args.confirm)
        print("영구 삭제 완료:", ", ".join(dropped) if dropped else "대상 없음")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m krx_research.data_engine",
        description="PostgreSQL 기본 데이터 + 요청 시 연산 엔진 v30",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup = subparsers.add_parser("setup", help="v30 기본 스키마 생성")
    setup.set_defaults(handler=command_setup)

    update = subparsers.add_parser("update", help="당일 원자료만 증분 갱신")
    update.add_argument("--as-of", type=_parse_date)
    update.add_argument(
        "--markets",
        nargs="+",
        choices=MARKETS,
        default=["KOSPI", "KOSDAQ"],
        help="갱신 시장(기본: KOSPI KOSDAQ, KONEX는 명시적으로 선택)",
    )
    update.add_argument("--no-investor", action="store_true")
    update.add_argument("--force", action="store_true")
    update.add_argument("--until-complete", action="store_true", help=argparse.SUPPRESS)
    update.set_defaults(handler=command_update)

    backfill = subparsers.add_parser("backfill-investor", help="과거 투자자 원자료를 재개 가능한 방식으로 수집")
    backfill.add_argument("--start", type=_parse_date, required=True)
    backfill.add_argument("--end", type=_parse_date, required=True)
    backfill.add_argument("--markets", nargs="+", choices=MARKETS, default=list(MARKETS))
    backfill.add_argument("--max-days", type=int, default=31)
    backfill.add_argument("--force", action="store_true")
    backfill.set_defaults(handler=command_backfill_investor)

    query = subparsers.add_parser("query", help="봉/지표/수급을 메모리에서 계산")
    query.add_argument("ticker")
    query.add_argument("--timeframe", default="D", choices=["D", "W", "M", "Q", "Y"])
    query.add_argument("--start", type=_parse_date)
    query.add_argument("--end", type=_parse_date)
    query.add_argument("--limit", type=int)
    query.add_argument("--indicators", action="store_true")
    query.add_argument("--investor", action="store_true")
    query.add_argument("--pivot", action="store_true")
    query.add_argument("--unit", choices=["value", "volume"], default="value")
    query.add_argument("--tail", type=int, default=30)
    query.add_argument("--output")
    query.set_defaults(handler=command_query)

    screen = subparsers.add_parser("screen", help="종목을 요청 시 스크리닝")
    screen.add_argument("ticker")
    screen.add_argument("--timeframe", default="D", choices=["D", "W", "M", "Q", "Y"])
    screen.add_argument("--as-of", type=_parse_date)
    screen.set_defaults(handler=command_screen)

    status = subparsers.add_parser("status", help="DB와 원자료 범위 확인")
    status.set_defaults(handler=command_status)

    archive = subparsers.add_parser("archive-derived", help="기존 파생 테이블을 복구 가능하게 격리")
    archive.add_argument("--apply", action="store_true")
    archive.set_defaults(handler=command_archive)

    restore = subparsers.add_parser("restore-derived", help="격리한 파생 테이블 복원")
    restore.add_argument("--apply", action="store_true")
    restore.set_defaults(handler=command_restore)

    purge = subparsers.add_parser("purge-derived", help="격리한 파생 테이블 영구 삭제")
    purge.add_argument("--confirm", required=True)
    purge.set_defaults(handler=command_purge)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        print(f"알림: v30에서 사용하지 않는 이전 옵션을 무시합니다: {' '.join(unknown)}", file=sys.stderr)
    return int(args.handler(args))
