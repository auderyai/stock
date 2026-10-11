from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ROOT / "src" / "krx_research" / "application" / "xing_runtime",
    ROOT / "scripts" / "test_v39_xing_runtime_gui.py",
]


def iter_python_files():
    for target in TARGETS:
        if target.is_file():
            yield target
        elif target.is_dir():
            yield from target.rglob("*.py")


def main() -> int:
    failures: list[str] = []
    files = list(iter_python_files())
    if not files:
        failures.append("검증 대상 Python 파일이 없습니다.")

    for path in files:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        if "PyQt" in text:
            failures.append(f"{rel}: PyQt 혼용 금지")
        if rel.as_posix().startswith("scripts/") and "collectors.xingdll.direct" in text:
            failures.append(f"{rel}: View/GUI에서 XingDllSession 직접 import 금지")

    # Runtime imports may create __pycache__; packaging removes these directories.

    gui = (ROOT / "scripts" / "test_v39_xing_runtime_gui.py").read_text(encoding="utf-8")
    for required in ("class RuntimeWindow", "class RuntimeController", "class RuntimeWorker"):
        if required not in gui:
            failures.append(f"GUI 계층 누락: {required}")

    if failures:
        print("V39_ARCHITECTURE_CHECK: FAIL")
        for item in failures:
            print(" -", item)
        return 1
    print("V39_ARCHITECTURE_CHECK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
