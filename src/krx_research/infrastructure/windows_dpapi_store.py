from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
from typing import Any


class _DataBlob(ctypes.Structure):
    _fields_ = (("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte)))


class WindowsDpapiJsonStore:
    """Atomic JSON secret storage protected for the current Windows user."""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()

    def save(self, document: dict[str, Any]) -> None:
        payload = json.dumps(document, ensure_ascii=False).encode("utf-8")
        encrypted = self._crypt(payload, decrypt=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_bytes(encrypted)
        os.replace(temporary, self.path)

    def load(self) -> dict[str, Any]:
        try:
            document = json.loads(self._crypt(self.path.read_bytes(), decrypt=True))
        except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Windows 암호화 자격증명을 읽지 못했습니다.") from exc
        if not isinstance(document, dict):
            raise RuntimeError("Windows 암호화 자격증명 형식이 잘못되었습니다.")
        return document

    @staticmethod
    def _crypt(payload: bytes, *, decrypt: bool) -> bytes:
        if os.name != "nt":
            raise RuntimeError("DPAPI 자격증명은 Windows에서만 사용할 수 있습니다.")
        source_buffer = ctypes.create_string_buffer(payload)
        source = _DataBlob(
            len(payload), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte))
        )
        result = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
        operation.restype = wintypes.BOOL
        ok = operation(
            ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result)
        )
        if not ok:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(result.data, result.size)
        finally:
            ctypes.windll.kernel32.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))
