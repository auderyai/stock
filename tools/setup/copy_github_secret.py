from __future__ import annotations

import argparse
import ctypes
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.cloud_sync.credentials import DriveCredentials
from krx_research.collectors.ls_credentials import load_ls_credentials


SECRET_NAMES = (
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REFRESH_TOKEN",
    "GOOGLE_DRIVE_FOLDER_ID",
    "DRIVE_ARCHIVE_KEY",
    "LS_APP_KEY",
    "LS_APP_SECRET",
)


def _set_clipboard(value: str) -> None:
    if sys.platform != "win32":
        raise RuntimeError("이 도구는 Windows 전용입니다.")
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    kernel32.GlobalAlloc.argtypes = (ctypes.c_uint, ctypes.c_size_t)
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalUnlock.restype = ctypes.c_int
    kernel32.GlobalFree.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalFree.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = (ctypes.c_uint, ctypes.c_void_p)
    user32.SetClipboardData.restype = ctypes.c_void_p
    if not user32.OpenClipboard(None):
        raise RuntimeError("클립보드를 열 수 없습니다.")
    handle = None
    try:
        user32.EmptyClipboard()
        encoded = (value + "\0").encode("utf-16-le")
        handle = kernel32.GlobalAlloc(0x0002, len(encoded))
        if not handle:
            raise ctypes.WinError()
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            raise ctypes.WinError()
        try:
            ctypes.memmove(pointer, encoded, len(encoded))
        finally:
            kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(13, handle):
            raise ctypes.WinError()
        handle = None
    finally:
        user32.CloseClipboard()
        if handle:
            kernel32.GlobalFree(handle)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="비밀값을 출력하지 않고 GitHub Actions Secret 하나를 클립보드에 복사"
    )
    parser.add_argument("name", choices=SECRET_NAMES)
    args = parser.parse_args()
    drive = DriveCredentials.from_windows_store(
        ROOT / "config" / "google_drive_oauth.dpapi"
    )
    ls_key, ls_secret = load_ls_credentials(ROOT)
    values = {
        "GOOGLE_CLIENT_ID": drive.client_id,
        "GOOGLE_CLIENT_SECRET": drive.client_secret,
        "GOOGLE_REFRESH_TOKEN": drive.refresh_token,
        "GOOGLE_DRIVE_FOLDER_ID": drive.root_folder_id,
        "DRIVE_ARCHIVE_KEY": drive.archive_key,
        "LS_APP_KEY": ls_key,
        "LS_APP_SECRET": ls_secret,
    }
    _set_clipboard(values[args.name])
    print(f"{args.name}: 클립보드 복사 완료(값은 출력하지 않음)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
