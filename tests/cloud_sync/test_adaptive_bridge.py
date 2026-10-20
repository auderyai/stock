from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from krx_research.infrastructure.xing_db.adaptive_raw_bridge import (
    AdaptiveRawTrBridge,
    DataProviderUnavailableError,
)


class _Response:
    def raise_for_status(self) -> None:
        raise RuntimeError("offline")


class _Session:
    def post(self, *_args, **_kwargs):
        return _Response()

    def close(self) -> None:
        pass


class _JsonResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _ExpiredTokenSession:
    def __init__(self) -> None:
        self.token_requests = 0
        self.data_requests = 0

    def post(self, url, **_kwargs):
        if url.endswith("/oauth2/token"):
            self.token_requests += 1
            return _JsonResponse(200, {"access_token": f"token-{self.token_requests}"})
        self.data_requests += 1
        if self.data_requests == 1:
            return _JsonResponse(500, {"rsp_cd": "IGW00121", "rsp_msg": "유효하지 않은 token 입니다."})
        return _JsonResponse(200, {"rsp_cd": "00000", "t1702OutBlock1": [{"date": "20261012"}]})

    def close(self) -> None:
        pass


class _UniverseSession:
    def __init__(self, rows=None) -> None:
        self.request = None
        self.rows = rows if rows is not None else [{"shcode": "005930", "hname": "삼성전자"}]

    def post(self, url, **kwargs):
        if url.endswith("/oauth2/token"):
            return _JsonResponse(200, {"access_token": "token"})
        self.request = (url, kwargs)
        return _JsonResponse(200, {
            "rsp_cd": "00000",
            "t8436OutBlock": self.rows,
        })

    def close(self) -> None:
        pass


class _IndexMembershipSession:
    def __init__(self) -> None:
        self.requests = []

    def post(self, url, **kwargs):
        if url.endswith("/oauth2/token"):
            return _JsonResponse(200, {"access_token": "token"})
        self.requests.append((url, kwargs))
        request = kwargs["data"].decode("utf-8")
        if '"shcode": ""' in request:
            return _JsonResponse(200, {
                "rsp_cd": "00000",
                "t1516OutBlock": {"shcode": "000002"},
                "t1516OutBlock1": [{"shcode": "000001"}, {"shcode": "000002"}],
            })
        return _JsonResponse(200, {
            "rsp_cd": "00000",
            "t1516OutBlock": {"shcode": ""},
            "t1516OutBlock1": [{"shcode": "000003"}],
        })

    def close(self) -> None:
        pass


class AdaptiveBridgeTests(unittest.TestCase):
    def test_cloud_mode_does_not_attempt_xing_fallback(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as name:
            root = Path(name)
            (root / "src" / "krx_research").mkdir(parents=True)
            fallback_calls: list[bool] = []
            bridge = AdaptiveRawTrBridge(
                root,
                session=_Session(),
                credential_loader=lambda _root: ("key", "secret"),
                fallback_factory=lambda: fallback_calls.append(True),
                fallback_allowed=False,
                progress=lambda _message: None,
            )
            with self.assertRaises(DataProviderUnavailableError):
                bridge.connect()
            self.assertEqual([], fallback_calls)

    def test_refreshes_expired_openapi_token_once_and_retries_request(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as name:
            root = Path(name)
            (root / "src" / "krx_research").mkdir(parents=True)
            session = _ExpiredTokenSession()
            bridge = AdaptiveRawTrBridge(
                root,
                session=session,
                credential_loader=lambda _root: ("key", "secret"),
                fallback_allowed=False,
                sleep_fn=lambda _seconds: None,
                clock_fn=lambda: 1.0,
                progress=lambda _message: None,
            )

            bridge.connect()
            result = bridge.raw_tr("t1702", {"shcode": "001450"})

            self.assertEqual([{"date": "20261012"}], result["rows"])
            self.assertEqual(2, session.token_requests)
            self.assertEqual(2, session.data_requests)

    def test_cloud_stock_universe_uses_openapi_without_xing(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as name:
            root = Path(name); (root / "src" / "krx_research").mkdir(parents=True)
            session = _UniverseSession()
            bridge = AdaptiveRawTrBridge(
                root, session=session, credential_loader=lambda _root: ("key", "secret"),
                fallback_allowed=False, sleep_fn=lambda _seconds: None,
                clock_fn=lambda: 1.0, progress=lambda _message: None,
            )
            bridge.connect(); result = bridge.raw_tr("t8436", {"gubun": "0"})
            self.assertEqual("005930", result["rows"][0]["shcode"])
            self.assertTrue(session.request[0].endswith("/stock/etc"))

    def test_empty_cloud_stock_universe_is_provider_failure(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as name:
            root = Path(name); (root / "src" / "krx_research").mkdir(parents=True)
            bridge = AdaptiveRawTrBridge(
                root, session=_UniverseSession([]), credential_loader=lambda _root: ("key", "secret"),
                fallback_allowed=False, sleep_fn=lambda _seconds: None,
                clock_fn=lambda: 1.0, progress=lambda _message: None,
            )

            bridge.connect()
            with self.assertRaises(DataProviderUnavailableError):
                bridge.raw_tr("t8436", {"gubun": "0"})

    def test_index_membership_uses_openapi_and_body_cursor(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as name:
            root = Path(name); (root / "src" / "krx_research").mkdir(parents=True)
            session = _IndexMembershipSession()
            bridge = AdaptiveRawTrBridge(
                root, session=session, credential_loader=lambda _root: ("key", "secret"),
                fallback_allowed=False, sleep_fn=lambda _seconds: None,
                clock_fn=lambda: 1.0, progress=lambda _message: None,
            )

            bridge.connect()
            result = bridge.raw_tr("t1516", {"upcode": "101", "gubun": "1", "shcode": ""})

            self.assertEqual(["000001", "000002", "000003"], [row["shcode"] for row in result["rows"]])
            self.assertEqual(2, len(session.requests))
            self.assertTrue(all(item[0].endswith("/indtp/market-data") for item in session.requests))
            self.assertIn('"shcode": "000002"', session.requests[1][1]["data"].decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
