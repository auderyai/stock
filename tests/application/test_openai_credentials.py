from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from krx_research.application.openai_credentials import (
    OpenAICredentialRegistrationService, OpenAICredentialResolver,
)
from krx_research.infrastructure.windows_dpapi_store import WindowsDpapiJsonStore


class _Response:
    ok = True
    status_code = 200


class _Session:
    def get(self, url, *, headers, timeout):
        self.url, self.headers, self.timeout = url, headers, timeout
        return _Response()


class _RejectedSession:
    def get(self, *_args, **_kwargs):
        return type("RejectedResponse", (), {"ok": False, "status_code": 401})()


class OpenAICredentialTests(unittest.TestCase):
    def test_dpapi_round_trip(self):
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            store = WindowsDpapiJsonStore(Path(directory) / "secret.dpapi")
            store.save({"api_key": "test-secret", "model": "test-model"})
            self.assertNotIn(b"test-secret", store.path.read_bytes())
            self.assertEqual(store.load()["api_key"], "test-secret")

    def test_registration_validates_and_loads_encrypted_value(self):
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            root, session = Path(directory), _Session()
            path = OpenAICredentialRegistrationService(root, session=session).register(
                "test-secret", "gpt-5.4"
            )
            credentials = OpenAICredentialResolver(root).load()
            self.assertTrue(path.is_file())
            self.assertEqual(credentials.api_key, "test-secret")
            self.assertEqual(credentials.model, "gpt-5.4")
            self.assertNotIn("test-secret", str(session.url))

    def test_invalid_key_is_not_saved(self):
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            service = OpenAICredentialRegistrationService(
                root, session=_RejectedSession()
            )
            with self.assertRaisesRegex(RuntimeError, "인증"):
                service.register("invalid-secret", "gpt-5.4")
            self.assertFalse(service.resolver.store.path.exists())


if __name__ == "__main__":
    unittest.main()
