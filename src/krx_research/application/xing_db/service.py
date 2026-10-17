from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from typing import Any

from .models import ActionReport, MenuAction, StageResult
from .policy import DailyCloseWritePolicy
from .ports import RawTrPort, XingMenuRepositoryPort

Progress = Callable[[str], None]


class MarketIndexPublisher:
    def __init__(self, repository: XingMenuRepositoryPort) -> None:
        self._repo = repository

    def publish(self, as_of: dt.date) -> int:
        published = self._repo.publish_market_indices(as_of)
        if published <= 0:
            raise ValueError("KOSPI·KOSDAQ 종합·업종지수 canonical 발행 결과가 0건입니다.")
        return published

    def publish_range(self, start: dt.date, end: dt.date) -> int:
        if start > end:
            raise ValueError("start가 end보다 늦습니다.")
        dates = self._repo.market_index_source_dates(start, end)
        if not dates:
            raise ValueError(f"종합·업종지수 발행 원천 거래일이 없습니다: {start}~{end}")
        return sum(self.publish(day) for day in dates)


class XingDbMenuService:
    """Application service for menu 2/5/7.

    No Qt, ctypes, DLL or psycopg code belongs here. The service talks only to ports.
    """

    _INDEX_ALIASES: tuple[tuple[str, tuple[str, ...], int], ...] = (
        ("KOSPI200", ("KOSPI200", "코스피200"), 200),
        ("KOSDAQ150", ("KOSDAQ150", "코스닥150"), 150),
    )
    _INDEX_COUNT_TOLERANCE = 5
    _LS_QUALIFIED_LOOKBACK_DAYS = 45
    _T1702_REPAIR_PASSES = 3
    _T8451_REPAIR_PASSES = 3
    _VENUE_CODE = {"KRX": "K", "NXT": "N", "COMBINED": "U"}

    def __init__(self, bridge: RawTrPort, repository: XingMenuRepositoryPort) -> None:
        self._bridge = bridge
        self._repo = repository
        self._index_publisher = MarketIndexPublisher(repository)

    def close(self) -> None:
        try:
            self._bridge.close()
        finally:
            self._repo.close()

    def __enter__(self) -> "XingDbMenuService":
        self._repo.initialize()
        self._bridge.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def run_menu2(self, *, as_of: dt.date, progress: Progress | None = None,
                  enforce_cutoff: bool = True) -> ActionReport:
        started = dt.datetime.now()
        stages: list[StageResult] = []
        latest_db_day = self._repo.latest_market_date()
        effective_as_of = (
            DailyCloseWritePolicy.resolve_end_date(as_of, latest_db_day)
            if enforce_cutoff else (min(as_of, latest_db_day) if latest_db_day else as_of)
        )
        if effective_as_of != as_of:
            self._emit(progress, f"[DATE ADJUST] 요청 기준일 {as_of} → 최신 확정 거래일 {effective_as_of}")

        sectors = self._rows("t8424", {"gubun1": "0"})
        n = self._repo.upsert_sector_master(sectors)
        stages.append(StageResult("t8424 업종 마스터", True, n))
        self._emit(progress, f"t8424 업종 마스터 {n:,}건 저장")

        securities = self._rows("t8436", {"gubun": "0"})
        n = self._repo.upsert_security_master(securities)
        stages.append(StageResult("t8436 종목 마스터", True, n))
        self._emit(progress, f"t8436 종목 마스터 {n:,}건 저장")

        index_codes = self._resolve_index_codes(sectors)
        membership_count = 0
        expected_counts = {display: expected for display, _aliases, expected in self._INDEX_ALIASES}
        for display, code in index_codes.items():
            rows = self._rows("t1516", {"upcode": code, "gubun": "1", "shcode": ""})
            unique: dict[str, dict[str, Any]] = {}
            for row in rows:
                stock_code = str(row.get("shcode") or "").strip().upper()
                if re.fullmatch(r"[0-9A-Z]{6}", stock_code):
                    unique[stock_code] = row
            nominal = expected_counts[display]
            actual = len(unique)
            if abs(actual - nominal) > self._INDEX_COUNT_TOLERANCE:
                raise ValueError(
                    f"{display} 구성종목 수 비정상: {actual} "
                    f"(명목 {nominal}, 허용 ±{self._INDEX_COUNT_TOLERANCE})"
                )
            stored = self._repo.replace_index_membership(
                effective_as_of, code, display, list(unique.values())
            )
            if stored != actual:
                raise ValueError(f"{display} DB 저장 수 오류: {stored}/{actual}")
            membership_count += stored
            self._emit(progress, f"{display} 구성종목 {actual:,}건 (명목 {nominal}, tolerance 적용)")
        stages.append(StageResult("t1516 지수 구성종목", True, membership_count))
        self._emit(progress, f"t1516 구성종목 {membership_count:,}건 저장")

        sector_daily = 0
        t8429_request_start = self._expanded_request_start(effective_as_of, effective_as_of)
        sector_targets: list[tuple[str, str]] = []
        for row in sectors:
            code = str(row.get("upcode") or "").strip()
            if not re.fullmatch(r"\d{3}", code):
                continue
            sector_targets.append((code, str(row.get("hname") or "").strip()))

        all_target_count = len(sector_targets)
        completed_codes = self._repo.completed_sector_codes(effective_as_of)
        pending_targets = [(code, name) for code, name in sector_targets if code not in completed_codes]
        completed_count = all_target_count - len(pending_targets)
        target_count = len(pending_targets)
        sector_started = dt.datetime.now()
        self._emit(
            progress,
            f"t8429 RESUME: 기준일 기존완료 {completed_count:,}/{all_target_count:,}, "
            f"남은 {target_count:,}개 업종만 조회",
        )
        if not pending_targets:
            self._emit(progress, f"t8429 업종 일봉 SKIP: {all_target_count:,}개 업종 기준일 DB 완료")
        else:
            self._emit(
                progress,
                f"t8429 업종 일봉 시작: {target_count:,}개 업종, "
                f"wire={t8429_request_start:%Y-%m-%d}~{effective_as_of:%Y-%m-%d}",
            )
        for position, (code, name) in enumerate(pending_targets, 1):
            elapsed = max(0.0, (dt.datetime.now() - sector_started).total_seconds())
            if position > 1:
                seconds_per_item = elapsed / (position - 1)
                eta_seconds = int(seconds_per_item * (target_count - position + 1))
                eta_text = f"ETA {eta_seconds // 60:02d}:{eta_seconds % 60:02d}"
            else:
                eta_text = "ETA 계산 중"
            self._emit(
                progress,
                f"[t8429 {position}/{target_count}] {code} {name or '-'} 조회 시작 | "
                f"누적저장 {sector_daily:,}건 | {eta_text}",
            )
            try:
                raw_rows = self._rows(
                    "t8429",
                    {
                        "shcode": code,
                        "gubun": "2",
                        "qrycnt": "200",
                        "sdate": t8429_request_start.strftime("%Y%m%d"),
                        "edate": effective_as_of.strftime("%Y%m%d"),
                        "cts_date": "",
                        "comp_yn": "N",
                    },
                    allow_empty=True,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"t8429 업종 조회 실패 [{position}/{target_count}]: "
                    f"upcode={code}, hname={name!r}, "
                    f"wire={t8429_request_start:%Y-%m-%d}~{effective_as_of:%Y-%m-%d}: {exc}"
                ) from exc
            day_rows = self._filter_rows_by_date(raw_rows, effective_as_of, effective_as_of)
            stored_now = 0
            if day_rows:
                stored_now = self._repo.upsert_sector_daily(code, day_rows)
                sector_daily += stored_now
            self._emit(
                progress,
                f"[t8429 {position}/{target_count}] {code} 완료 | "
                f"수신 {len(raw_rows):,}건 / 기준일 {len(day_rows):,}건 / "
                f"저장 {stored_now:,}건 / 누적 {sector_daily:,}건",
            )
        stages.append(StageResult("t8429 업종 일봉", True, sector_daily))
        total_elapsed = int((dt.datetime.now() - sector_started).total_seconds())
        self._emit(
            progress,
            f"t8429 업종 일봉 신규 {sector_daily:,}건 저장 완료 "
            f"(처리 {target_count:,}개 / 기준일 완료 {completed_count + sector_daily:,}/{all_target_count:,}, "
            f"{total_elapsed // 60:02d}:{total_elapsed % 60:02d})",
        )

        published_indices = self._index_publisher.publish(effective_as_of)
        stages.append(StageResult("KOSPI·KOSDAQ 종합·업종지수 발행", True, published_indices))
        self._emit(progress, f"KOSPI·KOSDAQ 종합·업종지수 {published_indices:,}건 검증·발행 완료")

        return ActionReport(
            MenuAction.FAST_DAILY, started, dt.datetime.now(), tuple(stages),
            {"requested_as_of": as_of.isoformat(), "effective_as_of": effective_as_of.isoformat()},
        )

    def run_menu5(self, *, start: dt.date, end: dt.date, ticker: str | None = None,
                  max_tickers: int = 0, ticker_offset: int = 0,
                  chunk_days: int = 90, empty_stop_chunks: int = 0,
                  progress: Progress | None = None, enforce_cutoff: bool = True,
                  force_refresh: bool = False,
                  independent_target: bool = False) -> ActionReport:
        if start > end:
            raise ValueError("start가 end보다 늦습니다.")
        latest_db_day = None if independent_target else self._repo.latest_market_date()
        cutoff_base = None if independent_target else latest_db_day
        effective_end = DailyCloseWritePolicy.resolve_end_date(end, cutoff_base) if enforce_cutoff else end
        if start > effective_end:
            raise ValueError(f"선택 범위에 확정 거래일이 없습니다: {start}~{end} (DB 최신 {latest_db_day})")
        if effective_end != end:
            self._emit(progress, f"[DATE ADJUST] 요청 종료일 {end} → 최신 확정 거래일 {effective_end}")
        end = effective_end
        if not 1 <= chunk_days <= 90:
            raise ValueError("chunk_days는 1~90이어야 합니다.")
        started = dt.datetime.now()
        total_complete = total_raw = skipped_complete = request_failures = 0
        refresh_failed: set[str] = set()
        if independent_target:
            count = self._repo.replace_cloud_stock_universe(
                self._rows("t8436", {"gubun": "0"})
            )
            self._emit(progress, f"클라우드 독립 종목 목록 {count:,}건 갱신")
        if ticker_offset < 0:
            raise ValueError("ticker_offset은 0 이상이어야 합니다.")
        if independent_target:
            codes = self._repo.list_cloud_stock_codes(ticker, max_tickers, ticker_offset)
        elif ticker_offset:
            codes = self._repo.list_stock_codes(ticker, max_tickers, ticker_offset)
        else:
            codes = self._repo.list_stock_codes(ticker, max_tickers)
        trade_days = (
            {code: self._date_range(start, end) for code in codes}
            if independent_target else
            self._repo.stock_trade_dates_by_code(codes, start, end)
        )
        completed = self._repo.completed_investor_dates_by_code(codes, start, end, "K")
        pending_codes = sum(bool(trade_days.get(code, set()) and
                            (force_refresh or trade_days[code] - completed.get(code, set()))) for code in codes)
        self._emit(progress, f"수급 대상 {len(codes):,}종목 / 미완료 {pending_codes:,}종목 (DB 일괄 선조회)")
        for pos, code in enumerate(codes, 1):
            code_request_failures = 0
            all_days = sorted(trade_days.get(code, set()))
            if not all_days:
                continue
            expected = set(all_days)
            done_before = completed.get(code, set())
            pending = sorted(expected if force_refresh else (expected - done_before))
            if not pending:
                skipped_complete += len(expected)
                continue
            if force_refresh:
                self._emit(progress, f"[REFRESH] {code}: 수급 {len(pending):,}거래일 강제 재수집")
            self._emit(progress, f"[{pos}/{len(codes)}] {code}: {len(pending):,}거래일 수집")
            last = end
            empty_streak = 0
            while last >= start:
                first = max(start, last - dt.timedelta(days=chunk_days - 1))
                days = [d for d in pending if first <= d <= last]
                if days:
                    try:
                        found, complete = self._collect_t1702(code, days)
                        empty_streak = empty_streak + 1 if not found else 0
                        total_raw += len(found)
                        total_complete += self._repo.upsert_investor_raw(code, found, complete, "K")
                    except Exception as exc:
                        request_failures += 1
                        code_request_failures += 1
                        if force_refresh: refresh_failed.add(code)
                        self._emit(progress, f"{code} {first}~{last}: {type(exc).__name__}: {exc}")
                    if empty_stop_chunks and empty_streak >= empty_stop_chunks:
                        self._emit(progress, f"{code}: 연속 {empty_streak}개 구간 원본 없음, 오래된 기간 조회 중단")
                        break
                last = first - dt.timedelta(days=1)

            if not code_request_failures and pos % 100 == 0:
                self._emit(progress, f"[PROGRESS] {pos:,}/{len(codes):,}종목 처리")

        verified = self._repo.completed_investor_dates_by_code(codes, start, end, "K")
        for repair_pass in range(1, self._T1702_REPAIR_PASSES + 1):
            unresolved_by_code = {
                code: trade_days.get(code, set()) - verified.get(code, set())
                for code in codes
                if trade_days.get(code, set()) - verified.get(code, set())
            }
            if not unresolved_by_code:
                break
            self._emit(
                progress,
                f"[REPAIR {repair_pass}/{self._T1702_REPAIR_PASSES}] "
                f"t1702 누락 {len(unresolved_by_code):,}종목만 재수집",
            )
            for code, unresolved in unresolved_by_code.items():
                try:
                    found, complete = self._collect_t1702(code, sorted(unresolved))
                    total_raw += len(found)
                    total_complete += self._repo.upsert_investor_raw(code, found, complete, "K")
                    if unresolved.issubset(set(complete)):
                        refresh_failed.discard(code)
                except Exception as exc:
                    request_failures += 1
                    self._emit(
                        progress,
                        f"[REPAIR {repair_pass}] {code}: {type(exc).__name__}: {exc}",
                    )
            verified = self._repo.completed_investor_dates_by_code(codes, start, end, "K")

        failures = 0; unresolved_codes: set[str] = set()
        for code in codes:
            expected = trade_days.get(code, set()); unresolved = expected - verified.get(code, set())
            if unresolved:
                unresolved_codes.add(code)
                failures += len(unresolved)
                self._emit(progress, f"[FAIL] {code}: t1702 미완료 {len(unresolved):,}/{len(expected):,}거래일")
        for code in sorted(refresh_failed - unresolved_codes):
            failures += 1
            self._emit(progress, f"[FAIL] {code}: force-refresh 요청 실패")
        self._emit(progress, f"[VERIFY] PostgreSQL 일괄 검증 완료: 미완료 {failures:,}거래일")

        if failures:
            message = f"미완료 {failures:,}건/거래일, 요청실패 {request_failures:,}회"
        elif request_failures:
            message = (
                f"PASS / 원본 {total_raw:,}건, 신규완료 {total_complete:,}일, "
                f"일시 요청실패 {request_failures:,}회 복구"
            )
        elif total_raw:
            message = f"PASS / 원본 {total_raw:,}건, 신규완료 {total_complete:,}일"
        else:
            message = f"SKIP / 기존 완료 {skipped_complete:,}거래일"
        stages = (
            StageResult("t1702 원본 저장", failures == 0, total_raw, message),
            StageResult("t1702 완료 체크포인트", failures == 0, total_complete,
                        "DB 재검증 완료" if failures == 0 else "DB 재검증 실패"),
        )
        return ActionReport(
            MenuAction.INVESTOR_RAW, started, dt.datetime.now(), stages,
            {
                "start": start.isoformat(), "end": end.isoformat(),
                "ticker": ticker or "ALL", "ticker_offset": str(ticker_offset),
                "code_count": str(len(codes)),
            },
        )

    def run_menu7(self, *, start: dt.date, end: dt.date, ticker: str | None = None,
                  venues: tuple[str, ...] = ("NXT", "COMBINED"), max_tickers: int = 0,
                  progress: Progress | None = None, enforce_cutoff: bool = True,
                  include_investor: bool = True, force_refresh: bool = False,
                  independent_target: bool = False) -> ActionReport:
        if start > end:
            raise ValueError("start가 end보다 늦습니다.")
        latest_db_day = None if independent_target else self._repo.latest_market_date()
        cutoff_base = None if independent_target else latest_db_day
        effective_end = DailyCloseWritePolicy.resolve_end_date(end, cutoff_base) if enforce_cutoff else end
        if start > effective_end:
            raise ValueError(f"선택 범위에 확정 거래일이 없습니다: {start}~{end} (DB 최신 {latest_db_day})")
        if effective_end != end:
            self._emit(progress, f"[DATE ADJUST] 요청 종료일 {end} → 최신 확정 거래일 {effective_end}")
        end = effective_end
        invalid = [v for v in venues if v.upper() not in self._VENUE_CODE]
        if invalid:
            raise ValueError(f"지원하지 않는 거래시장: {', '.join(invalid)}")
        started = dt.datetime.now()
        if independent_target:
            codes = self._repo.list_cloud_stock_codes(ticker, max_tickers)
            if not codes:
                raise ValueError("클라우드 종목 목록이 없습니다. 메뉴 5 완료 후 메뉴 7을 실행하십시오.")
        else:
            codes = self._repo.list_stock_codes(ticker, max_tickers)
        venue_names = tuple(v.upper() for v in venues)
        base_by_code = (
            {code: self._date_range(start, end) for code in codes}
            if independent_target else
            self._repo.stock_trade_dates_by_code(codes, start, end)
        )
        stored_before = self._repo.venue_trade_dates_by_code(codes, venue_names, start, end)
        daily_count = skipped = 0
        received: dict[tuple[str, str], set[dt.date]] = {}
        request_errors: dict[tuple[str, str], str] = {}
        self._emit(progress, f"일봉 대상 {len(codes):,}종목 × {len(venue_names)}시장 (DB 일괄 선조회)")
        for pos, code in enumerate(codes, 1):
            base_days = base_by_code.get(code, set())
            if not base_days:
                skipped += 1
                continue
            for venue in venue_names:
                before = stored_before.get((code, venue), set())
                if venue == "COMBINED":
                    missing_before = sorted(base_days - before)
                    if not missing_before and not force_refresh:
                        skipped += len(base_days)
                        continue
                    fetch_start = start if force_refresh else missing_before[0]
                    if force_refresh:
                        self._emit(progress, f"[REFRESH] {code} {venue}: {start}~{end} 강제 재수집")
                else:
                    checkpoint = max(before) if before else None
                    fetch_start = max(start, checkpoint + dt.timedelta(days=1)) if checkpoint else start
                    if fetch_start > end:
                        skipped += len(before)
                        continue

                request_start = self._expanded_request_start(fetch_start, end)
                self._emit(
                    progress,
                    f"[{pos}/{len(codes)}] {code} {venue} logical={fetch_start}~{end} "
                    f"wire={request_start}~{end}",
                )
                rows: list[dict[str, Any]] = []
                try:
                    raw_rows = self._rows(
                        "t8451",
                        {
                            "shcode": code,
                            "gubun": "2",
                            "qrycnt": "2000",
                            "sdate": request_start.strftime("%Y%m%d"),
                            "edate": end.strftime("%Y%m%d"),
                            "cts_date": "",
                            "comp_yn": "N",
                            "sujung": "N",
                            "exchgubun": self._VENUE_CODE[venue],
                        },
                        allow_empty=True,
                    )
                    rows = self._filter_rows_by_date(raw_rows, start, end)
                    stored = self._repo.upsert_venue_daily(code, venue, rows)
                    daily_count += stored
                    dates = {dt.datetime.strptime(str(row["date"]), "%Y%m%d").date() for row in rows}
                    if dates: received[(code, venue)] = dates
                    else: skipped += 1
                except Exception as exc:
                    request_errors[(code, venue)] = f"{type(exc).__name__}: {exc}"
            if pos % 100 == 0: self._emit(progress, f"[PROGRESS] {pos:,}/{len(codes):,}종목 처리")

        verified = self._repo.venue_trade_dates_by_code(codes, venue_names, start, end)
        for repair_pass in range(1, self._T8451_REPAIR_PASSES + 1):
            unresolved: dict[tuple[str, str], set[dt.date]] = {}
            for code in codes:
                base_days = base_by_code.get(code, set())
                for venue in venue_names:
                    key = (code, venue)
                    expected = base_days if venue == "COMBINED" else received.get(key, set())
                    missing = expected - verified.get(key, set())
                    if missing or key in request_errors:
                        unresolved[key] = missing
            if not unresolved:
                break
            self._emit(
                progress,
                f"[REPAIR {repair_pass}/{self._T8451_REPAIR_PASSES}] "
                f"t8451 누락·요청실패 {len(unresolved):,}종목/시장만 재수집",
            )
            for (code, venue), missing in unresolved.items():
                logical_start = min(missing) if missing else start
                request_start = self._expanded_request_start(logical_start, end)
                try:
                    raw_rows = self._rows(
                        "t8451",
                        {
                            "shcode": code,
                            "gubun": "2",
                            "qrycnt": "2000",
                            "sdate": request_start.strftime("%Y%m%d"),
                            "edate": end.strftime("%Y%m%d"),
                            "cts_date": "",
                            "comp_yn": "N",
                            "sujung": "N",
                            "exchgubun": self._VENUE_CODE[venue],
                        },
                        allow_empty=True,
                    )
                    rows = self._filter_rows_by_date(raw_rows, start, end)
                    daily_count += self._repo.upsert_venue_daily(code, venue, rows)
                    dates = {
                        dt.datetime.strptime(str(row["date"]), "%Y%m%d").date()
                        for row in rows
                    }
                    if dates:
                        received.setdefault((code, venue), set()).update(dates)
                    request_errors.pop((code, venue), None)
                except Exception as exc:
                    request_errors[(code, venue)] = f"{type(exc).__name__}: {exc}"
            verified = self._repo.venue_trade_dates_by_code(codes, venue_names, start, end)

        failures = 0; unresolved_keys: set[tuple[str, str]] = set()
        for code in codes:
            base_days = base_by_code.get(code, set())
            for venue in venue_names:
                expected = base_days if venue == "COMBINED" else received.get((code, venue), set())
                missing = expected - verified.get((code, venue), set())
                if missing:
                    unresolved_keys.add((code, venue)); failures += len(missing)
                    self._emit(progress, f"[FAIL] {code} {venue}: DB 미완료 {len(missing):,}/{len(expected):,}거래일")
        for key, detail in request_errors.items():
            if key not in unresolved_keys:
                failures += 1; self._emit(progress, f"[FAIL] {key[0]} {key[1]}: {detail}")
        self._emit(progress, f"[VERIFY] PostgreSQL 일괄 검증 완료: 미완료 {failures:,}건")

        daily_message = (
            f"미완료 {failures:,}건" if failures else
            (f"PASS / 저장 {daily_count:,}건" if daily_count else f"SKIP / DB완료·NXT무자료 {skipped:,}건")
        )
        stages_list = [
            StageResult("t8451 종목별 일봉", failures == 0, daily_count, daily_message)
        ]
        if include_investor:
            investor = self.run_menu5(
                start=start, end=end, ticker=ticker, max_tickers=max_tickers,
                chunk_days=min(90, max(1, (end - start).days + 1)), empty_stop_chunks=0, progress=progress,
                enforce_cutoff=False, force_refresh=force_refresh,
                independent_target=independent_target,
            )
            investor_stage = next((s for s in investor.stages if s.name == "t1702 원본 저장"), None)
            stages_list.append(
                StageResult("t1702 종목별 수급", bool(investor_stage and investor_stage.passed),
                            investor_stage.affected_rows if investor_stage else 0,
                            investor_stage.message if investor_stage else "수급 단계 결과 없음")
            )
        stages = tuple(stages_list)
        return ActionReport(
            MenuAction.STOCK_SUPPLEMENT, started, dt.datetime.now(), stages,
            {"start": start.isoformat(), "end": end.isoformat(), "ticker": ticker or "ALL",
             "venues": ",".join(v.upper() for v in venues)},
        )

    @staticmethod
    def _date_range(start: dt.date, end: dt.date) -> set[dt.date]:
        return {start + dt.timedelta(days=offset) for offset in range((end - start).days + 1)}

    def _collect_t1702(
        self, stock_code: str, days: list[dt.date]
    ) -> tuple[dict[tuple[dt.date, str, str], dict[str, Any]], list[dt.date]]:
        expected = set(days)
        first, last = min(days), max(days)
        request_first = self._expanded_request_start(first, last)
        found: dict[tuple[dt.date, str, str], dict[str, Any]] = {}
        for metric in ("0", "1"):
            for side in ("1", "2"):
                rows = self._rows(
                    "t1702",
                    {
                        "fromdt": request_first.strftime("%Y%m%d"),
                        "shcode": stock_code,
                        "todt": last.strftime("%Y%m%d"),
                        "volvalgb": metric,
                        "msmdgb": side,
                        "gubun": "0",
                        "exchgubun": "K",
                    },
                    allow_empty=True,
                )
                for row in rows:
                    stamp = str(row.get("date") or "").strip()
                    try:
                        day = dt.datetime.strptime(stamp, "%Y%m%d").date()
                    except ValueError:
                        continue
                    if day not in expected:
                        continue
                    if any(v is not None and str(v).strip() != "" for k, v in row.items() if str(k).startswith("tjj")):
                        found[(day, metric, side)] = row
        complete = [
            day for day in days
            if all((day, m, s) in found for m in ("0", "1") for s in ("1", "2"))
        ]
        return found, complete

    @classmethod
    def _expanded_request_start(cls, logical_start: dt.date, logical_end: dt.date) -> dt.date:
        """Expand narrow LS daily/investor requests to the V39-qualified minimum window."""
        floor = logical_end - dt.timedelta(days=cls._LS_QUALIFIED_LOOKBACK_DAYS)
        return min(logical_start, floor)

    @staticmethod
    def _filter_rows_by_date(
        rows: list[dict[str, Any]], start: dt.date, end: dt.date
    ) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        for row in rows:
            stamp = str(row.get("date") or "").strip()
            try:
                day = dt.datetime.strptime(stamp, "%Y%m%d").date()
            except ValueError:
                continue
            if start <= day <= end:
                filtered.append(row)
        return filtered

    def _rows(self, tr: str, values: dict[str, str], *, allow_empty: bool = False) -> list[dict[str, Any]]:
        response = self._bridge.raw_tr(tr, {k: str(v) for k, v in values.items()})
        rows = response.get("rows")
        if not isinstance(rows, list):
            raise ValueError(f"{tr}: rows가 list가 아닙니다.")
        clean = [r for r in rows if isinstance(r, dict)]
        if not clean and not allow_empty:
            raise ValueError(f"{tr}: 응답 행이 없습니다.")
        return clean

    @classmethod
    def _resolve_index_codes(cls, rows: list[dict[str, Any]]) -> dict[str, str]:
        def norm(value: object) -> str:
            return re.sub(r"[\s_-]+", "", str(value or "")).upper()

        result: dict[str, str] = {}
        for display, aliases, _expected in cls._INDEX_ALIASES:
            wanted = {norm(a) for a in aliases}
            codes = {
                str(row.get("upcode") or "").strip()
                for row in rows
                if norm(row.get("hname")) in wanted
                and re.fullmatch(r"\d{3}", str(row.get("upcode") or "").strip())
            }
            if len(codes) != 1:
                raise ValueError(f"{display} 업종코드 식별 실패: {sorted(codes)}")
            result[display] = next(iter(codes))
        return result

    @staticmethod
    def _emit(callback: Progress | None, message: str) -> None:
        if callback is not None:
            callback(message)
