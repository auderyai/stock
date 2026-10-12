from __future__ import annotations

import base64
from pathlib import Path
import tarfile
import tempfile
import unittest

from krx_research.cloud_sync.archive import ArchiveCipher, CloudArchiveError, _extracted_archive


class ArchiveCipherTests(unittest.TestCase):
    def test_authenticated_round_trip_and_wrong_key_rejection(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as name:
            root = Path(name)
            source = root / "source.bin"
            encrypted = root / "source.enc"
            restored = root / "restored.bin"
            source.write_bytes(b"stock-db-state\x00\xff")
            key = ArchiveCipher.generate_key()

            ArchiveCipher.encrypt(source, encrypted, key)
            ArchiveCipher.decrypt(encrypted, restored, key)
            self.assertEqual(source.read_bytes(), restored.read_bytes())

            wrong = base64.urlsafe_b64encode(b"x" * 32).decode("ascii")
            with self.assertRaises(CloudArchiveError):
                ArchiveCipher.decrypt(encrypted, restored, wrong)

    def test_path_traversal_archive_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as name:
            root = Path(name)
            payload = root / "payload.txt"
            payload.write_text("unsafe", encoding="utf-8")
            archive = root / "unsafe.tar.gz"
            with tarfile.open(archive, "w:gz") as stream:
                stream.add(payload, arcname="../outside.txt")
            with self.assertRaises(CloudArchiveError):
                with _extracted_archive(archive):
                    pass


if __name__ == "__main__":
    unittest.main()
