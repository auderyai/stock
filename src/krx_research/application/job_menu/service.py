from __future__ import annotations

import datetime as dt

from .models import JobKind, JobRequest, JobResult, LegacyJobSpec
from .ports import JobExecutorPort, Progress


class JobMenuApplicationService:
    """Application facade used by the PySide6 job menu.

    The GUI never talks to subprocess, PostgreSQL, DLL, or Xing directly.
    Validated production scripts remain composition roots for every menu item,
    and those scripts instantiate the already-qualified XingDbMenuService.
    """

    def __init__(self, executor: JobExecutorPort) -> None:
        self._executor = executor

    def run(self, request: JobRequest, progress: Progress | None = None) -> JobResult:
        self._validate(request)
        return self._executor.execute(request, progress)

    def run_legacy(self, spec: LegacyJobSpec, progress: Progress | None = None) -> JobResult:
        return self._executor.execute_legacy(spec, progress)

    def cancel(self) -> None:
        self._executor.cancel()

    @staticmethod
    def _validate(request: JobRequest) -> None:
        if request.kind in {JobKind.DRIVE_VERIFY, JobKind.DRIVE_UPDATE}:
            return
        if request.kind == JobKind.DRIVE_CLEANUP:
            if request.end is None:
                raise ValueError("Drive 정리 기준일이 필요합니다.")
            return
        if request.kind == JobKind.MENU_2:
            if request.end is None:
                raise ValueError("메뉴 2 기준일이 필요합니다.")
            return
        if request.start is None or request.end is None:
            raise ValueError(f"메뉴 {int(request.kind)} 시작일/종료일이 필요합니다.")
        if request.start > request.end:
            raise ValueError("시작일이 종료일보다 늦습니다.")
        if request.kind == JobKind.MENU_5 and not 1 <= request.chunk_days <= 90:
            raise ValueError("chunk_days는 1~90이어야 합니다.")
        if request.kind == JobKind.MENU_7:
            allowed = {"NXT", "COMBINED"}
            if not request.venues or any(v not in allowed for v in request.venues):
                raise ValueError("메뉴 7 거래시장은 NXT/COMBINED 중 하나 이상이어야 합니다.")


# 기존 호출부와 외부 실행 파일의 호환성을 유지한다.
Menu257ApplicationService = JobMenuApplicationService
