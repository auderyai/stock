from __future__ import annotations

from datetime import datetime
from io import BytesIO
import time
from typing import Any
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

import requests

from .models import DartCompany, FinancialPeriod


class OpenDartError(RuntimeError):
    pass


class OpenDartTransientError(OpenDartError):
    pass


class OpenDartClient:
    BASE = "https://opendart.fss.or.kr/api"
    TRANSIENT = {"020", "800", "900"}

    def __init__(self, api_key: str, session: requests.Session | None = None) -> None:
        key = api_key.strip()
        if len(key) != 40:
            raise OpenDartError("OpenDART API 키는 40자리여야 합니다.")
        self._key = key
        self._session = session or requests.Session()

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "OpenDartClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def listed_companies(self) -> tuple[DartCompany, ...]:
        response = self._get("corpCode.xml", {})
        try:
            with ZipFile(BytesIO(response.content)) as archive:
                root = ET.fromstring(archive.read(archive.namelist()[0]))
        except (BadZipFile, ET.ParseError, IndexError, KeyError) as exc:
            self._raise_xml_error(response.content)
            raise OpenDartError("OpenDART 고유번호 파일을 해석할 수 없습니다.") from exc
        companies = []
        for item in root.findall("list"):
            ticker = (item.findtext("stock_code") or "").strip()
            if len(ticker) != 6 or not ticker.isdigit():
                continue
            modified = (item.findtext("modify_date") or "").strip()
            companies.append(DartCompany(
                corp_code=(item.findtext("corp_code") or "").strip(),
                ticker=ticker,
                name=(item.findtext("corp_name") or "").strip(),
                english_name=(item.findtext("corp_eng_name") or "").strip(),
                modified_at=datetime.strptime(modified, "%Y%m%d").date() if modified else None,
            ))
        if not companies:
            raise OpenDartError("OpenDART 상장회사 목록이 0건입니다.")
        return tuple(sorted(companies, key=lambda company: company.corp_code))

    def statements(
        self, corp_code: str, year: int, period: FinancialPeriod, scope: str
    ) -> list[dict[str, Any]]:
        parameters = {
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": period.report_code,
            "fs_div": scope,
        }
        for attempt in range(2):
            response = self._get("fnlttSinglAcntAll.json", parameters)
            try:
                payload = response.json()
            except ValueError as exc:
                raise OpenDartError("OpenDART 재무제표 응답이 JSON이 아닙니다.") from exc
            status = str(payload.get("status") or "")
            if status == "013":
                return []
            if status == "000":
                rows = payload.get("list") or []
                if not isinstance(rows, list):
                    raise OpenDartError("OpenDART 재무제표 목록 형식이 잘못되었습니다.")
                return [dict(row) for row in rows]
            message = str(payload.get("message") or "알 수 없는 오류")
            if status not in self.TRANSIENT:
                raise OpenDartError(f"OpenDART 오류 {status}: {message}")
            if attempt:
                raise OpenDartTransientError(f"OpenDART 오류 {status}: {message}")
            time.sleep(1)
        raise AssertionError("unreachable")

    def _get(self, endpoint: str, params: dict[str, str]) -> requests.Response:
        parameters = {"crtfc_key": self._key, **params}
        for attempt in range(2):
            try:
                response = self._session.get(
                    f"{self.BASE}/{endpoint}", params=parameters, timeout=60
                )
                response.raise_for_status()
                return response
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
                if attempt:
                    raise OpenDartTransientError("OpenDART 네트워크 요청이 2회 실패했습니다.") from exc
                time.sleep(1)
        raise AssertionError("unreachable")

    @classmethod
    def _raise_xml_error(cls, content: bytes) -> None:
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            return
        status = str(root.findtext("status") or "")
        if not status or status == "000":
            return
        message = str(root.findtext("message") or "알 수 없는 오류")
        error = OpenDartTransientError if status in cls.TRANSIENT else OpenDartError
        raise error(f"OpenDART 오류 {status}: {message}")
