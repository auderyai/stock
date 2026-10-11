"""Import every module below a package without starting application entry points."""

from __future__ import annotations

import argparse
import importlib
import pkgutil


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package")
    args = parser.parse_args()
    package = importlib.import_module(args.package)
    failures: list[tuple[str, str]] = []
    names = sorted(
        info.name
        for info in pkgutil.walk_packages(package.__path__, package.__name__ + ".")
        if not info.name.endswith(".__main__")
    )
    for name in names:
        try:
            importlib.import_module(name)
        except Exception as exc:  # report every import boundary consistently
            failures.append((name, f"{type(exc).__name__}: {exc}"))
    for name, error in failures:
        print(f"FAIL {name}: {error}")
    print(f"IMPORTS package={args.package} modules={len(names) + 1} failures={len(failures)}")
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
