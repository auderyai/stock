"""Account setup orchestration with safe errors and the shared .env repository."""
from __future__ import annotations

from pathlib import Path
from dataclasses import replace
from datetime import datetime
import hashlib
import json
import psycopg

from krx_research.database.provisioning import PostgreSQLProvisioningRepository
from krx_research.database.administrative_repository import AdministrativeRepository
from krx_research.database.backup import PostgreSQLBackupArchive
from krx_research.database.settings import resolve_database_target_from_env_file
from krx_research.data_engine.config import settings_from_database_target
from krx_research.infrastructure.env_file_repository import EnvFileRepository


class PostgreSQLSetupService:
    def __init__(self, root: str | Path, repository=None):
        self.root = Path(root)
        self.repository = repository or PostgreSQLProvisioningRepository()
        self.environment = EnvFileRepository(self.root / ".env")

    def verify_connection(self) -> dict:
        target = resolve_database_target_from_env_file(self.environment.path, read_only=True)
        try:
            with AdministrativeRepository(
                settings_from_database_target(target), application_name="setup_check", read_only=True,
            ) as repository:
                identity = repository.server_identity()
        except Exception:
            raise RuntimeError("읽기 전용 DB 연결 검증 실패") from None
        if (identity["db"], identity["user"], identity["read_only"]) != (target.database, target.user, "on"):
            raise ValueError("연결 정보 또는 읽기 전용 상태 검증 실패")
        return identity

    def inspect18(self, request: dict, progress=lambda message: None) -> tuple:
        archive = Path(request["backup"]).resolve()
        backup = PostgreSQLBackupArchive(Path(r"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe"))
        directory = self.root / "logs" / "restore" / datetime.now().strftime("pg18_%Y%m%d_%H%M%S_%f")
        directory.mkdir(parents=True)
        report = {"status": "pending", "source": str(archive), "target_port": 5433, "original_port": 5432}
        stage = "archive-integrity"
        try:
            progress("PostgreSQL 18.6 백업 크기·SHA-256·목록 검증 중...")
            report["integrity"] = backup.inspect(
                archive, expected_size=request["expected_size"], expected_sha256=request["sha256"],
                list_path=directory / "restore.list",
            )
            stage = "source-counts"
            progress("백업 원본의 테이블 건수·재무 분기·체크포인트 집계 중...")
            report["source_summary"] = backup.source_summary(
                archive, expected_tables=report["integrity"]["table_data_entries"])
            trade_dates = [item["dates"]["trade_date"] for item in report["source_summary"]["tables"].values()
                           if item["dates"].get("trade_date")]
            if not trade_dates or max(trade_dates) != request["latest_trade_date"]:
                raise ValueError("백업의 최신 거래일이 요청된 날짜와 일치하지 않습니다.")
            report["status"] = "inspected"
        except Exception as error:
            report.update(status="failed", failed_stage=stage, error_type=type(error).__name__)
            message = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
            report["error"] = message
            raise RuntimeError(f"백업 검사 중단: {stage}: {message}") from None
        finally:
            (directory / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return backup, archive, directory, report

    def verify_saved(self) -> None:
        reader = resolve_database_target_from_env_file(self.environment.path, read_only=True)
        writer = resolve_database_target_from_env_file(self.environment.path, read_only=False)
        if (reader.user, writer.user, reader.database, writer.database) != (
            self.repository.READER, self.repository.WRITER, self.repository.DATABASE, self.repository.DATABASE,
        ):
            raise ValueError("저장된 계정 이름과 대상 DB가 일치하지 않습니다.")
        if reader.host != "127.0.0.1" or writer.host != reader.host or writer.port != reader.port:
            raise ValueError("저장된 읽기·쓰기 연결 대상이 일치하지 않습니다.")
        try:
            repository = PostgreSQLProvisioningRepository(
                port=reader.port, major_version=18 if reader.port == 5433 else 16,
            )
            repository.verify(reader.password, writer.password, require_empty=reader.port != 5433)
        except Exception:
            raise RuntimeError("저장된 계정의 연결·최소 권한 검증 실패") from None

    def verify_restored(self, report_path: Path, *, complete18=False, latest_trade_date=None) -> dict:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        original = self.environment.path.read_bytes()
        reader = resolve_database_target_from_env_file(self.environment.path, read_only=True)
        writer = resolve_database_target_from_env_file(self.environment.path, read_only=False)
        expected_port = 5432 if complete18 else 5433
        allowed_report = (report.get("status") == "failed" and report.get("failed_stage") == "restored-validation") \
            if complete18 else report.get("status") == "verified"
        if not allowed_report or (report.get("target_port"), report.get("original_port")) != (5433, 5432) or (reader.host, reader.port, reader.database, reader.user) != (
            "127.0.0.1", expected_port, "krx_research", "krx_reader",
        ) or (writer.host, writer.port, writer.database, writer.user) != (
            reader.host, expected_port, reader.database, "krx_writer",
        ):
            raise ValueError("복원 보고서의 중단 단계와 로컬 연결 설정이 일치하지 않습니다.")
        latest_trade_date = latest_trade_date or report.get("validation", {}).get("latest_trade_date")
        if not latest_trade_date:
            raise ValueError("검증할 최신 거래일을 지정하십시오.")
        repository = PostgreSQLProvisioningRepository(port=5433, major_version=18)
        repository.verify(reader.password, writer.password, require_empty=False)
        result = repository.validate_restored(
            reader.password, report["source_summary"], latest_trade_date=latest_trade_date,
        )
        if complete18:
            self._switch18(original)
            report["resumed_from"] = str(report_path)
            report["previous_failure"] = {key: report.pop(key) for key in ("failed_stage", "error_type", "error", "sqlstate") if key in report}
            report["status"] = "verified"
            report_path = report_path.with_name("validation_completed.json")
        report["validation"] = result
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"report": str(report_path), **result}

    def _switch18(self, original: bytes) -> None:
        if hashlib.sha256(self.environment.path.read_bytes()).digest() != hashlib.sha256(original).digest():
            raise ValueError("검증 중 .env가 외부에서 변경되어 전환을 중단했습니다.")
        self.environment.save({"KRX_DB_PORT": "5433", "KRX_DB_DUMP": r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe"})

    def restore_status(self) -> dict:
        reader = resolve_database_target_from_env_file(self.environment.path, read_only=True)
        if (reader.host, reader.database, reader.user) != ("127.0.0.1", "krx_research", "krx_reader"):
            raise ValueError("로컬 읽기 계정 설정이 필요합니다.")
        return PostgreSQLProvisioningRepository(port=5433, major_version=18).restore_status(reader.password)

    def migrate18(self, admin_password: str, request: dict, progress=lambda message: None) -> dict:
        if not admin_password or any(c in admin_password for c in "\r\n\0"):
            raise ValueError("PostgreSQL 18 관리자 암호를 로컬 입력창에 입력하십시오.")
        original = self.environment.path.read_bytes()
        reader = resolve_database_target_from_env_file(self.environment.path, read_only=True)
        writer = resolve_database_target_from_env_file(self.environment.path, read_only=False)
        if (reader.host, reader.port, reader.database, reader.user, writer.user) != (
            "127.0.0.1", 5432, "krx_research", "krx_reader", "krx_writer",
        ) or (writer.host, writer.port, writer.database) != (reader.host, reader.port, reader.database):
            raise ValueError("전환 전 .env가 기존 5432 계정 설정과 일치하지 않습니다.")
        repository = PostgreSQLProvisioningRepository(port=5433, major_version=18)
        backup, archive, directory, report = self.inspect18(request, progress)
        source = report["source_summary"]
        stage = "provision-18"
        try:
            progress("5433의 PostgreSQL 18에 빈 DB·최소 권한 계정 설정 중... 16과 .env는 보존합니다.")
            repository.provision(admin_password, reader.password, writer.password)
            repository.verify(reader.password, writer.password)
            stage = "restore-transaction"
            progress("5433의 빈 krx_research에 단일 트랜잭션으로 복원 중...")
            administrator = replace(reader, port=5433, user="postgres", password=admin_password)
            backup.restore(archive, administrator, list_path=directory / "restore.list")
            stage = "restored-validation"
            progress("복원된 테이블 건수·거래일·재무 분기·체크포인트·권한 검증 중...")
            repository.apply_restored_permissions(admin_password)
            repository.verify(reader.password, writer.password, require_empty=False)
            report["validation"] = repository.validate_restored(
                reader.password, source, latest_trade_date=request["latest_trade_date"],
            )
            stage = "environment-switch"
            # This is the only configuration write, after every restore check has passed.
            self._switch18(original)
            report["status"] = "verified"
            progress("복원 검증 통과. .env를 5433으로 전환했습니다. PostgreSQL 16은 보존했습니다.")
        except Exception as error:
            report["status"], report["failed_stage"] = "failed", stage
            report["error_type"] = type(error).__name__
            if isinstance(error, psycopg.Error):
                report["sqlstate"] = error.sqlstate
                message = f"PostgreSQL 오류 SQLSTATE={error.sqlstate}"
            else:
                message = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
            report["error"] = message
            raise RuntimeError(f"5433 전환 중단: {stage}: {message}") from None
        finally:
            (directory / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"report": str(directory / "validation.json"), **report["validation"]}

    def configure(self, admin_password: str, read_password: str, write_password: str) -> None:
        passwords = (admin_password, read_password, write_password)
        if any(not value or value != value.strip() or any(c in value for c in "\r\n\0") for value in passwords):
            raise ValueError("암호를 모두 입력하십시오. 양끝 공백·줄바꿈·NUL은 사용할 수 없습니다.")
        if len(set(passwords)) != 3:
            raise ValueError("관리자·읽기·쓰기 암호는 서로 다르게 지정하십시오.")
        try:
            self.repository.provision(*passwords)
            self.repository.verify(read_password, write_password)
            values = {
                "KRX_DB_ENGINE": "postgresql", "KRX_DB_HOST": "127.0.0.1", "KRX_DB_PORT": "5432",
                "KRX_DB_NAME": self.repository.DATABASE,
                "KRX_DB_READ_USER": self.repository.READER,
                "KRX_DB_READ_PASSWORD": f'"{read_password}"',
                "KRX_DB_WRITE_USER": self.repository.WRITER,
                "KRX_DB_WRITE_PASSWORD": f'"{write_password}"',
            }
            self.environment.save(values)
            for readonly, name, password in (
                (True, self.repository.READER, read_password),
                (False, self.repository.WRITER, write_password),
            ):
                target = resolve_database_target_from_env_file(self.environment.path, read_only=readonly)
                if (target.user, target.password, target.database) != (name, password, self.repository.DATABASE):
                    raise ValueError("환경 파일 재검증 실패")
        except Exception as error:
            # SQL diagnostics/connection strings can contain credentials. Never chain them.
            state = getattr(error, "sqlstate", None)
            suffix = f" (SQLSTATE {state})" if state and len(state) == 5 and state.isalnum() else ""
            raise RuntimeError(
                "설정을 완료하지 못했습니다. 관리자 암호, 서비스, 기존 DB/동명 역할을 확인하십시오."
                + suffix
            ) from None
