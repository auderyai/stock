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

    def cloud_run(self, target_date: date, *, stage: str = "menu2") -> dict[str, Any]:
        if stage not in {"menu2", "menu5", "menu7", "remaining", "all"}:
            raise ValueError(f"지원하지 않는 클라우드 단계입니다: {stage}")
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

            commit = self._git_commit()
            checkpoints: list[dict[str, Any]] = []
            actual = before
            completed_stage = str(metadata.get("completed_stage") or "")

            if stage in {"menu2", "all"}:
                menu2 = self._run_menu2_with_retry(target_date.isoformat())
                with self._connection(conninfo) as conn:
                    actual = self._latest_date(conn)
                no_new = self._validate_menu2_date(before, actual, target_date, menu2)
                if no_new is not None:
                    return no_new
                if before != actual:
                    metadata, checkpoint = self._publish_checkpoint(
                        drive, metadata, work, conninfo, actual, commit, "menu2"
                    )
                    checkpoints.append(checkpoint)
                if stage == "menu2":
                    return {
                        "status": "updated" if checkpoints else "already-complete",
                        "reference_date": target_date.isoformat(),
                        "completed_stage": "menu2",
                        "checkpoints": checkpoints,
                    }

            self._require_reference_date(actual, target_date, stage)
            day = target_date.isoformat()

            if stage in {"menu5", "remaining", "all"} and not self._stage_completed(
                completed_stage, "menu5"
            ):
                self._run("scripts/update_ls_investor_date_range.py", "--start", day, "--end", day, "--chunk-days", "1")
                metadata, checkpoint = self._publish_checkpoint(
                    drive, metadata, work, conninfo, target_date, commit, "menu5"
                )
                checkpoints.append(checkpoint)
                completed_stage = "menu5"
                if stage == "menu5":
                    return {
                        "status": "updated",
                        "reference_date": day,
                        "completed_stage": "menu5",
                        "delta_rows": checkpoint["delta_rows"],
                        "checkpoints": checkpoints,
                    }

            elif stage == "menu5":
                return {
                    "status": "already-complete",
                    "reference_date": day,
                    "completed_stage": completed_stage,
                    "checkpoints": checkpoints,
                }

            if stage in {"menu7", "remaining", "all"} and not self._stage_completed(
                completed_stage, "menu7"
            ):
                self._run_menu7_with_retry(day)
                metadata, checkpoint = self._publish_checkpoint(
                    drive, metadata, work, conninfo, target_date, commit, "menu7"
                )
                checkpoints.append(checkpoint)

            if not checkpoints:
                return {
                    "status": "already-complete",
                    "reference_date": day,
                    "completed_stage": completed_stage,
                    "checkpoints": checkpoints,
                }

            return {
                "status": "updated",
                "reference_date": day,
                "completed_stage": "menu7",
                "delta_rows": checkpoints[-1]["delta_rows"],
                "checkpoints": checkpoints,
            }

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

    def _publish_checkpoint(
        self,
        drive: GoogleDriveClient,
        metadata: dict[str, Any],
        work: Path,
        conninfo: str,
        reference_date: date,
        commit: str,
        stage: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Persist one completed menu before the next expensive menu starts."""
        day = reference_date.isoformat()
        checkpoint_dir = work / stage
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        with self._connection(conninfo) as conn:
            exporter = DatabaseArchiveService(conn, conninfo=conninfo)
            delta = exporter.export_delta(
                checkpoint_dir / f"delta-{day}.tar.gz",
                target_date=reference_date,
                git_commit=commit,
            )
            state = exporter.export_snapshot(
                checkpoint_dir / "next-state.tar.gz",
                pg_dump=self._executable("pg_dump"),
                reference_date=reference_date,
                git_commit=commit,
            )

        delta_enc = checkpoint_dir / f"delta-{day}-{stage}-{commit[:12]}.enc"
        next_slot = "b" if metadata.get("state_slot") == "a" else "a"
        state_enc = checkpoint_dir / f"worker-state-{next_slot}.enc"
        ArchiveCipher.encrypt(delta.path, delta_enc, self._context.credentials.archive_key)
        ArchiveCipher.encrypt(state.path, state_enc, self._context.credentials.archive_key)

        delta_id = drive.upload(
            delta_enc,
            name=delta_enc.name,
            parent_id=str(metadata["delta_folder_id"]),
        )
        state_id = drive.upload(
            state_enc,
            name=state_enc.name,
            parent_id=drive.ensure_folder("worker-state"),
        )
        deltas = [
            item for item in metadata.get("deltas", [])
            if item.get("reference_date") != day
        ]
        delta_record = self._delta_record(
            delta_id, delta_enc.name, delta_enc, delta.manifest
        )
        delta_record["completed_stage"] = stage
        deltas.append(delta_record)
        metadata.update(
            {
                "state": self._state_record(
                    state_id, state_enc.name, state_enc, state.manifest
                ),
                "state_slot": next_slot,
                "deltas": sorted(
                    deltas, key=lambda item: item["reference_date"]
                )[-400:],
                "completed_stage": stage,
            }
        )
        drive.write_json(metadata, name=METADATA_NAME, parent_id=drive.root_folder_id)
        return metadata, {
            "stage": stage,
            "reference_date": day,
            "delta_rows": self._rows(delta.manifest),
        }

    @staticmethod
    def _validate_menu2_date(
        before: date | None,
        actual: date | None,
        target_date: date,
        exit_code: int,
    ) -> dict[str, str] | None:
        # A restored snapshot may already contain the requested date.  In that
        # case menu 2 correctly reports a completed/skipped update and the
        # coordinator must continue to menus 5 and 7 instead of requiring a
        # strictly newer date.
        if actual == target_date:
            return None
        if actual is None or (before is not None and actual <= before):
            if exit_code == 2:
                return {
                    "status": "no-new-trading-day",
                    "requested_date": target_date.isoformat(),
                }
            raise CloudArchiveError("메뉴 2 후 요청 거래일이 확인되지 않았습니다.")
        raise CloudArchiveError(
            f"요청일과 DB 최신 거래일이 다릅니다: 요청={target_date}, DB={actual}"
        )

    @staticmethod
    def _require_reference_date(
        actual: date | None, target_date: date, stage: str
    ) -> None:
        if actual != target_date:
            raise CloudArchiveError(
                f"{stage} 실행 전 메뉴 2 기준일이 준비되지 않았습니다: "
                f"요청={target_date}, DB={actual}"
            )

    @staticmethod
    def _stage_completed(completed_stage: str, requested_stage: str) -> bool:
        order = {"": 0, "menu2": 1, "menu5": 2, "menu7": 3}
        return order.get(completed_stage, 0) >= order[requested_stage]

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
            "completed_stage": metadata.get("completed_stage"),
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
