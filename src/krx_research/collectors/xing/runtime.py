from __future__ import annotations

from dataclasses import dataclass
import platform
import sys
from typing import Any


@dataclass(frozen=True, slots=True)
class XingRuntimeStatus:
    available: bool
    python_architecture: str
    reason: str = ""
    hresult: int | None = None


class XingRuntimeProbe:
    """Check xingAPI COM availability before login/query execution."""

    PROGID = "XA_Session.XASession"

    @classmethod
    def inspect(cls) -> XingRuntimeStatus:
        architecture = platform.architecture()[0]
        if sys.platform != "win32":
            return XingRuntimeStatus(False, architecture, "xingAPI COM은 Windows에서만 사용할 수 있습니다.")
        try:
            import pythoncom  # type: ignore
            import win32com.client  # type: ignore
        except Exception as error:
            return XingRuntimeStatus(False, architecture, f"pywin32를 불러오지 못했습니다: {type(error).__name__}")

        try:
            pythoncom.CoInitialize()
            instance = win32com.client.Dispatch(cls.PROGID)
            del instance
            return XingRuntimeStatus(True, architecture)
        except Exception as error:
            hresult = getattr(error, "hresult", None)
            if hresult is None and getattr(error, "args", None):
                first = error.args[0]
                if isinstance(first, int):
                    hresult = first
            if hresult == -2147221164:
                reason = (
                    "XA_Session.XASession COM 클래스가 등록되어 있지 않습니다. "
                    "LS xingAPI를 설치/등록한 뒤 다시 실행하십시오."
                )
            elif hresult == -2147221021:
                reason = "xingAPI COM 객체를 연결할 수 없습니다. xingAPI 설치/등록 상태를 확인하십시오."
            else:
                reason = f"xingAPI COM 초기화 실패: {type(error).__name__}"
            return XingRuntimeStatus(False, architecture, reason, hresult)
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
