from __future__ import annotations

import base64
from contextlib import contextmanager
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from krx_research.cloud_sync.archive import (
    ArchiveCipher,
    CloudArchiveError,
    DatabaseArchiveService,
    DeltaArchiveApplier,
    _extracted_archive,
)


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

    def test_postgres_18_transaction_timeout_is_removed_for_restore(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as name:
            schema = Path(name) / "schema.sql"
            schema.write_text(
                "SET statement_timeout = 0;\n"
                "SET transaction_timeout = 0;\n"
                "CREATE TABLE sample(id integer);\n",
                encoding="utf-8",
            )

            compatible = DatabaseArchiveService._compatible_restore_schema(schema)

            self.assertNotEqual(schema, compatible)
            text = compatible.read_text(encoding="utf-8")
            self.assertNotIn("transaction_timeout", text)
            self.assertIn("statement_timeout", text)
            self.assertIn("CREATE TABLE", text)

    def test_restore_schema_uses_compatible_copy(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as name:
            root = Path(name)
            psql = root / "psql"
            psql.touch()
            schema = root / "schema.sql"
            schema.write_text(
                "SET transaction_timeout = 0;\nCREATE TABLE sample(id integer);\n",
                encoding="utf-8",
            )
            conn = MagicMock()
            conn.info.get_parameters.return_value = {
                "host": "127.0.0.1",
                "port": "5432",
                "user": "worker",
                "dbname": "stock",
            }
            service = DatabaseArchiveService(conn, tables=())

            with patch("krx_research.cloud_sync.archive.subprocess.run") as run:
                run.return_value.returncode = 0
                service._restore_schema(psql, schema)

            command = run.call_args.args[0]
            restored_schema = Path(command[command.index("--file") + 1])
            self.assertNotEqual(schema, restored_schema)
            self.assertNotIn(
                "transaction_timeout", restored_schema.read_text(encoding="utf-8")
            )

    def test_delta_history_lookup_runs_inside_apply_transaction(self) -> None:
        class Connection:
            depth = 0

            @contextmanager
            def transaction(self):
                self.depth += 1
                try:
                    yield
                finally:
                    self.depth -= 1

            def execute(self, statement, parameters=None):
                if str(statement).startswith("SELECT 1"):
                    self.assert_in_transaction()
                    return MagicMock(fetchone=lambda: None)
                return MagicMock()

            def assert_in_transaction(self):
                if not self.depth:
                    raise AssertionError("history lookup escaped the apply transaction")

        connection = Connection()
        manifest = {
            "batch_id": "2026-10-13-test",
            "reference_date": "2026-10-13",
            "tables": [],
        }
        applier = DeltaArchiveApplier(connection, tables=())
        with (
            patch("krx_research.cloud_sync.archive._extracted_archive") as extracted,
            patch(
                "krx_research.cloud_sync.archive._load_and_verify_manifest",
                return_value=manifest,
            ),
        ):
            extracted.return_value.__enter__.return_value = Path.cwd()
            result = applier.apply(Path("unused.tar.gz"))

        self.assertEqual("applied", result["apply_status"])
        self.assertEqual(0, connection.depth)


if __name__ == "__main__":
    unittest.main()
