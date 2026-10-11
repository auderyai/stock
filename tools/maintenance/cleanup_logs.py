from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(r"C:\stock")
LOG_ROOT = ROOT / "logs"

STAMP_RE = re.compile(
    r"([_-])20\d{6}(?:[_-]\d{6})?(?=\.[^.]+$)",
    re.I,
)

RUNTIME_KEEP_EXACT = {
    "run_krx_menu_runtime.log",
    "run_workstation_gui_runtime.log",
}

RUNTIME_KEEP_LATEST_PATTERNS = (
    "stage4_mainwindow_reset_final_v1_*.log",
)


def family_key(path: Path) -> str:
    return STAMP_RE.sub("", path.name).lower()


def newest(pattern: str, folder: Path) -> Path | None:
    items = [p for p in folder.glob(pattern) if p.is_file()]
    if not items:
        return None
    return max(items, key=lambda p: (p.stat().st_mtime, p.name))


def strict_runtime_cleanup(
    current_log: Path | None,
    quiet: bool,
) -> tuple[int, int]:
    folder = LOG_ROOT / "runtime"
    folder.mkdir(parents=True, exist_ok=True)

    keep: set[Path] = set()

    if current_log and current_log.exists():
        keep.add(current_log.resolve())

    for name in RUNTIME_KEEP_EXACT:
        p = folder / name
        if p.exists():
            keep.add(p.resolve())

    for pattern in RUNTIME_KEEP_LATEST_PATTERNS:
        p = newest(pattern, folder)
        if p:
            keep.add(p.resolve())

    deleted = failed = 0

    for p in folder.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".log", ".txt"}:
            continue
        if p.resolve() in keep:
            continue

        try:
            p.unlink()
            deleted += 1
            if not quiet:
                print(f"DELETE_RUNTIME_LOG={p}")
        except PermissionError:
            # Nonessential locked logs can be retried next run,
            # but do not fail the entire cleanup operation.
            if not quiet:
                print(f"SKIP_LOCKED_RUNTIME_LOG={p}")
        except Exception as exc:
            failed += 1
            if not quiet:
                print(
                    f"WARN_RUNTIME_LOG={p} "
                    f"error={type(exc).__name__}:{exc}"
                )

    return deleted, failed


def latest_per_family_cleanup(
    folder: Path,
    keep_count: int,
    quiet: bool,
) -> tuple[int, int]:
    folder.mkdir(parents=True, exist_ok=True)

    groups: dict[str, list[Path]] = {}

    for p in folder.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".log", ".txt"}:
            continue
        groups.setdefault(family_key(p), []).append(p)

    deleted = failed = 0

    for items in groups.values():
        items.sort(
            key=lambda p: (p.stat().st_mtime, p.name),
            reverse=True,
        )

        for p in items[keep_count:]:
            try:
                p.unlink()
                deleted += 1
                if not quiet:
                    print(f"DELETE_OLD_LOG={p}")
            except PermissionError:
                if not quiet:
                    print(f"SKIP_LOCKED_OLD_LOG={p}")
            except Exception as exc:
                failed += 1
                if not quiet:
                    print(
                        f"WARN_OLD_LOG={p} "
                        f"error={type(exc).__name__}:{exc}"
                    )

    return deleted, failed


def compact_latest_session(
    path: Path,
    delimiter: str,
    quiet: bool,
) -> tuple[bool, bool]:
    if not path.exists():
        return False, False

    try:
        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except PermissionError:
        if not quiet:
            print(f"SKIP_LOCKED_ACTIVE_LOG={path}")
        return False, True

    positions = []
    start = 0

    while True:
        idx = text.find(delimiter, start)
        if idx < 0:
            break
        positions.append(idx)
        start = idx + len(delimiter)

    if len(positions) <= 1:
        return False, False

    latest = text[positions[-1]:].lstrip("\r\n")

    try:
        path.write_text(latest, encoding="utf-8")
    except PermissionError:
        if not quiet:
            print(f"SKIP_LOCKED_ACTIVE_LOG={path}")
        return False, True

    return True, False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--current-log", default="")
    parser.add_argument("--keep", type=int, default=1)
    args = parser.parse_args()

    current_log = (
        Path(args.current_log).resolve()
        if args.current_log
        else None
    )

    deleted = failed = compacted = locked = 0

    if args.strict:
        d, f = strict_runtime_cleanup(
            current_log=current_log,
            quiet=args.quiet,
        )
        deleted += d
        failed += f

        for name in ("database", "tasks", "plans"):
            d, f = latest_per_family_cleanup(
                LOG_ROOT / name,
                keep_count=1,
                quiet=args.quiet,
            )
            deleted += d
            failed += f
    else:
        for name in ("runtime", "database", "tasks", "plans"):
            d, f = latest_per_family_cleanup(
                LOG_ROOT / name,
                keep_count=max(1, args.keep),
                quiet=args.quiet,
            )
            deleted += d
            failed += f

    for name in (
        "run_krx_menu_runtime.log",
        "run_workstation_gui_runtime.log",
    ):
        p = LOG_ROOT / "runtime" / name

        try:
            did_compact, was_locked = compact_latest_session(
                p,
                "==================================================",
                quiet=args.quiet,
            )
            if did_compact:
                compacted += 1
                if not args.quiet:
                    print(f"COMPACT_LOG={p}")
            if was_locked:
                locked += 1
        except Exception as exc:
            failed += 1
            if not args.quiet:
                print(
                    f"WARN_COMPACT={p} "
                    f"error={type(exc).__name__}:{exc}"
                )

    if not args.quiet:
        print(f"deleted_log_count={deleted}")
        print(f"compacted_log_count={compacted}")
        print(f"locked_active_log_count={locked}")
        print(f"failed_count={failed}")

    # Locked active logs are expected and are not cleanup failures.
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
