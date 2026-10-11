from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from .e2e_models import Menu2Snapshot, VerificationResult
from .e2e_ports import E2EProbePort, MenuCommandPort

Progress = Callable[[str], None]


class DbMenuE2EVerificationService:
    """Non-destructive end-to-end verification for menus 2, 5 and 7.

    This application service never imports Qt, psycopg, subprocess, ctypes or Xing DLL code.
    It coordinates command and DB-probe ports only.
    """

    def __init__(self, probe: E2EProbePort, commands: MenuCommandPort) -> None:
        self._probe = probe
        self._commands = commands

    def close(self) -> None:
        self._probe.close()

    def run_all(self, *, lookback_days: int = 550, progress: Progress | None = None) -> tuple[VerificationResult, ...]:
        latest = self._probe.latest_market_date()
        if latest is None:
            return (VerificationResult("기준 거래일", False, "PostgreSQL OHLCV 최신 거래일을 찾지 못했습니다."),)
        start = latest - dt.timedelta(days=max(30, lookback_days))
        self._emit(progress, f"기준 거래일: {latest} / 결측 탐색 시작일: {start}")

        # Menu 2 runs first so LS security/index master tables are populated before
        # candidate discovery for menu 7/5. It does not write t8451/t1702 data.
        results = [
            self._verify_menu2(latest, progress),
            self._verify_menu7(start, latest, progress),
            self._verify_menu5(start, latest, progress),
        ]
        return tuple(results)

    def _verify_menu7(self, start: dt.date, end: dt.date, progress: Progress | None) -> VerificationResult:
        candidate = self._probe.find_combined_gap(start, end)
        insert_mode = candidate is not None
        if candidate is None:
            candidate = self._probe.find_existing_combined(start, end)
        if candidate is None:
            return VerificationResult("Menu 7 actual write path", False, "COMBINED 검증 후보가 없습니다.")

        code, day = candidate.stock_code, candidate.trade_date
        before = self._probe.combined_row_count(code, day)
        force = not insert_mode
        expected_before = 0 if insert_mode else 1
        self._emit(progress, f"[Menu7] 후보 {code} {day} / before={before} / force={force} / {candidate.reason}")
        if before != expected_before:
            return VerificationResult("Menu 7 actual write path", False, f"후보 사전 행 수 오류: {before}/{expected_before}")

        out1 = self._commands.run_menu7_single_combined(code, day, force_refresh=force)
        after = self._probe.combined_row_count(code, day)
        self._emit(progress, f"[Menu7] 1차 rc={out1.return_code}, affected={out1.affected_rows}, after={after}")
        if out1.return_code != 0 or out1.affected_rows <= 0 or after != 1:
            return VerificationResult(
                "Menu 7 actual write path", False,
                f"write 검증 실패: {code} {day}, rc={out1.return_code}, affected={out1.affected_rows}, {before}→{after}",
            )

        out2 = self._commands.run_menu7_single_combined(code, day, force_refresh=True)
        after2 = self._probe.combined_row_count(code, day)
        self._emit(progress, f"[Menu7] 재실행 rc={out2.return_code}, affected={out2.affected_rows}, after2={after2}")
        if out2.return_code != 0 or out2.affected_rows <= 0 or after2 != 1:
            return VerificationResult(
                "Menu 7 actual write path", False,
                f"UPSERT/idempotency 실패: {code} {day}, rc={out2.return_code}, affected={out2.affected_rows}, rows={after2}",
            )
        mode = "INSERT→UPSERT" if insert_mode else "기존행 UPSERT→UPSERT"
        return VerificationResult("Menu 7 actual write path", True, f"{code} {day}: {mode}, row_count=1 유지")

    def _verify_menu5(self, start: dt.date, end: dt.date, progress: Progress | None) -> VerificationResult:
        # For non-destructive E2E, prefer a known-complete row and force-refresh it.
        # Missing rows remain production completeness work; the verifier must prove the real
        # t1702 -> PostgreSQL UPSERT path without deleting or manufacturing production data.
        candidate = self._probe.find_completed_investor(start, end)
        insert_mode = False
        if candidate is None:
            candidate = self._probe.find_investor_gap(start, end)
            insert_mode = candidate is not None
        if candidate is None:
            return VerificationResult("Menu 5 end-to-end", False, "t1702 검증 후보가 없습니다.")

        code, day = candidate.stock_code, candidate.trade_date
        raw_before = self._probe.investor_matrix_count(code, day)
        cp_before = self._probe.investor_checkpoint_count(code, day)
        force = not insert_mode
        self._emit(progress, f"[Menu5] 후보 {code} {day} / raw={raw_before}, checkpoint={cp_before}, force={force}")

        out1 = self._commands.run_menu5_single_day(code, day, force_refresh=force)
        raw_after = self._probe.investor_matrix_count(code, day)
        cp_after = self._probe.investor_checkpoint_count(code, day)
        self._emit(progress, f"[Menu5] 1차 rc={out1.return_code}, affected={out1.affected_rows}, raw={raw_after}, checkpoint={cp_after}")
        if out1.return_code != 0 or out1.affected_rows <= 0 or raw_after != 4 or cp_after != 1:
            return VerificationResult(
                "Menu 5 end-to-end", False,
                f"t1702 저장 실패: {code} {day}, rc={out1.return_code}, affected={out1.affected_rows}, raw={raw_after}/4, checkpoint={cp_after}/1",
            )

        out2 = self._commands.run_menu5_single_day(code, day, force_refresh=True)
        raw_after2 = self._probe.investor_matrix_count(code, day)
        cp_after2 = self._probe.investor_checkpoint_count(code, day)
        self._emit(progress, f"[Menu5] 재실행 rc={out2.return_code}, affected={out2.affected_rows}, raw={raw_after2}, checkpoint={cp_after2}")
        if out2.return_code != 0 or out2.affected_rows <= 0 or raw_after2 != 4 or cp_after2 != 1:
            return VerificationResult(
                "Menu 5 end-to-end", False,
                f"t1702 UPSERT/idempotency 실패: {code} {day}, raw={raw_after2}, checkpoint={cp_after2}",
            )
        mode = "신규 4-matrix 저장" if insert_mode else "기존 4-matrix force-refresh"
        return VerificationResult("Menu 5 end-to-end", True, f"{code} {day}: {mode}, 재실행 후 raw=4/checkpoint=1 유지")

    def _verify_menu2(self, as_of: dt.date, progress: Progress | None) -> VerificationResult:
        before = self._probe.menu2_snapshot(as_of)
        self._emit(progress, f"[Menu2] before: {self._snapshot_text(before)}")
        out1 = self._commands.run_menu2_full(as_of)
        after = self._probe.menu2_snapshot(as_of)
        self._emit(progress, f"[Menu2] 1차 rc={out1.return_code}: {self._snapshot_text(after)}")
        problem = self._menu2_problem(out1.return_code, after)
        if problem:
            return VerificationResult("Menu 2 end-to-end", False, problem)

        out2 = self._commands.run_menu2_full(as_of)
        after2 = self._probe.menu2_snapshot(as_of)
        self._emit(progress, f"[Menu2] 2차 rc={out2.return_code}: {self._snapshot_text(after2)}")
        problem = self._menu2_problem(out2.return_code, after2)
        if problem:
            return VerificationResult("Menu 2 end-to-end", False, f"재실행: {problem}")

        stable_fields = ("sector_master", "security_master", "kospi200", "kosdaq150", "sector_daily")
        unstable = [name for name in stable_fields if getattr(after, name) != getattr(after2, name)]
        if unstable:
            return VerificationResult("Menu 2 end-to-end", False, "동일 기준일 재실행 후 row count 변동: " + ", ".join(unstable))
        return VerificationResult(
            "Menu 2 end-to-end", True,
            f"{as_of}: wrapper 2회 성공, KOSPI200={after2.kospi200}, KOSDAQ150={after2.kosdaq150}, 업종일봉={after2.sector_daily}, 중복=0",
        )

    @staticmethod
    def _menu2_problem(return_code: int, snap: Menu2Snapshot) -> str:
        if return_code != 0:
            return f"전체 menu2 wrapper 종료코드={return_code}"
        if snap.sector_master <= 0 or snap.security_master <= 0:
            return f"마스터 저장 부족: sector={snap.sector_master}, security={snap.security_master}"
        if abs(snap.kospi200 - 200) > 5 or abs(snap.kosdaq150 - 150) > 5:
            return f"지수 구성종목 비정상: KOSPI200={snap.kospi200}, KOSDAQ150={snap.kosdaq150}"
        if snap.sector_daily <= 0:
            return "기준일 업종 일봉이 0건입니다."
        if snap.duplicates:
            return f"PK 중복 검출={snap.duplicates}"
        return ""

    @staticmethod
    def _snapshot_text(snap: Menu2Snapshot) -> str:
        return (
            f"sector={snap.sector_master}, security={snap.security_master}, "
            f"K200={snap.kospi200}, KQ150={snap.kosdaq150}, "
            f"sector_daily={snap.sector_daily}, duplicates={snap.duplicates}"
        )

    @staticmethod
    def _emit(progress: Progress | None, message: str) -> None:
        if progress:
            progress(message)
