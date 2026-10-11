from __future__ import annotations

import ctypes
import json
import struct
import sys
from pathlib import Path


EXPORTS = (
    "ETK_Connect",
    "ETK_IsConnected",
    "ETK_Disconnect",
    "ETK_Login",
    "ETK_Logout",
    "ETK_Request",
    "ETK_ReleaseRequestData",
    "ETK_ReleaseMessageData",
    "ETK_GetLastError",
    "ETK_GetErrorMessage",
    "ETK_GetTRCountPerSec",
)


def main() -> int:
    dll_path = Path(sys.argv[1]).resolve()
    bits = struct.calcsize("P") * 8
    result = {
        "ok": False,
        "python_bits": bits,
        "dll": str(dll_path),
        "exports": {},
        "error": "",
    }

    if bits != 32:
        result["error"] = f"32bit helper가 {bits}bit Python에서 실행되었습니다."
        print(json.dumps(result, ensure_ascii=False))
        return 2

    if not dll_path.is_file():
        result["error"] = "XingAPI.dll 파일이 없습니다."
        print(json.dumps(result, ensure_ascii=False))
        return 3

    try:
        lib = ctypes.WinDLL(str(dll_path))
    except Exception as exc:
        result["error"] = f"DLL load 실패: {type(exc).__name__}: {exc}"
        print(json.dumps(result, ensure_ascii=False))
        return 4

    result["exports"] = {name: hasattr(lib, name) for name in EXPORTS}
    result["ok"] = True
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
