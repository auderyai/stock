from __future__ import annotations

import traceback
from time import perf_counter

from krx_research_nextgen.controllers.screening_controller import ScreeningController
from krx_research_nextgen.infrastructure.task_logging import TaskLog
from krx_research_nextgen.models.screening import ScreeningKind
from krx_research_nextgen.repositories.screening_repository import ScreeningRepository
from krx_research_nextgen.services.screening_service import ScreeningService
from krx_research_nextgen.services.screening_export_service import ScreeningExportService


def main() -> int:
    with TaskLog("stage4_sql_perf_verification") as rootlog:
        try:
            with ScreeningRepository() as repo:
                service = ScreeningService(repo)
                controller = ScreeningController(service, ScreeningExportService())

                index_results = service.ensure_performance_indexes()

                rootlog.info("INDEX CHECK RESULTS")
                for item in index_results:
                    rootlog.info(
                        f"index={item.get('index')} "
                        f"status={item.get('status')} "
                        f"detail={item.get('detail')}"
                    )

                print("PERF_INDEX_CHECK:")
                for item in index_results:
                    print(f" - {item.get('index')}: {item.get('status')}")

                print("STAGE4_SQL_PERF_VERIFY_2:")

                for kind in ScreeningKind:
                    with TaskLog(
                        "screening_perf_test",
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
                            f" - {kind.value}: "
                            f"rows={len(rows)} elapsed={elapsed:.3f}s"
                        )

                rootlog.info("STATUS=SUCCESS")
                print("STAGE4_SQL_PERF_VERIFY_2: PASS")
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
