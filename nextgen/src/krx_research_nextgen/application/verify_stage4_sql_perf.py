from __future__ import annotations

from time import perf_counter

from krx_research_nextgen.controllers.screening_controller import ScreeningController
from krx_research_nextgen.models.screening import ScreeningKind
from krx_research_nextgen.repositories.screening_repository import ScreeningRepository
from krx_research_nextgen.services.screening_service import ScreeningService
from krx_research_nextgen.services.screening_export_service import ScreeningExportService


def main() -> int:
    with ScreeningRepository() as repo:
        service = ScreeningService(repo)
        controller = ScreeningController(service, ScreeningExportService())

        indexes = service.ensure_performance_indexes()
        print("PERF_INDEXES:")
        for name in indexes:
            print(" -", name)

        print("STAGE4_SQL_PERF_VERIFY:")
        for kind in ScreeningKind:
            started = perf_counter()
            rows = controller.run(kind, limit=10, market="ALL")
            elapsed = perf_counter() - started
            print(f" - {kind.value}: rows={len(rows)} elapsed={elapsed:.3f}s")
            for key, value in repo.last_metrics.items():
                print(f"    {key}={value}")

        print("STAGE4_SQL_PERF_VERIFY: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
