from __future__ import annotations

import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[4]
NEXTGEN_SRC = ROOT / "nextgen" / "src"
if str(NEXTGEN_SRC) not in sys.path:
    sys.path.insert(0, str(NEXTGEN_SRC))

from krx_research_nextgen.controllers.screening_controller import ScreeningController
from krx_research_nextgen.infrastructure.log_paths import LOG_PATHS
from krx_research_nextgen.models.screening import ScreeningKind
from krx_research_nextgen.repositories.screening_repository import ScreeningRepository
from krx_research_nextgen.services.screening_service import ScreeningService
from krx_research_nextgen.services.screening_export_service import ScreeningExportService


# Build legacy names dynamically so path-normalization scripts cannot rewrite
# this verifier's own guard strings.
LEGACY_RUNTIME = "_" + "runtime_migration_logs"
LEGACY_DATABASE = "_" + "db_migration_logs"
FORBIDDEN = (LEGACY_RUNTIME, LEGACY_DATABASE)


def scan_forbidden_log_paths() -> list[str]:
    hits: list[str] = []
    skip_exact = {
        ".git",
        ".venv_finplot",
        "logs",
        "_rollback",
        "POSTGRESQL_BACKUP",
    }

    for ext in ("*.py", "*.cmd", "*.bat", "*.ps1"):
        for path in ROOT.rglob(ext):
            try:
                parts = path.relative_to(ROOT).parts
            except ValueError:
                continue

            if any(part in skip_exact for part in parts):
                continue

            # Ignore temporary patch/extraction folders at the project root.
            if parts and parts[0].upper().startswith("C_STOCK_"):
                continue

            # Ignore this verifier itself.
            if path.name == Path(__file__).name:
                continue

            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                try:
                    text = path.read_text(encoding="utf-8-sig")
                except Exception:
                    continue

            for token in FORBIDDEN:
                if token in text:
                    hits.append(f"{path}: {token}")

    return hits


def main() -> int:
    print("LOG_PATHS:")
    print(" runtime =", LOG_PATHS.runtime)
    print(" database=", LOG_PATHS.database)
    print(" tasks   =", LOG_PATHS.tasks)
    print(" plans   =", LOG_PATHS.plans)

    # Physical root-folder guard.
    legacy_dirs = [
        ROOT / LEGACY_RUNTIME,
        ROOT / LEGACY_DATABASE,
    ]
    existing = [str(p) for p in legacy_dirs if p.exists()]
    if existing:
        print("LEGACY_ROOT_LOG_DIRS_EXIST:")
        for p in existing:
            print(" -", p)
        return 3

    hits = scan_forbidden_log_paths()
    if hits:
        print("FORBIDDEN_LEGACY_LOG_PATH_REFERENCES:")
        for hit in hits:
            print(" -", hit)
        return 2

    with ScreeningRepository() as repo:
        service = ScreeningService(repo)
        controller = ScreeningController(service, ScreeningExportService())

        print("HOTFIX6B_BENCHMARK:")
        for pass_name in ("COLD_PASS", "WARM_PASS"):
            print(pass_name + ":")
            for kind in ScreeningKind:
                started = perf_counter()
                rows = controller.run(kind, limit=10, market="ALL")
                elapsed = perf_counter() - started
                print(
                    f" - {kind.value}: rows={len(rows)} "
                    f"elapsed={elapsed:.3f}s "
                    f"sql={float(repo.last_metrics.get('sql_seconds', 0)):.3f}s "
                    f"date={float(repo.last_metrics.get('date_lookup_seconds', 0)):.3f}s "
                    f"cache={repo.last_metrics.get('date_cache_hit', False)} "
                    f"method={repo.last_metrics.get('date_lookup_method', '')}"
                )

    print("HOTFIX6B_VERIFY: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
