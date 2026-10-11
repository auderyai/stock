from __future__ import annotations

import json
import platform
import sys
from pathlib import Path


def environment_summary() -> dict[str, object]:
    project_root = Path(__file__).resolve().parents[2]
    return {
        "project_root": str(project_root),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "architecture": platform.architecture()[0],
        "machine": platform.machine(),
        "cpu_only": True,
    }


def main() -> int:
    print(json.dumps(environment_summary(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())