from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import struct
import time
from typing import Any, Mapping

from krx_research.collectors.xing.credentials import XingCredentials
from krx_research.collectors.xing_schema import PacketCodec, TrSchemaService


WM_USER = 0x0400
XM_DISCONNECT = WM_USER + 1
XM_RECEIVE_DATA = WM_USER + 3
XM_LOGIN = WM_USER + 5
XM_LOGOUT = WM_USER + 6
XM_TIMEOUT = WM_USER + 7

REQUEST_DATA = 1
MESSAGE_DATA = 2
SYSTEM_ERROR_DATA = 3
RELEASE_DATA = 4

HWND_MESSAGE = -3
PM_REMOVE = 0x0001

_VERSION_RE = re.compile(r"xingAPI_Program\((20\d{2})[._-](\d{2})[._-](\d{2})\)", re.I)

# These are continuation fields confirmed by the currently-used TR definitions.
CONTINUATION_FIELD = {
    "t1516": "shcode",
    "t8429": "cts_date",
    "t8451": "cts_date",
}
MAX_PAGES = 100


class XingDllError(RuntimeError):
    pass


class RECV_PACKET(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("nRqID", ctypes.c_int),
        ("nDataLength", ctypes.c_int),
        ("nTotalDataBufferSize", ctypes.c_int),
        ("nElapsedTime", ctypes.c_int),
        ("nDataMode", ctypes.c_int),
        ("szTrCode", ctypes.c_char * 11),
        ("cCont", ctypes.c_char * 1),
        ("szContKey", ctypes.c_char * 19),
        ("szUserData", ctypes.c_char * 31),
        ("szBlockName", ctypes.c_char * 17),
        ("lpData", ctypes.c_void_p),
    ]


class MSG_PACKET(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("nRqID", ctypes.c_int),
        ("nIsSystemError", ctypes.c_int),
        ("szMsgCode", ctypes.c_char * 6),
        ("nMsgLength", ctypes.c_int),
        ("lpszMessageData", ctypes.c_void_p),
    ]


@dataclass(slots=True)
class RequestState:
    request_id: int = 0
    blocks: dict[str, list[bytes]] = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)
    system_error: str = ""
    continuation: bool = False
    continuation_key: str = ""
    released: bool = False
    timed_out: bool = False
    input_buffer: Any = None


class HiddenMessageWindow:
    """One message-only Win32 window. The DLL posts login/TR events here."""

    def __init__(self, callback) -> None:
        if os.name != "nt":
            raise XingDllError("xingAPI DLL은 Windows에서만 실행할 수 있습니다.")
        self.callback = callback
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.hwnd = None
        self._wndproc = None
        self._class_name = f"NewStockXingDllWorker_{os.getpid()}"

    def create(self) -> int:
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(
            LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        self.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self.kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        hinst = self.kernel32.GetModuleHandleW(None)

        @WNDPROC
        def wndproc(hwnd, msg, wparam, lparam):
            if msg in {
                XM_DISCONNECT, XM_RECEIVE_DATA, XM_LOGIN, XM_LOGOUT, XM_TIMEOUT
            }:
                try:
                    return int(self.callback(int(msg), int(wparam), int(lparam)) or 0)
                except Exception:
                    # Never unwind a Python exception through a Win32 callback.
                    return 0
            return self.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc = wndproc
        wc = WNDCLASSW()
        wc.lpfnWndProc = wndproc
        wc.hInstance = hinst
        wc.lpszClassName = self._class_name

        self.user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        self.user32.RegisterClassW.restype = wintypes.ATOM
        atom = self.user32.RegisterClassW(ctypes.byref(wc))
        if not atom:
            err = ctypes.get_last_error()
            # 1410 = class already exists; unique class names make this very unlikely.
            if err != 1410:
                raise XingDllError(f"RegisterClassW 실패: WinError={err}")

        self.user32.DefWindowProcW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        ]
        self.user32.DefWindowProcW.restype = ctypes.c_ssize_t

        self.user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]
        self.user32.CreateWindowExW.restype = wintypes.HWND
        hwnd = self.user32.CreateWindowExW(
            0, self._class_name, self._class_name, 0,
            0, 0, 0, 0, wintypes.HWND(HWND_MESSAGE), None, hinst, None,
        )
        if not hwnd:
            raise XingDllError(f"CreateWindowExW 실패: WinError={ctypes.get_last_error()}")
        self.hwnd = int(hwnd)
        return self.hwnd

    def pump_once(self) -> None:
        class POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt", POINT),
            ]

        msg = MSG()
        self.user32.PeekMessageW.argtypes = [
            ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT
        ]
        self.user32.PeekMessageW.restype = wintypes.BOOL
        while self.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            self.user32.TranslateMessage(ctypes.byref(msg))
            self.user32.DispatchMessageW(ctypes.byref(msg))

    def close(self) -> None:
        if self.hwnd:
            try:
                self.user32.DestroyWindow(self.hwnd)
            finally:
                self.hwnd = None


class XingDllLibrary:
    """Thin stdcall adapter. No TR-specific logic is allowed in this class."""

    def __init__(self, dll_path: Path) -> None:
        self.dll_path = Path(dll_path).resolve()
        if not self.dll_path.is_file():
            raise XingDllError(f"XingAPI.dll 없음: {self.dll_path}")

        self.lib = ctypes.WinDLL(str(self.dll_path), use_last_error=True)

        self.connect = self._fn(
            "ETK_Connect", wintypes.BOOL,
            wintypes.HWND, ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        )
        self.is_connected = self._fn("ETK_IsConnected", wintypes.BOOL)
        self.login = self._fn(
            "ETK_Login", wintypes.BOOL,
            wintypes.HWND, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, wintypes.BOOL,
        )
        self.logout = self._fn("ETK_Logout", wintypes.BOOL, wintypes.HWND)
        self.request = self._fn(
            "ETK_Request", ctypes.c_int,
            wintypes.HWND, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_int,
            wintypes.BOOL, ctypes.c_char_p, ctypes.c_int,
        )
        self.release_request = self._fn("ETK_ReleaseRequestData", None, ctypes.c_int)
        self.release_message = self._fn("ETK_ReleaseMessageData", None, wintypes.LPARAM)
        self.get_last_error = self._fn("ETK_GetLastError", ctypes.c_int)
        self.get_error_message = self._fn(
            "ETK_GetErrorMessage", ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int
        )
        self.get_tr_count_per_sec = self._fn(
            "ETK_GetTRCountPerSec", ctypes.c_int, ctypes.c_char_p
        )

    def _fn(self, name, restype, *argtypes):
        try:
            fn = getattr(self.lib, name)
        except AttributeError as exc:
            raise XingDllError(f"{name} export 없음") from exc
        fn.restype = restype
        fn.argtypes = list(argtypes)
        return fn

    def error_text(self) -> str:
        code = int(self.get_last_error())
        buf = ctypes.create_string_buffer(1024)
        n = int(self.get_error_message(code, buf, len(buf)))
        raw = buf.raw[:max(n, 0)] if n > 0 else buf.value
        return f"{code}: {raw.decode('cp949', errors='replace').strip()}"


def _c_string(pointer: int, *, limit: int = 2048) -> str:
    if not pointer:
        return ""
    raw = ctypes.string_at(pointer, limit)
    raw = raw.split(b"\x00", 1)[0]
    return raw.decode("cp949", errors="replace").strip()


class XingDllSession:
    """Persistent connection/login + one common request path for every TR."""

    def __init__(
        self,
        project_root: Path,
        credentials: XingCredentials,
        *,
        timeout: float = 30.0,
        delay: float = 0.08,
    ) -> None:
        if struct.calcsize("P") * 8 != 32:
            raise XingDllError("XingDllSession은 32bit Python 전용입니다.")
        if ctypes.sizeof(RECV_PACKET) != 103 or ctypes.sizeof(MSG_PACKET) != 22:
            raise XingDllError(
                f"xingAPI ABI 크기 불일치: RECV_PACKET={ctypes.sizeof(RECV_PACKET)}, "
                f"MSG_PACKET={ctypes.sizeof(MSG_PACKET)}"
            )
        self.root = Path(project_root).resolve()
        self.credentials = credentials
        self.timeout = max(1.0, float(timeout))
        self.delay = max(0.0, float(delay))
        self.schemas = TrSchemaService(self.root)
        self.codec = PacketCodec()
        self.install_root = self._discover_install_root()
        self.api = XingDllLibrary(self.install_root / "XingAPI.dll")
        self.window = HiddenMessageWindow(self._on_message)
        self.hwnd = self.window.create()
        self.login_done = False
        self.login_ok = False
        self.login_message = ""
        self.current: RequestState | None = None
        self._last_request = 0.0

    @staticmethod
    def _discover_install_root() -> Path:
        explicit = os.getenv("LS_XING_INSTALL_ROOT", "").strip().strip('"')
        if explicit:
            p = Path(explicit)
            if (p / "XingAPI.dll").is_file():
                return p.resolve()

        base = Path(r"C:\LS_SEC")
        candidates: list[tuple[tuple[int, int, int], Path]] = []
        if base.is_dir():
            for child in base.iterdir():
                if not child.is_dir():
                    continue
                m = _VERSION_RE.fullmatch(child.name)
                if m and (child / "XingAPI.dll").is_file():
                    candidates.append((tuple(map(int, m.groups())), child))
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1].resolve()

        legacy = base / "xingAPI"
        if (legacy / "XingAPI.dll").is_file():
            return legacy.resolve()
        raise XingDllError("LS xingAPI 설치 폴더를 찾지 못했습니다.")

    def connect(self) -> None:
        if self.api.is_connected():
            return
        server = os.getenv("LS_XING_SERVER", "api.ls-sec.co.kr").strip()
        port = int(os.getenv("LS_XING_PORT", "20001"))
        ok = bool(
            self.api.connect(
                self.hwnd,
                server.encode("ascii"),
                port,
                WM_USER,
                -1,
                -1,
            )
        )
        if not ok:
            raise XingDllError(f"ETK_Connect 실패: {self.api.error_text()}")

        self.login_done = False
        self.login_ok = False
        self.login_message = ""
        ok = bool(
            self.api.login(
                self.hwnd,
                self.credentials.user_id.encode("cp949"),
                self.credentials.password.encode("cp949"),
                self.credentials.cert_password.encode("cp949"),
                0,
                False,
            )
        )
        if not ok:
            raise XingDllError(f"ETK_Login 호출 실패: {self.api.error_text()}")

        deadline = time.monotonic() + self.timeout
        while not self.login_done:
            self.window.pump_once()
            if time.monotonic() >= deadline:
                raise XingDllError("xingAPI 로그인 응답 시간 초과")
            time.sleep(0.01)

        if not self.login_ok:
            raise XingDllError(f"xingAPI 로그인 실패: {self.login_message}")

    def close(self) -> None:
        try:
            if self.api.is_connected():
                try:
                    self.api.logout(self.hwnd)
                except Exception:
                    pass
        finally:
            self.window.close()

    def request(self, tr_code: str, values: Mapping[str, Any]) -> dict[str, Any]:
        self.connect()
        schema = self.schemas.load(tr_code)
        if not schema.input_blocks:
            raise XingDllError(f"{tr_code}: 입력 블록 없음")
        in_block = schema.input_blocks[0]

        mutable_values = {str(k): v for k, v in values.items()}
        rows: list[dict[str, Any]] = []
        header: dict[str, Any] = {}
        continuation_key = ""
        is_next = False

        for page in range(MAX_PAGES):
            elapsed = time.monotonic() - self._last_request
            if elapsed < self.delay:
                time.sleep(self.delay - elapsed)

            packet = self.codec.encode(in_block, mutable_values)
            state = self._request_page(
                tr_code,
                packet,
                is_next=is_next,
                continuation_key=continuation_key,
            )
            self._last_request = time.monotonic()

            decoded = self._decode_state(schema, state)
            rows.extend(decoded["rows"])
            header.update(decoded["header"])

            continuation_field = CONTINUATION_FIELD.get(tr_code)
            field_value = str(header.get(continuation_field) or "").strip() if continuation_field else ""

            # Prefer the DLL continuation signal/key. For A-header TRs, the confirmed
            # output continuation field is used as the next input value.
            if not state.continuation:
                break

            if continuation_field and field_value:
                mutable_values[continuation_field] = field_value

            continuation_key = state.continuation_key
            is_next = True
        else:
            raise XingDllError(f"{tr_code}: 연속조회 {MAX_PAGES}페이지 제한 초과")

        return {"rows": rows, "header": header}

    def _request_page(
        self,
        tr_code: str,
        packet: bytes,
        *,
        is_next: bool,
        continuation_key: str,
    ) -> RequestState:
        buf = ctypes.create_string_buffer(packet, len(packet))
        state = RequestState(input_buffer=buf)
        request_id = int(
            self.api.request(
                self.hwnd,
                tr_code.encode("ascii"),
                ctypes.cast(buf, ctypes.c_void_p),
                len(packet),
                bool(is_next),
                continuation_key.encode("ascii"),
                int(self.timeout),
            )
        )
        if request_id <= 0:
            raise XingDllError(f"{tr_code} ETK_Request 실패: {self.api.error_text()}")

        state.request_id = request_id
        self.current = state
        deadline = time.monotonic() + self.timeout

        try:
            while not state.released:
                self.window.pump_once()
                if state.system_error:
                    raise XingDllError(f"{tr_code}: {state.system_error}")
                if state.timed_out or time.monotonic() >= deadline:
                    raise XingDllError(f"{tr_code}: 조회 응답 시간 초과")
                time.sleep(0.005)
            return state
        finally:
            self.current = None

    def _decode_state(self, schema, state: RequestState) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        header: dict[str, Any] = {}

        for block_name, chunks in state.blocks.items():
            try:
                block = schema.block(block_name)
            except KeyError:
                continue

            for raw in chunks:
                if block.occurs:
                    rows.extend(self.codec.decode_occurs(block, raw))
                else:
                    header.update(self.codec.decode_one(block, raw))
        return {"rows": rows, "header": header}

    def _on_message(self, msg: int, wparam: int, lparam: int) -> int:
        if msg == XM_LOGIN:
            code = _c_string(wparam, limit=64)
            message = _c_string(lparam, limit=2048)
            self.login_done = True
            self.login_ok = code in {"0000", "0"}
            self.login_message = f"[{code}] {message}".strip()
            return 1

        if msg == XM_DISCONNECT:
            if self.current:
                self.current.system_error = "서버 연결이 끊겼습니다."
                self.current.released = True
            return 1

        if msg == XM_TIMEOUT:
            if self.current and (not lparam or self.current.request_id == int(lparam)):
                self.current.timed_out = True
                self.current.released = True
            return 1

        if msg != XM_RECEIVE_DATA:
            return 0

        if wparam == REQUEST_DATA:
            packet = ctypes.cast(lparam, ctypes.POINTER(RECV_PACKET)).contents
            if not self.current or packet.nRqID != self.current.request_id:
                return 1

            block_name = bytes(packet.szBlockName).split(b"\x00", 1)[0].decode(
                "ascii", errors="replace"
            ).strip()
            raw = (
                ctypes.string_at(packet.lpData, packet.nDataLength)
                if packet.lpData and packet.nDataLength > 0
                else b""
            )
            self.current.blocks.setdefault(block_name, []).append(raw)
            cont = bytes(packet.cCont).decode("ascii", errors="ignore").strip()
            self.current.continuation = cont in {"1", "Y"}
            self.current.continuation_key = bytes(packet.szContKey).split(
                b"\x00", 1
            )[0].decode("ascii", errors="ignore").strip()
            return 1

        if wparam in {MESSAGE_DATA, SYSTEM_ERROR_DATA}:
            packet = ctypes.cast(lparam, ctypes.POINTER(MSG_PACKET)).contents
            message = (
                ctypes.string_at(packet.lpszMessageData, packet.nMsgLength).decode(
                    "cp949", errors="replace"
                ).strip()
                if packet.lpszMessageData and packet.nMsgLength > 0
                else ""
            )
            code = bytes(packet.szMsgCode).split(b"\x00", 1)[0].decode(
                "ascii", errors="replace"
            ).strip()
            text = f"[{code}] {message}".strip()
            if self.current and packet.nRqID == self.current.request_id:
                self.current.messages.append(text)
                if wparam == SYSTEM_ERROR_DATA or packet.nIsSystemError:
                    self.current.system_error = text
            self.api.release_message(lparam)
            return 1

        if wparam == RELEASE_DATA:
            if self.current and int(lparam) == self.current.request_id:
                self.current.released = True
            self.api.release_request(int(lparam))
            return 1

        return 0

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()
