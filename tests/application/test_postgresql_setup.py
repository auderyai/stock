from pathlib import Path
import os
import tempfile
import traceback
import unittest
import hashlib
import io
import json
import importlib.util
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from krx_research.application.postgresql_setup import PostgreSQLSetupService
from krx_research.database.provisioning import PostgreSQLProvisioningRepository
from krx_research.database.backup import PostgreSQLBackupArchive
from krx_research.environment import EnvironmentResolver
from krx_research.infrastructure.env_file_repository import EnvFileRepository


class PostgreSQLSetupTests(unittest.TestCase):
    def repository(self):
        repository = MagicMock()
        repository.DATABASE = "krx_research"
        repository.READER = "krx_reader"
        repository.WRITER = "krx_writer"
        return repository

    def test_connection_verification_uses_read_only_administrative_repository(self):
        from krx_research.database.settings import PostgreSQLSettings
        target = PostgreSQLSettings("127.0.0.1", 5433, "krx_research", "krx_reader", "synthetic")
        identity = {"db": target.database, "user": target.user, "version": "PostgreSQL 18.6", "read_only": "on"}
        with patch("krx_research.application.postgresql_setup.resolve_database_target_from_env_file", return_value=target), \
             patch("krx_research.application.postgresql_setup.AdministrativeRepository") as repository:
            repository.return_value.__enter__.return_value.server_identity.return_value = identity
            service = PostgreSQLSetupService(Path.cwd())
            self.assertEqual(service.verify_connection(), identity)
            self.assertTrue(repository.call_args.kwargs["read_only"])
            self.assertEqual(repository.call_args.kwargs["application_name"], "setup_check")
            for invalid in ({**identity, "read_only": "off"}, {**identity, "user": "postgres"}, {**identity, "db": "other"}):
                repository.return_value.__enter__.return_value.server_identity.return_value = invalid
                with self.assertRaises(ValueError):
                    service.verify_connection()
            repository.return_value.__enter__.side_effect = RuntimeError("driver-secret-demo")
            try:
                service.verify_connection()
            except RuntimeError:
                self.assertNotIn("driver-secret-demo", traceback.format_exc())
            else:
                self.fail("Driver failure was accepted")

    def test_administrative_identity_preserves_version_and_read_only_status(self):
        from krx_research.database.administrative_repository import AdministrativeRepository
        repository = AdministrativeRepository.__new__(AdministrativeRepository)
        repository._repository = MagicMock()
        expected = {"db": "krx_research", "user": "krx_reader", "version": "18.6", "read_only": "on"}
        repository._repository.conn.execute.return_value.fetchone.return_value = expected
        self.assertEqual(repository.server_identity(), expected)
        statement = repository._repository.conn.execute.call_args.args[0]
        self.assertIn("version() AS version", statement)
        self.assertIn("current_setting('transaction_read_only')", statement)

    def test_setup_cli_preserves_all_modes_without_direct_database_access(self):
        path = Path(__file__).resolve().parents[2] / "scripts" / "setup_postgresql.py"
        spec = importlib.util.spec_from_file_location("setup_postgresql_cli", path)
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        archive_args = ["--backup", "archive.dump", "--expected-size", "7", "--sha256", "00", "--latest-trade-date", "2026-10-21"]
        with patch.object(cli, "PostgreSQLSetupService") as service_type, \
             patch("krx_research.qt.postgresql_setup.configure", return_value=0) as configure, \
             patch("sys.stdout", new_callable=io.StringIO):
            service = service_type.return_value
            service.verify_restored.return_value = {"table_counts": {"t": 1}, "latest_trade_date": "2026-10-21"}
            service.inspect18.return_value = (None, None, Path.cwd(), {})
            cases = [([], "verify_connection"), (["--verify-accounts"], "verify_saved"),
                     (["--restore-status"], "restore_status"),
                     (["--verify-restored", "report.json", "--complete-18", "--latest-trade-date", "2026-10-21"], "verify_restored"),
                     (["--inspect-backup", *archive_args], "inspect18")]
            for arguments, method in cases:
                with self.subTest(mode=method), patch("sys.argv", [str(path), *arguments]):
                    service.reset_mock()
                    self.assertEqual(cli.main(), 0)
                    getattr(service, method).assert_called_once()
                    service.provision.assert_not_called()
            for arguments in (["--configure"], ["--migrate-to-18", *archive_args]):
                with patch("sys.argv", [str(path), *arguments]):
                    self.assertEqual(cli.main(), 0)
            self.assertEqual(configure.call_count, 2)
            self.assertIsNone(configure.call_args_list[0].kwargs["migration"])
            self.assertEqual(configure.call_args_list[1].kwargs["migration"]["expected_size"], 7)

    def test_verified_accounts_saved_with_unrelated_entries_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = root / ".env"
            env.write_text("# keep\nDART_API_KEY=unrelated\nKRX_DB_READ_PASSWORD=old\nKRX_DB_READ_PASSWORD=duplicate\n")
            repository = self.repository()
            service = PostgreSQLSetupService(root, repository)
            service.configure("admin-demo", 'read #\\"demo', "write-demo")
            values = EnvironmentResolver._read(env)
            self.assertEqual(values["KRX_DB_READ_PASSWORD"], 'read #\\"demo')
            self.assertEqual(values["KRX_DB_WRITE_USER"], "krx_writer")
            self.assertEqual(values["DART_API_KEY"], "unrelated")
            repository.verify.assert_called_once()
            self.assertFalse((root / ".env.tmp").exists())

    def test_invalid_input_does_not_touch_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = self.repository()
            service = PostgreSQLSetupService(directory, repository)
            for secrets in (("", "reader", "writer"), ("same", "same", "writer"), ("admin", "bad\nvalue", "writer")):
                with self.subTest(secrets_present=bool(secrets[0])):
                    with self.assertRaises(ValueError):
                        service.configure(*secrets)
            repository.provision.assert_not_called()

    def test_failure_never_saves_or_displays_driver_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = self.repository()
            repository.verify.side_effect = RuntimeError("driver-secret-demo")
            service = PostgreSQLSetupService(directory, repository)
            try:
                service.configure("admin-demo", "reader-demo", "writer-demo")
            except RuntimeError:
                self.assertNotIn("driver-secret-demo", traceback.format_exc())
            else:
                self.fail("Verification failure was accepted")
            self.assertFalse((Path(directory) / ".env").exists())

    def test_env_rejects_line_injection(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                EnvFileRepository(Path(directory) / ".env").save({"KEY": "value\nOTHER=value"})

    def test_unmanaged_database_is_rejected_before_role_changes(self):
        repository = PostgreSQLProvisioningRepository()
        admin = MagicMock()
        admin.info.server_version = 160015
        admin.execute.return_value.fetchone.side_effect = [(True,), ("someone_else", None)]
        with patch.object(repository, "connect") as connect:
            connect.return_value.__enter__.return_value = admin
            with self.assertRaises(ValueError):
                repository.provision("admin-demo", "reader-demo", "writer-demo")
        self.assertEqual(admin.execute.call_count, 2)

    def test_privileges_are_database_local_and_writer_has_no_ddl(self):
        repository = PostgreSQLProvisioningRepository()
        connection = MagicMock()
        repository._permissions(connection)
        statements = "\n".join(call.args[0].as_string(None) for call in connection.execute.call_args_list)
        self.assertIn("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES", statements)
        self.assertIn("REVOKE ALL ON DATABASE", statements)
        self.assertIn("GRANT USAGE ON SCHEMAS", statements)
        self.assertNotIn("GRANT CREATE", statements)
        self.assertNotIn("pg_read_all_data", statements)
        self.assertNotIn("CREATE TABLE", statements)

    def test_existing_data_is_rejected_before_password_changes(self):
        repository = PostgreSQLProvisioningRepository()
        admin, target = MagicMock(), MagicMock()
        admin.info.server_version = 160015
        admin.execute.return_value.fetchone.side_effect = [(True,), (repository.OWNER, repository.MARKER)]
        target.execute.return_value.fetchone.return_value = (True,)
        with patch.object(repository, "connect") as connect:
            connect.side_effect = [admin, target]
            admin.__enter__.return_value = admin
            target.__enter__.return_value = target
            with self.assertRaises(ValueError):
                repository.provision("admin-demo", "reader-demo", "writer-demo")
        self.assertEqual(admin.execute.call_count, 2)

    def test_local_dialog_masks_every_password(self):
        with patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}):
            from PySide6.QtWidgets import QApplication, QLineEdit
            from krx_research.qt.postgresql_setup import PostgreSQLSetupDialog
            app = QApplication.instance() or QApplication([])
            dialog = PostgreSQLSetupDialog(Path.cwd())
            self.assertEqual(len(dialog.fields), 5)
            self.assertTrue(all(field.echoMode() == QLineEdit.Password for field in dialog.fields))
            dialog.close()
            app.processEvents()

    def test_migration_dialog_only_requests_masked_admin_password(self):
        with patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}):
            from PySide6.QtWidgets import QApplication, QLineEdit
            from krx_research.qt.postgresql_setup import PostgreSQLSetupDialog
            app = QApplication.instance() or QApplication([])
            dialog = PostgreSQLSetupDialog(Path.cwd(), migration={"backup": "archive.dump"})
            self.assertEqual(len(dialog.fields), 1)
            self.assertEqual(dialog.fields[0].echoMode(), QLineEdit.Password)
            dialog.close()
            app.processEvents()

    def test_archive_hash_mismatch_stops_before_pg_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "archive.dump"
            archive.write_bytes(b"archive")
            with patch("krx_research.database.backup.subprocess.run") as run:
                with self.assertRaises(ValueError):
                    PostgreSQLBackupArchive(Path("pg_restore")).inspect(
                        archive, expected_size=7, expected_sha256="wrong", list_path=archive.with_suffix(".list"))
                run.assert_not_called()

    def test_archive_inspection_uses_18_and_retains_public_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "archive.dump"
            archive.write_bytes(b"archive")
            listing = "1; 2615 1 SCHEMA - public postgres\n2; 0 2 TABLE DATA public prices postgres\n"
            with patch("krx_research.database.backup.subprocess.run", side_effect=[
                SimpleNamespace(stdout="pg_restore (PostgreSQL) 18.6"),
                SimpleNamespace(stdout=listing, returncode=0),
            ]):
                result = PostgreSQLBackupArchive(Path("pg_restore")).inspect(
                    archive, expected_size=7, expected_sha256=hashlib.sha256(b"archive").hexdigest(),
                    list_path=archive.with_suffix(".list"))
            self.assertEqual(result["table_data_entries"], 1)
            self.assertNotIn("SCHEMA - public", archive.with_suffix(".list").read_text())

    def test_archive_aggregates_copy_counts_dates_financial_and_checkpoints(self):
        process = MagicMock()
        process.stdout = io.BytesIO(
            b"COPY public.prices (trade_date, value) FROM stdin;\n2026-10-21\t10\n\\.\n"
            b"COPY financial.statement_facts (fiscal_year, fiscal_period) FROM stdin;\n2026\tHALF\n\\.\n"
            b"COPY public.update_state (status, end_date) FROM stdin;\ncompleted\t2026-10-21\n\\.\n")
        process.wait.return_value = 0
        process.poll.return_value = 0
        with patch("krx_research.database.backup.subprocess.Popen", return_value=process) as popen:
            result = PostgreSQLBackupArchive(Path("pg_restore")).source_summary(Path("archive"), expected_tables=3)
        self.assertEqual(popen.call_args.args[0][-3:-1], ["--file", "-"])
        self.assertEqual(result["tables"]["public.prices"]["rows"], 1)
        self.assertEqual(result["tables"]["public.prices"]["dates"], {"trade_date": "2026-10-21"})
        self.assertEqual(result["latest_financial"], (2026, 6, "HALF"))
        self.assertEqual(result["tables"]["public.update_state"]["statuses"], {"completed": 1})

    def test_restore_refuses_postgresql16_endpoint(self):
        from krx_research.database.settings import PostgreSQLSettings
        settings = PostgreSQLSettings(host="127.0.0.1", port=5432, database="krx_research",
                                      user="postgres", password="synthetic")
        with patch("krx_research.database.backup.subprocess.run") as run:
            with self.assertRaises(ValueError):
                PostgreSQLBackupArchive(Path("pg_restore")).restore(
                    Path("archive"), settings, list_path=Path("archive.list"))
            run.assert_not_called()

    def test_failed_restore_does_not_switch_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            PostgreSQLSetupService(root, self.repository()).configure("admin-demo", "reader-demo", "writer-demo")
            original = (root / ".env").read_bytes()
            table = {"dates": {"trade_date": "2026-10-21"}}
            with patch("krx_research.application.postgresql_setup.PostgreSQLBackupArchive") as archive, \
                 patch("krx_research.application.postgresql_setup.PostgreSQLProvisioningRepository") as repository:
                archive.return_value.inspect.return_value = {"table_data_entries": 1}
                archive.return_value.source_summary.return_value = {"tables": {"public.prices": table}}
                archive.return_value.restore.side_effect = RuntimeError("복원 트랜잭션 실패")
                with self.assertRaisesRegex(RuntimeError, "restore-transaction"):
                    PostgreSQLSetupService(root).migrate18("admin-demo", {
                        "backup": root / "archive", "expected_size": 1, "sha256": "00",
                        "latest_trade_date": "2026-10-21"})
                repository.return_value.validate_restored.assert_not_called()
            self.assertEqual((root / ".env").read_bytes(), original)

    def test_migration_switches_only_after_restored_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            PostgreSQLSetupService(root, self.repository()).configure("admin-demo", "reader-demo", "writer-demo")
            with patch("krx_research.application.postgresql_setup.PostgreSQLBackupArchive") as archive, \
                 patch("krx_research.application.postgresql_setup.PostgreSQLProvisioningRepository") as repository:
                archive.return_value.executable = Path("pg_restore.exe")
                archive.return_value.inspect.return_value = {"table_data_entries": 1}
                archive.return_value.source_summary.return_value = {
                    "tables": {"public.prices": {"dates": {"trade_date": "2026-10-21"}}}}
                def validate(*args, **kwargs):
                    self.assertEqual(EnvironmentResolver._read(root / ".env")["KRX_DB_PORT"], "5432")
                    return {"table_counts": {"public.prices": 1}}
                repository.return_value.validate_restored.side_effect = validate
                result = PostgreSQLSetupService(root).migrate18("admin-demo", {
                    "backup": root / "archive", "expected_size": 1, "sha256": "00",
                    "latest_trade_date": "2026-10-21"})
                repository.assert_any_call(port=5433, major_version=18)
            self.assertEqual(EnvironmentResolver._read(root / ".env")["KRX_DB_PORT"], "5433")
            self.assertTrue(Path(result["report"]).is_file())

    def test_archive_diagnostic_redacts_quoted_content(self):
        headline = PostgreSQLBackupArchive._error_headline(
            b'pg_restore: error: failed "sensitive-demo"\nDETAIL: source record\n')
        self.assertNotIn("sensitive-demo", headline)
        self.assertNotIn("source record", headline)

    def test_restored_zero_count_is_not_accepted_as_success(self):
        repository = PostgreSQLProvisioningRepository(port=5433, major_version=18)
        connection = MagicMock()
        connection.execute.return_value.fetchone.return_value = (0,)
        with patch.object(repository, "connect") as connect:
            connect.return_value.__enter__.return_value = connection
            with self.assertRaisesRegex(ValueError, "건수 불일치"):
                repository.validate_restored("reader-demo", {"tables": {
                    "market.prices": {"schema": "market", "table": "prices", "rows": 1}}},
                    latest_trade_date="2026-10-21")
        self.assertEqual(connection.execute.call_count, 2)

    def test_partition_parent_count_must_match_backup_children(self):
        repository = PostgreSQLProvisioningRepository(port=5433, major_version=18)
        connection = MagicMock()
        count, parents, descendants, parent_count = (MagicMock() for _ in range(4))
        count.fetchone.return_value = (1,)
        parents.fetchall.return_value = [(42, "market", "prices_parent")]
        descendants.fetchall.return_value = [("market", "prices")]
        parent_count.fetchone.return_value = (2,)
        connection.execute.side_effect = [MagicMock(), count, parents, descendants, parent_count]
        with patch.object(repository, "connect") as connect:
            connect.return_value.__enter__.return_value = connection
            with self.assertRaisesRegex(ValueError, "파티션 부모 건수 불일치"):
                repository.validate_restored("reader-demo", {"tables": {
                    "market.prices": {"schema": "market", "table": "prices", "rows": 1,
                                      "dates": {}, "columns": []}}}, latest_trade_date="2026-10-21")

    def test_restore_status_uses_only_18_reader_and_aggregate_metrics(self):
        repository = PostgreSQLProvisioningRepository(port=5433, major_version=18)
        with patch.object(repository, "connect") as connect:
            connection = connect.return_value.__enter__.return_value
            connection.execute.return_value.fetchone.side_effect = [(0, 1), (1, 12)]
            self.assertEqual(repository.restore_status("reader-demo"), {
                "copy_operations": 0, "index_operations": 1, "validation_queries": 1, "longest_query_seconds": 12.0})
            connect.assert_called_once_with("krx_reader", "reader-demo", "krx_research")
            self.assertIn("pg_stat_progress_create_index", connection.execute.call_args_list[0].args[0])
        with self.assertRaises(ValueError):
            PostgreSQLProvisioningRepository().restore_status("reader-demo")

    def test_resume_validates_without_restoring_and_preserves_failed_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            PostgreSQLSetupService(root, self.repository()).configure("admin-demo", "reader-demo", "writer-demo")
            report_path = root / "validation.json"
            report_path.write_text(json.dumps({"status": "failed", "failed_stage": "restored-validation",
                "target_port": 5433, "original_port": 5432, "source_summary": {}, "error": "previous failure"}))
            original_env = (root / ".env").read_bytes()
            original_report = report_path.read_bytes()
            with patch("krx_research.application.postgresql_setup.PostgreSQLProvisioningRepository") as repository:
                repository.return_value.validate_restored.side_effect = ValueError("count mismatch")
                with self.assertRaisesRegex(ValueError, "count mismatch"):
                    PostgreSQLSetupService(root).verify_restored(
                        report_path, complete18=True, latest_trade_date="2026-10-21")
                self.assertEqual((root / ".env").read_bytes(), original_env)
                repository.return_value.validate_restored.side_effect = None
                repository.return_value.validate_restored.return_value = {"table_counts": {"parent": 1}}
                result = PostgreSQLSetupService(root).verify_restored(
                    report_path, complete18=True, latest_trade_date="2026-10-21")
                repository.return_value.provision.assert_not_called()
            self.assertEqual(EnvironmentResolver._read(root / ".env")["KRX_DB_PORT"], "5433")
            self.assertEqual(report_path.read_bytes(), original_report)
            self.assertEqual(Path(result["report"]).name, "validation_completed.json")


if __name__ == "__main__":
    unittest.main()
