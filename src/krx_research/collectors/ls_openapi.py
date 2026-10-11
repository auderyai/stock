"""Read-only LS Securities OPEN API t8451 client.

Credentials are only taken from the current process environment or from a
current-Windows-user DPAPI encrypted file. Never log tokens or secrets.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import datetime as dt
import json
import os
from pathlib import Path
import time
from typing import Any

import pandas as pd
import requests

from .xing_t8451 import T8451_VENUES, normalize_t8451_rows

BASE = "https://openapi.ls-sec.co.kr:8080"
TOKEN_URL = BASE + "/oauth2/token"
CHART_URL = BASE + "/stock/chart"


class LSOpenApiError(RuntimeError):
    pass


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(raw: bytes) -> tuple[_Blob, Any]:
    buffer = ctypes.create_string_buffer(raw)
    return _Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _crypt(raw: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise LSOpenApiError("암호화된 키는 키를 등록한 Windows 사용자 계정에서만 열 수 있습니다.")
    source, buffer = _blob(raw)
    result = _Blob()
    crypt32 = ctypes.windll.crypt32
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    operation.restype = wintypes.BOOL
    if decrypt:
        ok = operation(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result))
    else:
        ok = operation(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result))
    if not ok:
        raise LSOpenApiError("Windows 사용자 암호화 키를 읽지 못했습니다.")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        local_free = ctypes.windll.kernel32.LocalFree
        local_free.argtypes = [ctypes.c_void_p]
        local_free.restype = ctypes.c_void_p
        local_free(ctypes.cast(result.pbData, ctypes.c_void_p))


def credential_file(project_root: Path) -> Path:
    return project_root / "config" / "ls_openapi_credentials.dpapi"


def env_file(project_root: Path) -> Path:
    return project_root / "config" / "ls_openapi.env"


def save_env_credentials(project_root: Path, appkey: str, appsecret: str) -> None:
    """Save a dedicated .env file; never overwrite an existing file implicitly."""
    if not appkey.strip() or not appsecret.strip():
        raise ValueError("APP KEY와 SECRET KEY가 모두 필요합니다.")
    path = env_file(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"LS_APP_KEY={json.dumps(appkey.strip())}\nLS_APP_SECRET={json.dumps(appsecret.strip())}\n"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _read_env_file(path: Path) -> tuple[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        if sep and name.strip() in ("LS_APP_KEY", "LS_APP_SECRET"):
            value = value.strip()
            values[name.strip()] = str(json.loads(value)) if value.startswith('"') else value
    key, secret = values.get("LS_APP_KEY", "").strip(), values.get("LS_APP_SECRET", "").strip()
    if not key or not secret:
        raise LSOpenApiError(f"{path.name}에 LS_APP_KEY와 LS_APP_SECRET이 모두 필요합니다.")
    return key, secret


def save_credentials(project_root: Path, appkey: str, appsecret: str) -> None:
    if not appkey.strip() or not appsecret.strip():
        raise ValueError("APP KEY와 SECRET KEY가 모두 필요합니다.")
    path = credential_file(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    packed = json.dumps({"appkey": appkey.strip(), "appsecretkey": appsecret.strip()}).encode()
    encoded = _crypt(packed, decrypt=False)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(path)


class CredentialResolver:
    """Resolve LS credentials without exposing secret values."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()

    def _env_candidates(self) -> list[Path]:
        paths = [self.project_root / ".env"]
        paths.append(env_file(self.project_root))
        return list(dict.fromkeys(path.resolve() for path in paths))

    def load(self) -> tuple[str, str]:
        key = os.environ.get("LS_APP_KEY", "").strip()
        secret = os.environ.get("LS_APP_SECRET", "").strip()
        if key and secret:
            return key, secret

        checked: list[str] = []
        for path in self._env_candidates():
            if not path.is_file():
                checked.append(f"{path} (파일 없음)")
                continue
            try:
                return _read_env_file(path)
            except LSOpenApiError:
                checked.append(f"{path} (LS_APP_KEY/LS_APP_SECRET 없음)")

        path = credential_file(self.project_root)
        if path.is_file():
            try:
                document = json.loads(_crypt(path.read_bytes(), decrypt=True))
                key = str(document["appkey"]).strip()
                secret = str(document["appsecretkey"]).strip()
            except (KeyError, ValueError, UnicodeError, OSError) as error:
                raise LSOpenApiError("LS OPEN API 저장 키 형식이 잘못되었습니다.") from error
            if key and secret:
                return key, secret

        detail = "\n - ".join(checked) if checked else "확인 가능한 .env 없음"
        raise LSOpenApiError(
            "LS OPEN API 키를 찾지 못했습니다. 필요한 이름은 LS_APP_KEY, LS_APP_SECRET입니다.\n"
            f"확인 위치:\n - {detail}"
        )


def load_credentials(project_root: Path) -> tuple[str, str]:
    return CredentialResolver(project_root).load()


class LSOpenApiT8451Client:
    def __init__(self, appkey: str, appsecret: str, *, session: Any = None,
                 timeout: float = 20.0, delay: float = 0.6) -> None:
        if not appkey or not appsecret:
            raise ValueError("LS APP KEY와 SECRET KEY가 필요합니다.")
        self._key, self._secret = appkey, appsecret
        self.session = session if session is not None else requests.Session()
        self.timeout = timeout
        self.delay = max(0.0, delay)
        self._token = ""
        self._expires = 0.0

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "LSOpenApiT8451Client":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(self, url: str, *, data: dict | None = None, body: dict | None = None,
                 headers: dict | None = None) -> dict:
        for attempt in range(3):
            try:
                response = self.session.post(url, data=data, json=body, headers=headers,
                                             timeout=self.timeout)
            except requests.RequestException as error:
                if attempt == 2:
                    raise LSOpenApiError(f"LS API 연결 실패: {type(error).__name__}") from error
                time.sleep(1 + attempt)
                continue
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(1 + attempt)
                continue
            if response.status_code >= 400:
                detail = ""
                try:
                    document = response.json()
                    if isinstance(document, dict):
                        code = str(document.get("rsp_cd") or document.get("error_code") or "")[:30]
                        message = str(document.get("rsp_msg") or document.get("error_description") or "")[:150]
                        detail = f" LS코드={code} {message}" if code or message else ""
                except (ValueError, TypeError):
                    pass
                for sensitive in (self._key, self._secret, self._token):
                    if sensitive:
                        detail = detail.replace(sensitive, "[숨김]")
                raise LSOpenApiError(f"LS API HTTP {response.status_code} "
                                     f"({url.rsplit('/', 1)[-1]}){detail}")
            try:
                payload = response.json()
            except ValueError as error:
                raise LSOpenApiError("LS API 응답이 JSON이 아닙니다.") from error
            if not isinstance(payload, dict):
                raise LSOpenApiError("LS API 응답 형식이 잘못되었습니다.")
            if str(payload.get("rsp_cd", "00000")) not in ("00000", "0000", "0"):
                raise LSOpenApiError(f"LS API 오류 [{payload['rsp_cd']}]: {payload.get('rsp_msg', '')}")
            return payload
        raise LSOpenApiError("LS API 재시도 횟수를 초과했습니다.")

    def token(self) -> str:
        if self._token and time.monotonic() < self._expires - 120:
            return self._token
        response = self._request(TOKEN_URL, data={"grant_type": "client_credentials",
            "appkey": self._key, "appsecretkey": self._secret, "scope": "oob"},
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        self._token = str(response.get("access_token") or "")
        if not self._token:
            raise LSOpenApiError("LS API 접근 토큰 발급에 실패했습니다.")
        self._expires = time.monotonic() + int(response.get("expires_in") or 3600)
        return self._token

    def fetch(self, ticker: str, start: dt.date, end: dt.date, venue: str,
              *, page_size: int = 500) -> pd.DataFrame:
        selected = venue.upper()
        if selected not in T8451_VENUES:
            raise ValueError(f"지원하지 않는 거래시장: {venue}")
        if start > end:
            raise ValueError("시작일이 종료일보다 늦습니다.")
        block = {"shcode": str(ticker).zfill(6), "gubun": "2",
                 "qrycnt": max(1, min(page_size, 500)), "sdate": start.strftime("%Y%m%d"),
                 "edate": end.strftime("%Y%m%d"), "cts_date": "", "comp_yn": "N",
                 "sujung": "N", "exchgubun": T8451_VENUES[selected]}
        rows: list[dict] = []
        continuation = "N"
        continuation_key = ""
        visited = set()
        for _ in range(200):
            headers = {"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json",
                       "tr_cd": "t8451", "tr_cont": continuation,
                       "tr_cont_key": continuation_key}
            response = self._request(CHART_URL, body={"t8451InBlock": block}, headers=headers)
            page = response.get("t8451OutBlock1")
            if not isinstance(page, list):
                raise LSOpenApiError("t8451 일봉 목록이 응답에 없습니다.")
            rows.extend(item for item in page if isinstance(item, dict))
            out = response.get("t8451OutBlock") or {}
            cursor = str(out.get("cts_date") or "").strip()
            if not cursor or cursor in visited or not page:
                break
            visited.add(cursor)
            block["cts_date"] = cursor
            continuation = "Y"
            continuation_key = str(response.get("tr_cont_key") or "")
            time.sleep(self.delay)
        else:
            raise LSOpenApiError("t8451 연속 조회 페이지 제한을 초과했습니다.")
        result = normalize_t8451_rows(rows, ticker=ticker, venue=selected)
        if not result.empty:
            result["source"] = f"LS_OPENAPI:t8451:{selected}"
        return result

# V34_LS_CREDENTIAL_ALIAS_OVERRIDE
from .ls_credentials import load_ls_credentials as _load_ls_credentials_v34

def load_credentials(project_root):
    return _load_ls_credentials_v34(project_root)
