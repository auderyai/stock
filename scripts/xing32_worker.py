from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.collectors.xing.credentials import XingCredentialResolver
from krx_research.collectors.xingdll import XingDllSession


class Xing32Worker:
    """One login, one DLL session, one common TrSchema/PacketCodec path."""

    def __init__(self, delay: float, timeout: float) -> None:
        if struct.calcsize("P") * 8 != 32:
            raise RuntimeError("xing32_worker.py는 32bit Python 전용입니다.")
        self.session = XingDllSession(
            ROOT,
            XingCredentialResolver(ROOT).load(),
            timeout=timeout,
            delay=delay,
        )

    def connect(self) -> None:
        self.session.connect()

    def close(self) -> None:
        self.session.close()

    def dispatch(self, req: dict[str, Any]) -> dict[str, Any]:
        operation = req.get("operation")
        if operation == "shutdown":
            return {"shutdown": True}
        if operation != "raw_tr":
            raise ValueError(f"지원하지 않는 worker operation: {operation}")

        tr = str(req.get("tr") or "").lower()
        values = req.get("values")
        if not isinstance(values, dict):
            raise ValueError("values는 dict여야 합니다.")

        return {
            "result": self.session.request(
                tr,
                {str(k): v for k, v in values.items()},
            )
        }


def emit(obj: dict[str, Any]) -> None:
    print(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--delay", type=float, default=.08)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    if not args.serve:
        parser.error("--serve가 필요합니다.")

    worker = Xing32Worker(args.delay, args.timeout)
    try:
        worker.connect()
        emit({"ok": True, "ready": True, "transport": "XingAPI.dll"})
        for line in sys.stdin:
            try:
                result = worker.dispatch(json.loads(line))
                emit({"ok": True, **result})
                if result.get("shutdown"):
                    return 0
            except Exception as exc:
                emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return 0
    finally:
        worker.close()


if __name__ == "__main__":
    raise SystemExit(main())
