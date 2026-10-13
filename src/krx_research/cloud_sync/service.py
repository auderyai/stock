from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

import psycopg
from psycopg.rows import dict_row

from krx_research.data_engine.config import database_conninfo

from .archive import (
    ArchiveCipher,
    CloudArchiveError,
    DatabaseArchiveService,
    DeltaArchiveApplier,
    verify_archive,
)
from .credentials import DriveCredentials
from .drive import GoogleDriveClient


METADATA_NAME = "latest.json"


@dataclass(frozen=True, slots=True)
class SyncContext:
    root: Path
    credentials: DriveCredentials

    def drive(self) -> GoogleDriveClient:
        return GoogleDriveClient(
            client_id=self.credentials.client_id,
            client_secret=self.credentials.client_secret,
            refresh_token=self.credentials.refresh_token,
            root_folder_id=self.credentials.root_folder_id,
        )


class StockDriveSyncService:
    """Coordinates encrypted Drive state without exposing credential values."""

    def __init__(self, context: SyncContext) -> None:
        self._context = context

    def bootstrap(self) -> dict[str, Any]:
        conninfo = database_conninfo()
        with self._connection(conninfo) as conn, tempfile.TemporaryDirectory(prefix="stock-bootstrap-") as name:
            work = Path(name)
            archive = work / "worker-state.tar.gz"
            result = DatabaseArchiveService(conn, conninfo=conninfo).export_snapshot(
                archive,
                pg_dump=self._executable("pg_dump"),
                git_commit=self._git_commit(),
            )
            encrypted = work / "worker-state-a.enc"
            ArchiveCipher.encrypt(archive, encrypted, self._context.credentials.archive_key)
            with self._context.drive() as drive:
                state_folder = drive.ensure_folder("worker-state")
                delta_folder = drive.ensure_folder("daily-deltas")
                file_id = drive.upload(encrypted, name=encrypted.name, parent_id=state_folder)
                metadata = {
                    "format_version": 1,
                    "state": self._state_record(file_id, encrypted.name, encrypted, result.manifest),
                    "state_slot": "a",
                    "delta_folder_id": delta_folder,
                    "deltas": [],
                }
                drive.write_json(metadata, name=METADATA_NAME, parent_id=drive.root_folder_id)
                return self._public_result(metadata)

    def sync_local(self) -> dict[str, Any]:
        applied: list[str] = []
        skipped: list[str] = []
        with self._context.drive() as drive:
            metadata = self._metadata(drive)
            with self._connection() as conn, tempfile.TemporaryDirectory(prefix="stock-delta-") as name:
                work = Path(name)
                for record in sorted(metadata.get("deltas", []), key=lambda item: item["reference_date"]):
                    encrypted = drive.download(str(record["id"]), work / str(record["name"]))
                    self._verify_download(encrypted, record)
                    archive = work / (encrypted.stem + ".tar.gz")
                    ArchiveCipher.decrypt(encrypted, archive, self._context.credentials.archive_key)
                    result = DeltaArchiveApplier(conn).apply(archive)
                    target = applied if result["apply_status"] == "applied" else skipped
                    target.append(str(result["batch_id"]))
                    encrypted.unlink(missing_ok=True)
                    archive.unlink(missing_ok=True)
        return {"applied": applied, "already_applied": skipped}

    def cloud_run(self, target_date: date) -> dict[str, Any]:
        conninfo = database_conninfo()
        with self._context.drive() as drive, tempfile.TemporaryDirectory(prefix="stock-cloud-") as name:
            work = Path(name)
            metadata = self._metadata(drive)
            state_record = metadata.get("state") or {}
            encrypted_state = drive.download(str(state_record["id"]), work / str(state_record["name"]))
            self._verify_download(encrypted_state, state_record)
            state_archive = work / "worker-state.tar.gz"
            ArchiveCipher.decrypt(encrypted_state, state_archive, self._context.credentials.archive_key)

            with self._connection(conninfo) as conn:
                archive_service = DatabaseArchiveService(conn, conninfo=conninfo)
                archive_service.restore_snapshot(state_archive, psql=self._executable("psql"))
                before = self._latest_date(conn)

            menu2 = self._run_menu2_with_retry(target_date.isoformat())
            with self._connection(conninfo) as conn:
                actual = self._latest_date(conn)
            if actual is None or actual <= before:
                if menu2 == 2:
                    return {"status": "no-new-trading-day", "requested_date": target_date.isoformat()}
                raise CloudArchiveError("메뉴 2 후 새 거래일이 확인되지 않았습니다.")
            if actual != target_date:
                raise CloudArchiveError(
                    f"요청일과 DB 최신 거래일이 다릅니다: 요청={target_date}, DB={actual}"
                )

            day = actual.isoformat()
            self._run("scripts/update_ls_investor_date_range.py", "--start", day, "--end", day, "--chunk-days", "1")
            self._run_menu7_with_retry(day)

            commit = self._git_commit()
            with self._connection(conninfo) as conn:
                exporter = DatabaseArchiveService(conn, conninfo=conninfo)
                delta = exporter.export_delta(work / f"delta-{day}.tar.gz", target_date=actual, git_commit=commit)
                state = exporter.export_snapshot(
                    work / "next-state.tar.gz", pg_dump=self._executable("pg_dump"),
                    reference_date=actual, git_commit=commit,
                )
            delta_enc = work / f"delta-{day}-{commit[:12]}.enc"
            next_slot = "b" if metadata.get("state_slot") == "a" else "a"
            state_enc = work / f"worker-state-{next_slot}.enc"
            ArchiveCipher.encrypt(delta.path, delta_enc, self._context.credentials.archive_key)
            ArchiveCipher.encrypt(state.path, state_enc, self._context.credentials.archive_key)

            delta_folder = str(metadata["delta_folder_id"])
            state_folder = drive.ensure_folder("worker-state")
            delta_id = drive.upload(delta_enc, name=delta_enc.name, parent_id=delta_folder)
            state_id = drive.upload(state_enc, name=state_enc.name, parent_id=state_folder)
            deltas = [item for item in metadata.get("deltas", []) if item.get("reference_date") != day]
            deltas.append(self._delta_record(delta_id, delta_enc.name, delta_enc, delta.manifest))
            metadata.update(
                {
                    "state": self._state_record(state_id, state_enc.name, state_enc, state.manifest),
                    "state_slot": next_slot,
                    "deltas": sorted(deltas, key=lambda item: item["reference_date"])[-400:],
                }
            )
            drive.write_json(metadata, name=METADATA_NAME, parent_id=drive.root_folder_id)
            return {"status": "updated", "reference_date": day, "delta_rows": self._rows(delta.manifest)}

    def verify(self) -> dict[str, Any]:
        with self._context.drive() as drive, tempfile.TemporaryDirectory(prefix="stock-verify-") as name:
            metadata = self._metadata(drive)
            record = metadata["state"]
            encrypted = drive.download(str(record["id"]), Path(name) / str(record["name"]))
            self._verify_download(encrypted, record)
            archive = Path(name) / "worker-state.tar.gz"
            ArchiveCipher.decrypt(encrypted, archive, self._context.credentials.archive_key)
            manifest = verify_archive(archive, expected_kind="worker-state")
            result = self._public_result(metadata)
            result["verified_tables"] = len(manifest.get("tables", []))
            result["verified_rows"] = self._rows(manifest)
            return result

    def _run(self, script: str, *arguments: str, accepted: tuple[int, ...] = (0,)) -> int:
        env = os.environ.copy()
        src = str(self._context.root / "src")
        current = env.get("PYTHONPATH")
        env["PYTHONPATH"] = os.pathsep.join((src, current)) if current else src
        completed = subprocess.run(
            [sys.executable, str(self._context.root / script), *arguments],
            cwd=self._context.root,
            env=env,
            check=False,
        )
        if completed.returncode not in accepted:
            raise CloudArchiveError(f"작업 실패: {script}, 종료코드={completed.returncode}")
        return completed.returncode

    def _run_menu7_with_retry(self, day: str) -> None:
        arguments = ("--menu", "7", "--start", day, "--end", day, "--no-investor")
        result = self._run(
            "scripts/run_xing_db_menu.py", *arguments, accepted=(0, 3)
        )
        if result == 3:
            self._run("scripts/run_xing_db_menu.py", *arguments)

    def _run_menu2_with_retry(self, day: str) -> int:
        arguments = (
            "--as-of", day,
            "--no-investor", "--markets", "KOSPI", "KOSDAQ",
        )
        for _ in range(2):
            result = self._run(
                "scripts/run_daily_pipeline.py", *arguments, accepted=(0, 2, 3)
            )
            if result != 3:
                return result
        return self._run("scripts/run_daily_pipeline.py", *arguments, accepted=(0, 2))

    def _connection(self, conninfo: str | None = None):
        return psycopg.connect(conninfo or database_conninfo(), row_factory=dict_row)

    def _git_commit(self) -> str:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self._context.root,
            text=True, capture_output=True, check=False,
        )
        value = completed.stdout.strip()
        return value if completed.returncode == 0 and len(value) == 40 else "unknown"

    @staticmethod
    def _latest_date(conn) -> date | None:
        row = conn.execute("SELECT max(trade_date)::date AS day FROM market.ohlcv_daily").fetchone()
        return row["day"] if row else None

    @staticmethod
    def _executable(name: str) -> Path:
        found = shutil.which(name)
        if found:
            return Path(found)
        if sys.platform == "win32":
            postgres_root = Path(r"C:\Program Files\PostgreSQL")
            if postgres_root.is_dir():
                candidates = sorted(
                    postgres_root.glob(f"*/bin/{name}.exe"), reverse=True
                )
                if candidates:
                    return candidates[0]
        raise CloudArchiveError(f"필수 PostgreSQL 도구가 없습니다: {name}")

    @staticmethod
    def _metadata(drive: GoogleDriveClient) -> dict[str, Any]:
        document = drive.read_json(METADATA_NAME, drive.root_folder_id)
        if not document or document.get("format_version") != 1 or not document.get("state"):
            raise CloudArchiveError("Google Drive 초기 작업 상태가 없습니다. bootstrap을 먼저 실행하십시오.")
        return document

    @staticmethod
    def _verify_download(path: Path, record: dict[str, Any]) -> None:
        if _sha256(path) != record.get("sha256"):
            raise CloudArchiveError(f"Drive 다운로드 해시 불일치: {path.name}")

    @staticmethod
    def _state_record(file_id: str, name: str, path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": file_id, "name": name, "sha256": _sha256(path),
            "reference_date": manifest["reference_date"], "batch_id": manifest["batch_id"],
        }

    @staticmethod
    def _delta_record(file_id: str, name: str, path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": file_id, "name": name, "sha256": _sha256(path),
            "reference_date": manifest["reference_date"], "batch_id": manifest["batch_id"],
            "rows": StockDriveSyncService._rows(manifest),
        }

    @staticmethod
    def _rows(manifest: dict[str, Any]) -> int:
        return sum(int(item.get("rows", 0)) for item in manifest.get("tables", []))

    @staticmethod
    def _public_result(metadata: dict[str, Any]) -> dict[str, Any]:
        state = metadata.get("state") or {}
        return {
            "status": "ready",
            "state_reference_date": state.get("reference_date"),
            "delta_count": len(metadata.get("deltas", [])),
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
