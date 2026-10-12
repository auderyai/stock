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


if __name__ == "__main__":
    unittest.main()
