from __future__ import annotations

from time import perf_counter

from krx_research_nextgen.controllers.screening_controller import ScreeningController
from krx_research_nextgen.models.screening import ScreeningKind
from krx_research_nextgen.repositories.screening_repository import ScreeningRepository
from krx_research_nextgen.services.screening_service import ScreeningService
from krx_research_nextgen.services.screening_export_service import ScreeningExportService


UNIVERSES = ("ALL", "KOSPI", "KOSDAQ", "KOSPI200", "KOSDAQ150")


def main() -> int:
    with ScreeningRepository() as repo:
        service = ScreeningService(repo)
        controller = ScreeningController(service, ScreeningExportService())

        latest = repo.latest_trade_date()
        status = repo.universe_status(latest)

        print("UNIVERSE_STATUS:")
        for key, value in status.items():
            print(f" - {key}={value}")

        k200 = int(status.get("kospi200_count", 0))
        kq150 = int(status.get("kosdaq150_count", 0))

        if not 180 <= k200 <= 220:
            raise RuntimeError(
                f"KOSPI200 membership unresolved/abnormal: {k200}; "
                f"status={status}"
            )
        if not 130 <= kq150 <= 170:
            raise RuntimeError(
                f"KOSDAQ150 membership unresolved/abnormal: {kq150}; "
                f"status={status}"
            )

        print("UNIVERSE_TOPN_VERIFY:")
        for universe in UNIVERSES:
            for kind in ScreeningKind:
                started = perf_counter()
                rows = controller.run(kind, limit=10, market=universe)
                elapsed = perf_counter() - started
                if len(rows) > 10:
                    raise RuntimeError(
                        f"TOP-N violation: {universe}/{kind.value}/{len(rows)}"
                    )
                print(
                    f" - {universe:9s} | {kind.value:12s} | "
                    f"rows={len(rows):2d} elapsed={elapsed:.3f}s"
                )

        print("UNIVERSE_TOPN_VERIFY: PASS")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
