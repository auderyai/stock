from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
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


class TransientSourceError(CloudArchiveError):
    """A supplier or network failure exhausted its bounded retries."""


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
            cleaned = self._acknowledge_and_cleanup(drive, metadata)
        return {"applied": applied, "already_applied": skipped, "cleaned": cleaned}

    def update_local(self) -> dict[str, Any]:
        """Apply Drive deltas and prove a second pass is idempotent."""
        applied = self.sync_local()
        verified = self.sync_local()
        if verified["applied"]:
            raise CloudArchiveError("로컬 재검증에서 새 적용 건이 발견되었습니다.")
        return {
            "status": "verified",
            "applied": applied["applied"],
            "already_applied": verified["already_applied"],
            "cleaned": sorted(set(applied["cleaned"] + verified["cleaned"])),
        }

    def cleanup_synced(self, through: date, *, confirmed: bool = False) -> dict[str, Any]:
        """Delete only completed deltas already acknowledged by the local database."""
        with self._context.drive() as drive:
            metadata = self._metadata(drive)
            day = through.isoformat()
            synced = str(metadata.get("local_synced_through") or "")
            state_day = str((metadata.get("state") or {}).get("reference_date") or "")
            if not synced or day > synced:
                raise CloudArchiveError(
                    f"로컬 반영이 확인되지 않은 날짜는 정리할 수 없습니다: 요청={day}, 반영={synced or '없음'}"
                )
            if not state_day or day > state_day:
                raise CloudArchiveError(
                    f"작업 상태에 포함되지 않은 날짜는 정리할 수 없습니다: 요청={day}, 상태={state_day or '없음'}"
                )
            if metadata.get("state_checkpoint_pending"):
                raise CloudArchiveError("저장 중인 체크포인트가 있어 Drive 자료를 정리할 수 없습니다.")
            replay = set(metadata.get("replay_delta_dates") or [])
            targets = [
                item for item in metadata.get("deltas", [])
                if str(item["reference_date"]) <= day
            ]
            incomplete = [
                str(item["reference_date"]) for item in targets
                if self._completed_stage_for(
                    metadata, date.fromisoformat(str(item["reference_date"]))
                ) != "menu7" or str(item["reference_date"]) in replay
            ]
            if incomplete:
                raise CloudArchiveError(
                    "메뉴 7 완료·복구 반영이 확인되지 않은 날짜가 있습니다: "
                    + ", ".join(sorted(set(incomplete)))
                )
            result = {
                "status": "ready-to-delete" if targets else "nothing-to-delete",
                "through": day,
                "dates": sorted({str(item["reference_date"]) for item in targets}),
                "file_count": len(targets),
            }
            if not confirmed or not targets:
                return result
            for item in targets:
                drive.delete(str(item["id"]))
            metadata["deltas"] = [item for item in metadata.get("deltas", []) if item not in targets]
            drive.write_json(metadata, name=METADATA_NAME, parent_id=drive.root_folder_id)
            result["status"] = "deleted"
            return result

    def publish_local_base(self, target_date: date) -> dict[str, Any]:
        """Publish a validated local menu-2 base without replacing cloud state."""
        conninfo = database_conninfo()
        with self._context.drive() as drive, tempfile.TemporaryDirectory(
            prefix="stock-base-"
        ) as name, self._connection(conninfo) as conn:
            metadata = self._metadata(drive)
            state_date = date.fromisoformat(str(metadata["state"]["reference_date"]))
            if target_date < state_date:
                raise CloudArchiveError(
                    f"클라우드 상태보다 과거 기준일은 게시할 수 없습니다: "
                    f"요청={target_date}, 상태={state_date}"
                )
            completed = self._completed_stage_for(metadata, target_date)
            if self._stage_completed(completed, "menu2"):
                return {"status": "already-complete", "reference_date": target_date.isoformat()}

            work = Path(name)
            delta = DatabaseArchiveService(conn, conninfo=conninfo).export_delta(
                work / f"delta-{target_date}.tar.gz",
                target_date=target_date,
                git_commit=self._git_commit(),
            )
            market_rows = next(
                (
                    int(item["rows"])
                    for item in delta.manifest["tables"]
                    if item["relation"] == "market.ohlcv_daily"
                ),
                0,
            )
            if market_rows <= 0:
                raise CloudArchiveError(
                    f"로컬 메뉴 2 기준자료가 0건입니다: {target_date}"
                )

            encrypted = work / f"delta-{target_date}-menu2-local.enc"
            ArchiveCipher.encrypt(delta.path, encrypted, self._context.credentials.archive_key)
            file_id = drive.upload(
                encrypted, name=encrypted.name, parent_id=str(metadata["delta_folder_id"])
            )
            record = self._delta_record(file_id, encrypted.name, encrypted, delta.manifest)
            record["completed_stage"] = "menu2"
            metadata["deltas"] = sorted(
                [
                    item for item in metadata.get("deltas", [])
                    if item.get("reference_date") != target_date.isoformat()
                ] + [record],
                key=lambda item: item["reference_date"],
            )[-400:]
            metadata["completed_stage"] = self._record_stage(
                metadata, target_date, "menu2"
            )
            metadata["state_checkpoint_pending"] = "menu2"
            drive.write_json(metadata, name=METADATA_NAME, parent_id=drive.root_folder_id)
            return {
                "status": "updated",
                "reference_date": target_date.isoformat(),
                "completed_stage": "menu2",
                "market_rows": market_rows,
            }

    def publish_local_progress(self, target_date: date) -> dict[str, Any]:
        """Seed a historical cloud retry with verified local rows without claiming completion."""
        conninfo = database_conninfo()
        day = target_date.isoformat()
        with self._context.drive() as drive, tempfile.TemporaryDirectory(
            prefix="stock-progress-"
        ) as name, self._connection(conninfo) as conn:
            metadata = self._metadata(drive)
            work = Path(name)
            delta = DatabaseArchiveService(conn, conninfo=conninfo).export_delta(
                work / f"delta-{day}.tar.gz",
                target_date=target_date,
                git_commit=self._git_commit(),
            )
            market_rows = next((
                int(item["rows"]) for item in delta.manifest["tables"]
                if item["relation"] == "market.ohlcv_daily"
            ), 0)
            if market_rows <= 0:
                raise CloudArchiveError(f"로컬 기준자료가 0건입니다: {day}")

            encrypted = work / f"delta-{day}-local-progress.enc"
            ArchiveCipher.encrypt(delta.path, encrypted, self._context.credentials.archive_key)
            file_id = drive.upload(
                encrypted, name=encrypted.name,
                parent_id=str(metadata["delta_folder_id"]),
            )
            record = self._delta_record(file_id, encrypted.name, encrypted, delta.manifest)
            record["completed_stage"] = "menu2"
            metadata["deltas"] = sorted(
                [item for item in metadata.get("deltas", [])
                 if item.get("reference_date") != day] + [record],
                key=lambda item: item["reference_date"],
            )[-400:]
            stages = dict(metadata.get("stage_dates") or {})
            stages[day] = "menu2"
            metadata["stage_dates"] = stages
            replay = set(metadata.get("replay_delta_dates") or [])
            replay.add(day)
            metadata["replay_delta_dates"] = sorted(replay)
            if metadata.get("menu5_reference_date") == day:
                metadata.pop("menu5_reference_date", None)
                metadata.pop("menu5_next_offset", None)
            drive.write_json(metadata, name=METADATA_NAME, parent_id=drive.root_folder_id)
            return {
                "status": "updated", "reference_date": day,
                "completed_stage": "menu2", "market_rows": market_rows,
                "delta_rows": self._rows(delta.manifest),
            }

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
                self._apply_cloud_deltas(drive, metadata, work, conn)
                before = self._latest_date(conn)
                target_ready = self._market_date_exists(conn, target_date)
                menu5_complete = self._menu5_complete(conn, target_date)

            commit = self._git_commit()
            checkpoints: list[dict[str, Any]] = []
            actual = before
            previous_stage = self._completed_stage_for(metadata, before)
            completed_stage = self._completed_stage_for(metadata, target_date)
            self._require_previous_date_completed(
                before, target_date, previous_stage, stage
            )

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
                        "completed_stage": self._completed_stage_for(
                            metadata, target_date
                        ),
                        "checkpoints": checkpoints,
                    }

            self._require_stage_base(target_ready, target_date, stage)
            day = target_date.isoformat()

            if stage in {"menu5", "remaining", "all"} and (
                not self._stage_completed(completed_stage, "menu5")
                or not menu5_complete
            ):
                metadata, menu5_checkpoints = self._run_menu5_checkpointed(
                    drive, metadata, work, conninfo, target_date, commit,
                    state_reference_date=actual,
                )
                checkpoints.extend(menu5_checkpoints)
                completed_stage = "menu5"
                if stage == "menu5":
                    return {
                        "status": "updated",
                        "reference_date": day,
                        "completed_stage": "menu5",
                        "delta_rows": menu5_checkpoints[-1]["delta_rows"],
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
                    drive, metadata, work, conninfo, target_date, commit, "menu7",
                    state_reference_date=actual,
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
            try:
                self._run("scripts/run_xing_db_menu.py", *arguments)
            except CloudArchiveError as exc:
                raise TransientSourceError("메뉴 7 공급원 호출이 2회 실패했습니다.") from exc

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
        return 3

    def _run_menu5_checkpointed(
        self,
        drive: GoogleDriveClient,
        metadata: dict[str, Any],
        work: Path,
        conninfo: str,
        target_date: date,
        commit: str,
        *,
        state_reference_date: date | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Run menu 5 in resumable batches and persist every valid batch."""
        day = target_date.isoformat()
        batch_size = max(1, int(os.environ.get("STOCK_DRIVE_MENU5_BATCH_SIZE", "100")))
        offset = (
            max(0, int(metadata.get("menu5_next_offset") or 0))
            if metadata.get("menu5_reference_date") == day
            else 0
        )
        checkpoints: list[dict[str, Any]] = []

        while True:
            for attempt in range(2):
                result = self._run(
                    "scripts/update_ls_investor_date_range.py",
                    "--start", day,
                    "--end", day,
                    "--chunk-days", "1",
                    "--max-tickers", str(batch_size),
                    "--ticker-offset", str(offset),
                    "--empty-is-complete",
                    accepted=(0, 3, 4),
                )
                if result != 3:
                    break
                metadata, checkpoint = self._publish_recovery_checkpoint(
                    drive, metadata, work, conninfo, target_date, commit,
                    next_offset=offset,
                )
                checkpoints.append(checkpoint)
                if attempt:
                    raise TransientSourceError(
                        f"메뉴 5 공급원 호출이 2회 실패했습니다: 재개 위치={offset}"
                    )
            if result == 4:
                break

            next_offset = offset + batch_size
            metadata, checkpoint = self._publish_recovery_checkpoint(
                drive, metadata, work, conninfo, target_date, commit,
                next_offset=next_offset,
            )
            checkpoints.append(checkpoint)
            offset = next_offset

        with self._connection(conninfo) as conn:
            if not self._menu5_complete(conn, target_date):
                raise CloudArchiveError(
                    f"메뉴 5 완료 검증 실패: 요청일 전체 종목이 완료되지 않았습니다: {day}"
                )

        metadata.pop("menu5_next_offset", None)
        metadata.pop("menu5_reference_date", None)
        metadata, checkpoint = self._publish_checkpoint(
            drive, metadata, work, conninfo, target_date, commit, "menu5",
            state_reference_date=state_reference_date,
        )
        checkpoints.append(checkpoint)
        return metadata, checkpoints

    def _publish_recovery_checkpoint(
        self,
        drive: GoogleDriveClient,
        metadata: dict[str, Any],
        work: Path,
        conninfo: str,
        reference_date: date,
        commit: str,
        *,
        next_offset: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Persist a small recoverable delta without rebuilding the full snapshot."""
        day = reference_date.isoformat()
        checkpoint_dir = work / f"menu5-partial-{next_offset:07d}"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        with self._connection(conninfo) as conn:
            delta = DatabaseArchiveService(conn, conninfo=conninfo).export_delta(
                checkpoint_dir / f"delta-{day}.tar.gz",
                target_date=reference_date,
                git_commit=commit,
            )

        delta_enc = checkpoint_dir / (
            f"delta-{day}-menu5-partial-{next_offset:07d}-{commit[:12]}.enc"
        )
        ArchiveCipher.encrypt(delta.path, delta_enc, self._context.credentials.archive_key)
        delta_id = drive.upload(
            delta_enc,
            name=delta_enc.name,
            parent_id=str(metadata["delta_folder_id"]),
        )
        deltas = [
            item for item in metadata.get("deltas", [])
            if item.get("reference_date") != day
        ]
        delta_record = self._delta_record(
            delta_id, delta_enc.name, delta_enc, delta.manifest
        )
        delta_record["completed_stage"] = "menu5-partial"
        delta_record["menu5_next_offset"] = next_offset
        deltas.append(delta_record)
        self._record_stage(metadata, reference_date, "menu5-partial")
        state_day = date.fromisoformat(str(metadata["state"]["reference_date"]))
        metadata.update(
            {
                "deltas": sorted(
                    deltas, key=lambda item: item["reference_date"]
                )[-400:],
                "completed_stage": self._completed_stage_for(metadata, state_day),
                "state_checkpoint_pending": "menu5-partial",
                "menu5_next_offset": next_offset,
                "menu5_reference_date": day,
            }
        )
        drive.write_json(metadata, name=METADATA_NAME, parent_id=drive.root_folder_id)
        return metadata, {
            "stage": "menu5-partial",
            "reference_date": day,
            "delta_rows": self._rows(delta.manifest),
            "next_offset": next_offset,
        }

    def _publish_checkpoint(
        self,
        drive: GoogleDriveClient,
        metadata: dict[str, Any],
        work: Path,
        conninfo: str,
        reference_date: date,
        commit: str,
        stage: str,
        *,
        state_reference_date: date | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Persist one completed menu before the next expensive menu starts."""
        day = reference_date.isoformat()
        checkpoint_dir = work / stage
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        # Publish the small daily delta first.  If pg_dump or the state upload
        # fails afterwards, the completed menu remains recoverable and the
        # next worker can rebuild from the previous state plus this delta.
        with self._connection(conninfo) as conn:
            delta = DatabaseArchiveService(conn, conninfo=conninfo).export_delta(
                checkpoint_dir / f"delta-{day}.tar.gz",
                target_date=reference_date,
                git_commit=commit,
            )

        delta_enc = checkpoint_dir / f"delta-{day}-{stage}-{commit[:12]}.enc"
        ArchiveCipher.encrypt(delta.path, delta_enc, self._context.credentials.archive_key)
        delta_id = drive.upload(
            delta_enc,
            name=delta_enc.name,
            parent_id=str(metadata["delta_folder_id"]),
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
        completed_stage = self._record_stage(metadata, reference_date, stage)
        state_day = state_reference_date or reference_date
        metadata.update(
            {
                "deltas": sorted(
                    deltas, key=lambda item: item["reference_date"]
                )[-400:],
                "completed_stage": self._completed_stage_for(metadata, state_day),
                "state_checkpoint_pending": completed_stage,
            }
        )
        drive.write_json(metadata, name=METADATA_NAME, parent_id=drive.root_folder_id)

        with self._connection(conninfo) as conn:
            state = DatabaseArchiveService(conn, conninfo=conninfo).export_snapshot(
                checkpoint_dir / "next-state.tar.gz",
                pg_dump=self._executable("pg_dump"),
                reference_date=state_reference_date or reference_date,
                git_commit=commit,
            )
        next_slot = "b" if metadata.get("state_slot") == "a" else "a"
        state_enc = checkpoint_dir / f"worker-state-{next_slot}.enc"
        ArchiveCipher.encrypt(state.path, state_enc, self._context.credentials.archive_key)
        state_id = drive.upload(
            state_enc,
            name=state_enc.name,
            parent_id=drive.ensure_folder("worker-state"),
        )
        metadata.update(
            {
                "state": self._state_record(
                    state_id, state_enc.name, state_enc, state.manifest
                ),
                "state_slot": next_slot,
            }
        )
        replay = set(metadata.get("replay_delta_dates") or [])
        replay.discard(day)
        if replay:
            metadata["replay_delta_dates"] = sorted(replay)
        else:
            metadata.pop("replay_delta_dates", None)
        metadata.pop("state_checkpoint_pending", None)
        drive.write_json(metadata, name=METADATA_NAME, parent_id=drive.root_folder_id)
        return metadata, {
            "stage": stage,
            "reference_date": day,
            "delta_rows": self._rows(delta.manifest),
        }

    def _apply_cloud_deltas(
        self,
        drive: GoogleDriveClient,
        metadata: dict[str, Any],
        work: Path,
        conn,
    ) -> None:
        """Rebuild state when a delta was saved before a state checkpoint failed."""
        state_reference = date.fromisoformat(str(metadata["state"]["reference_date"]))
        replay = set(metadata.get("replay_delta_dates") or [])
        delta_dir = work / "restore-deltas"
        delta_dir.mkdir(parents=True, exist_ok=True)
        applier = DeltaArchiveApplier(conn)
        for record in sorted(
            metadata.get("deltas", []), key=lambda item: item["reference_date"]
        ):
            record_day = str(record["reference_date"])
            if date.fromisoformat(record_day) < state_reference and record_day not in replay:
                continue
            encrypted = drive.download(
                str(record["id"]), delta_dir / str(record["name"])
            )
            self._verify_download(encrypted, record)
            archive = delta_dir / (encrypted.stem + ".tar.gz")
            ArchiveCipher.decrypt(
                encrypted, archive, self._context.credentials.archive_key
            )
            applier.apply(archive)

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
            if exit_code == 3:
                return {
                    "status": "provider-failed",
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

    @classmethod
    def _require_stage_base(
        cls, target_ready: bool, target_date: date, stage: str
    ) -> None:
        """Require the requested trading-day base before later-stage collection."""
        if not target_ready:
            raise CloudArchiveError(
                f"{stage} 실행 전 메뉴 2 기준일이 준비되지 않았습니다: 요청={target_date}"
            )

    @classmethod
    def _completed_stage_for(
        cls, metadata: dict[str, Any], reference_date: date | None
    ) -> str:
        if reference_date is None:
            return ""
        day = reference_date.isoformat()
        stage = str((metadata.get("stage_dates") or {}).get(day) or "")
        if stage:
            return stage
        state = metadata.get("state") or {}
        return (
            str(metadata.get("completed_stage") or "")
            if state.get("reference_date") == day
            else ""
        )

    @classmethod
    def _record_stage(
        cls, metadata: dict[str, Any], reference_date: date, stage: str
    ) -> str:
        stages = dict(metadata.get("stage_dates") or {})
        state = metadata.get("state") or {}
        state_day = state.get("reference_date")
        if state_day and state_day not in stages:
            stages[state_day] = str(metadata.get("completed_stage") or "")
        day = reference_date.isoformat()
        current = str(stages.get(day) or "")
        stages[day] = stage if not cls._stage_completed(current, stage) else current
        metadata["stage_dates"] = stages
        return stages[day]

    @staticmethod
    def _stage_completed(completed_stage: str, requested_stage: str) -> bool:
        order = {"": 0, "menu2": 1, "menu5-partial": 2, "menu5": 3, "menu7": 4}
        return order.get(completed_stage, 0) >= order[requested_stage]

    @staticmethod
    def _retention_cutoff(today: date | None = None) -> date:
        return (today or date.today()) - timedelta(days=30)

    def _acknowledge_and_cleanup(
        self, drive: GoogleDriveClient, metadata: dict[str, Any]
    ) -> list[str]:
        """Acknowledge local application and delete only deltas older than 30 days."""
        deltas = list(metadata.get("deltas", []))
        if not deltas:
            return []
        synced_through = max(str(item["reference_date"]) for item in deltas)
        cutoff = self._retention_cutoff().isoformat()
        expired = [
            item for item in deltas
            if str(item["reference_date"]) < cutoff
            and str(item["reference_date"]) <= synced_through
        ]
        expired_ids = {str(item["id"]) for item in expired}
        for item in drive.list_folder(str(metadata["delta_folder_id"])):
            match = re.match(r"delta-(\d{4}-\d{2}-\d{2})-", str(item.get("name", "")))
            if match and match.group(1) < cutoff and match.group(1) <= synced_through:
                expired_ids.add(str(item["id"]))
        for file_id in expired_ids:
            drive.delete(file_id)
        metadata["local_synced_through"] = synced_through
        metadata["deltas"] = [item for item in deltas if item not in expired]
        drive.write_json(metadata, name=METADATA_NAME, parent_id=drive.root_folder_id)
        return [str(item["reference_date"]) for item in expired]

    @staticmethod
    def _require_previous_date_completed(
        current_date: date | None,
        target_date: date,
        completed_stage: str,
        requested_stage: str,
    ) -> None:
        """Do not advance the cloud state while the prior date is incomplete."""
        if (
            requested_stage in {"menu2", "all"}
            and current_date is not None
            and current_date < target_date
            and completed_stage != "menu7"
        ):
            raise CloudArchiveError(
                "이전 기준일 작업이 완료되지 않아 다음 날짜를 시작할 수 없습니다: "
                f"이전={current_date.isoformat()}, 완료단계={completed_stage or '없음'}, "
                f"요청={target_date.isoformat()}"
            )

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
    def _menu5_complete(conn, target_date: date) -> bool:
        row = conn.execute(
            """WITH target AS (
                   SELECT DISTINCT ticker::text AS stock_code
                   FROM market.ohlcv_daily WHERE trade_date::date=%s)
               SELECT count(*) AS targets, count(done.stock_code) AS completed
               FROM target LEFT JOIN market_core.ls_investor_t1702_checkpoint done
                 ON done.stock_code=target.stock_code
                AND done.trade_date=%s AND done.exchange_code='K'""",
            (target_date, target_date),
        ).fetchone()
        return bool(row and row["targets"] and row["targets"] == row["completed"])

    @staticmethod
    def _market_date_exists(conn, target_date: date) -> bool:
        row = conn.execute(
            "SELECT EXISTS(SELECT 1 FROM market.ohlcv_daily WHERE trade_date::date=%s) AS found",
            (target_date,),
        ).fetchone()
        return bool(row and row["found"])

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
            "state_checkpoint_pending": metadata.get("state_checkpoint_pending"),
            "menu5_next_offset": metadata.get("menu5_next_offset"),
            "menu5_reference_date": metadata.get("menu5_reference_date"),
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
