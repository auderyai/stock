from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

from krx_research.collectors.ls_credentials import load_ls_credentials
from krx_research.collectors.xing.bridge import XingBridgeClient
from krx_research.infrastructure.xing_db.rate_limited_bridge import RateLimitedRawTrBridge


Progress = Callable[[str], None]


class DataProviderUnavailableError(RuntimeError):
    pass


class AdaptiveRawTrBridge:
    """LS OpenAPI primary for t1702/t8451; lazy Xing fallback for every failure."""

    _API = {
        "t1702": ("/stock/frgr-itt", "t1702InBlock", "t1702OutBlock1"),
        "t8451": ("/stock/chart", "t8451InBlock", "t8451OutBlock1"),
    }
    _BASE, _MIN_INTERVAL = "https://openapi.ls-sec.co.kr:8080", 1.05

    def __init__(self, project_root: Path, *, progress: Progress | None = None,
                 session=None, credential_loader=load_ls_credentials,
                 fallback_factory=None, sleep_fn=time.sleep, clock_fn=time.monotonic) -> None:
        self._root, self._progress = Path(project_root).resolve(), progress
        if self._root != Path(r"C:\stock").resolve(): raise ValueError("AdaptiveRawTrBridge는 C:\\stock 전용입니다.")
        self._session, self._credential_loader = session or requests.Session(), credential_loader
        self._fallback_factory = fallback_factory or self._default_fallback
        self._sleep, self._clock = sleep_fn, clock_fn
        self._token, self._enabled, self._fallback = "", False, None
        self._last_call: dict[str, float] = {}

    def connect(self) -> None:
        try:
            appkey, secret = self._credential_loader(self._root)
            response = self._session.post(f"{self._BASE}/oauth2/token", data={
                "grant_type": "client_credentials", "appkey": appkey,
                "appsecretkey": secret, "scope": "oob",
            }, timeout=15)
            response.raise_for_status(); self._token = str(response.json().get("access_token") or "").strip()
            if not self._token: raise RuntimeError("access_token 없음")
            self._enabled = True; self._emit("[LS OPENAPI] t1702/t8451 primary 연결 완료 (1 TR/sec)")
        except Exception as exc:
            detail = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            self._enabled = False; self._emit(f"[LS OPENAPI] 연결 불가 → Xing fallback: {type(exc).__name__}: {detail}")
            try: self._xing()
            except Exception as fallback_error:
                raise DataProviderUnavailableError(
                    "사용 가능한 LS 데이터 공급자가 없습니다. C:\\stock에 LS OpenAPI APP KEY/SECRET을 "
                    "등록하거나 tools\\setup\\SETUP_XING32_ENV.cmd로 Xing 32bit 환경을 준비하십시오. "
                    f"OpenAPI={type(exc).__name__}: {detail}, Xing={fallback_error}"
                ) from fallback_error

    def close(self) -> None:
        self._session.close()
        if self._fallback is not None: self._fallback.close()

    def raw_tr(self, tr: str, values: dict[str, str]) -> dict[str, Any]:
        code = str(tr).strip().lower()
        if self._enabled and code in self._API:
            try: return self._openapi(code, values)
            except Exception as exc: self._emit(f"[LS OPENAPI FALLBACK] {code}: {type(exc).__name__}: {exc}")
        return self._xing().raw_tr(tr, values)

    def _openapi(self, tr: str, values: dict[str, str]) -> dict[str, Any]:
        path, in_block, out_block = self._API[tr]; values = {k: str(v) for k, v in values.items()}
        if tr == "t8451": values["qrycnt"] = min(500, max(1, int(values.get("qrycnt", 500))))
        rows, visited, continuation, key, payload = [], set(), "N", "", {}
        for _ in range(200):
            response = self._request(path, tr, in_block, values, continuation, key)
            payload = response.json(); code = str(payload.get("rsp_cd") or "")
            if code and code not in ("00000", "0000", "0"): raise RuntimeError(f"{tr} {code}: {payload.get('rsp_msg') or 'OPEN API 오류'}")
            page = payload.get(out_block, [])
            if not isinstance(page, list): raise TypeError(f"{tr}: {out_block}가 list가 아닙니다.")
            rows.extend(row for row in page if isinstance(row, dict))
            if tr != "t8451": break
            cursor = str((payload.get("t8451OutBlock") or {}).get("cts_date") or "").strip()
            if not cursor or cursor in visited or not page: break
            visited.add(cursor); values["cts_date"] = cursor; continuation = "Y"
            key = str(getattr(response, "headers", {}).get("tr_cont_key") or "")
        else: raise RuntimeError("t8451 연속조회 200페이지 제한을 초과했습니다.")
        return {"rows": rows, "provider": "LS_OPENAPI", "raw": payload}

    def _request(self, path: str, tr: str, block: str, values: dict[str, Any], continuation: str, key: str):
        response = None
        for attempt in range(3):
            self._pace(tr); response = self._post(path, tr, block, values, continuation, key)
            if response.status_code < 500 and response.status_code != 429: break
            if attempt < 2:
                self._emit(f"[LS OPENAPI RETRY] {tr}: HTTP {response.status_code}, {attempt + 1}/2")
                self._sleep(1.25 * (attempt + 1)); self._last_call.pop(tr, None)
        assert response is not None
        if response.status_code >= 400:
            try:
                error = response.json()
                raise RuntimeError(
                    f"{tr} HTTP {response.status_code} {error.get('rsp_cd') or ''}: "
                    f"{error.get('rsp_msg') or 'OPEN API 오류'}"
                )
            except (ValueError, TypeError):
                response.raise_for_status()
        return response

    def _post(self, path: str, tr: str, block: str, values: dict[str, Any], continuation: str, key: str):
        return self._session.post(f"{self._BASE}{path}", headers={
            "Content-Type": "application/json; charset=UTF-8", "authorization": f"Bearer {self._token}",
            "tr_cd": tr, "tr_cont": continuation, "tr_cont_key": key, "mac_address": "",
        }, data=json.dumps({block: values}, ensure_ascii=False).encode(), timeout=20)

    def _default_fallback(self):
        return RateLimitedRawTrBridge(XingBridgeClient(self._root), progress=self._progress)

    def _xing(self):
        if self._fallback is None:
            self._fallback = self._fallback_factory(); self._fallback.connect()
            self._emit("[XING FALLBACK] 필요한 요청에 한해 DLL 연결")
        return self._fallback

    def _pace(self, tr: str) -> None:
        now, previous = self._clock(), self._last_call.get(tr)
        if previous is not None and (wait := self._MIN_INTERVAL - (now - previous)) > 0: self._sleep(wait)
        self._last_call[tr] = self._clock()

    def _emit(self, message: str) -> None:
        (self._progress or (lambda value: print(value, flush=True)))(message)
