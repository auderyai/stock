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


if __name__ == "__main__":
    unittest.main()
