from __future__ import annotations

import traceback
from time import perf_counter

from krx_research_nextgen.controllers.screening_controller import ScreeningController
from krx_research_nextgen.infrastructure.task_logging import TaskLog
from krx_research_nextgen.models.screening import ScreeningKind
from krx_research_nextgen.repositories.screening_repository import ScreeningRepository
from krx_research_nextgen.services.screening_service import ScreeningService
from krx_research_nextgen.services.screening_export_service import ScreeningExportService


def run_pass(controller, repo, label: str) -> None:
    print(f"{label}:")
    for kind in ScreeningKind:
        with TaskLog(
            "screening_perf_test",
            pass_name=label,
            kind=kind.value,
            market="ALL",
            limit=10,
        ) as task:
            started = perf_counter()
            rows = controller.run(kind, limit=10, market="ALL")
            elapsed = perf_counter() - started

            task.info(f"elapsed_seconds={elapsed:.6f}")
            task.info(f"result_count={len(rows)}")
            for key, value in repo.last_metrics.items():
                task.info(f"{key}={value}")

            print(
                f" - {kind.value}: rows={len(rows)} "
                f"elapsed={elapsed:.3f}s "
                f"sql={repo.last_metrics.get('sql_seconds', 0):.3f}s "
                f"date={repo.last_metrics.get('date_lookup_seconds', 0):.3f}s "
                f"cache={repo.last_metrics.get('date_cache_hit', False)}"
            )

            if kind != ScreeningKind.HIGH_52W:
                if "range_start_date" in repo.last_metrics:
                    raise RuntimeError(
                        f"Stale range_start_date leaked into {kind.value}"
                    )
                if "range_trade_days" in repo.last_metrics:
                    raise RuntimeError(
                        f"Stale range_trade_days leaked into {kind.value}"
                    )


def main() -> int:
    with TaskLog("stage4_sql_perf3_verification") as rootlog:
        try:
            with ScreeningRepository() as repo:
                service = ScreeningService(repo)
                controller = ScreeningController(service, ScreeningExportService())

                run_pass(controller, repo, "COLD_PASS")
                run_pass(controller, repo, "WARM_PASS")

                rootlog.info("STATUS=SUCCESS")
                print("STAGE4_SQL_PERF3_VERIFY: PASS")
                return 0

        except Exception as exc:
            rootlog.info("STATUS=ERROR")
            rootlog.info(f"EXCEPTION_TYPE={type(exc).__name__}")
            rootlog.info(f"EXCEPTION={exc}")
            for line in traceback.format_exc().rstrip().splitlines():
                rootlog.info("TRACE " + line)
            raise


if __name__ == "__main__":
    raise SystemExit(main())
