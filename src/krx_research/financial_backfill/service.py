from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from krx_research.cloud_sync.archive import ArchiveCipher
from krx_research.cloud_sync.drive import GoogleDriveClient

from .client import OpenDartClient
from .cleanup import FinancialDriveCleanupService
from .models import FinancialBatch, FinancialPeriod
from .policy import FinancialBackfillPolicy
from .repository import open_financial_repository
from .staging import DuckDbFinancialStagingRepository


METADATA_NAME = "financial-backfill.json"
DEFAULT_YEARS = (2026, 2025, 2024, 2023)


@dataclass(frozen=True, slots=True)
class FinancialBackfillContext:
    root: Path
    drive: GoogleDriveClient
    archive_key: str


class FinancialBackfillService:
    """Coordinates period checkpoints; collection and DB writes stay in collaborators."""

    def __init__(
        self,
        context: FinancialBackfillContext,
        client: OpenDartClient | None,
        *,
        staging: DuckDbFinancialStagingRepository | None = None,
    ) -> None:
        self._context = context
        self._client = client
        self._staging = staging or DuckDbFinancialStagingRepository()

    def cloud_collect(
        self,
        year: int,
        *,
        years: tuple[int, ...] = DEFAULT_YEARS,
        batch_size: int = 100,
        max_batches: int = 0,
    ) -> dict[str, Any]:
        FinancialBackfillPolicy.validate_year(year)
        if self._client is None:
            raise RuntimeError("클라우드 수집에는 OpenDART 클라이언트가 필요합니다.")
        ordered_years = list(dict.fromkeys(years))
        if year not in ordered_years or ordered_years != sorted(ordered_years, reverse=True):
            raise ValueError("사업연도는 최신 연도부터 내림차순으로 지정해야 합니다.")
        metadata = self._metadata(ordered_years)
        year_state = (metadata["years"]).setdefault(str(year), {"periods": {}})
        targets = self._target_periods(year_state, year)
        period = FinancialBackfillPolicy.next_period(year_state, targets)
        if period is None:
            return {
                "status": "awaiting-local" if not year_state.get("local_completed") else "complete",
                "year": year,
            }
        return self._collect_period(
            metadata, year, period, batch_size=max(1, batch_size), max_batches=max_batches
        )

    def cloud_collect_next(
        self,
        *,
        years: tuple[int, ...] = DEFAULT_YEARS,
        batch_size: int = 100,
        max_batches: int = 0,
    ) -> dict[str, Any]:
        metadata = self._metadata(list(years))
        if metadata.get("restore_deleted_requested"):
            return self._restore_next_deleted(
                metadata, years=years, batch_size=batch_size, max_batches=max_batches
            )
        for year in years:
            state = (metadata.get("years") or {}).get(str(year), {})
            targets = self._target_periods(state, year)
            if FinancialBackfillPolicy.next_period(state, targets) is not None:
                return self.cloud_collect(
                    year,
                    years=years,
                    batch_size=batch_size,
                    max_batches=max_batches,
                )
        return {"status": "complete", "years": list(years)}

    def request_drive_restore(
        self,
        targets: tuple[tuple[int, FinancialPeriod], ...],
        *,
        years: tuple[int, ...] = DEFAULT_YEARS,
    ) -> dict[str, Any]:
        """Queue reconstruction of verified archives that were removed from Drive."""
        metadata = self._metadata(list(years))
        labels = []
        for year, period in targets:
            if year not in years:
                raise ValueError(f"복구 대상 연도가 요청 범위에 없습니다: {year}")
            state = (
                ((metadata.get("years") or {}).get(str(year), {}).get("periods") or {})
                .get(period.label, {})
            )
            if not (state.get("drive_cleaned") or state.get("restore_in_progress")):
                raise RuntimeError(
                    f"삭제가 확인된 재무자료만 복구할 수 있습니다: {year}:{period.label}"
                )
            labels.append(f"{year}:{period.label}")
        metadata["restore_deleted_requested"] = True
        metadata["restore_deleted_targets"] = labels
        self._write_metadata(metadata)
        return {"status": "restore-requested", "periods": labels}

    def sync_local(
        self,
        year: int,
        *,
        years: tuple[int, ...] = DEFAULT_YEARS,
        cleanup_confirmed: bool = False,
    ) -> dict[str, Any]:
        metadata = self._metadata(list(years))
        year_state = (metadata.get("years") or {}).get(str(year)) or {}
        periods = year_state.get("periods") or {}
        targets = self._stored_targets(year_state)
        active = next(
            (
                period for period in targets
                if periods.get(period.label, {}).get("batches")
                and not periods.get(period.label, {}).get("cloud_completed")
            ),
            None,
        )
        if active is not None:
            return {"status": "awaiting-cloud", "year": year, "period": active.label}
        applied: list[str] = []
        with open_financial_repository() as repository, tempfile.TemporaryDirectory(
            prefix="stock-financial-local-"
        ) as temporary_name:
            repository.initialize_schema()
            period = next(
                (
                    candidate for candidate in targets
                    if periods.get(candidate.label, {}).get("cloud_completed")
                    and repository.period_fact_count(year, candidate)
                    != int(periods.get(candidate.label, {}).get("facts") or 0)
                ),
                None,
            )
            if period is None:
                return {"status": "up-to-date", "year": year}
            work = Path(temporary_name)
            state = periods[period.label]
            for record in state.get("batches", []):
                if record.get("drive_deleted") or not record.get("id"):
                    raise RuntimeError(
                        f"Drive 재무자료 복구가 필요합니다: {year} {period.label}"
                    )
                encrypted = self._context.drive.download(
                    str(record["id"]), work / str(record["name"])
                )
                if self._sha256(encrypted) != record.get("sha256"):
                    raise RuntimeError(f"Drive 다운로드 해시 불일치: {record['name']}")
                archive = work / f"{record['batch_id']}.tar.gz"
                ArchiveCipher.decrypt(encrypted, archive, self._context.archive_key)
                result = repository.apply_archive(archive)
                record["local_applied"] = True
                applied.append(str(result["batch_id"]))
                self._write_metadata(metadata)
            expected_facts = int(state.get("facts") or 0)
            actual_facts = repository.period_fact_count(year, period)
            if not expected_facts or actual_facts != expected_facts:
                raise RuntimeError(
                    f"{year}년 {period.label} 로컬 재무자료 검증 실패: "
                    f"기대={expected_facts}, 실제={actual_facts}"
                )
        state.update(local_completed=True, local_verified_facts=actual_facts)
        self._write_metadata(metadata)
        deleted = (
            FinancialDriveCleanupService(
                self._context.drive, self._write_metadata
            ).cleanup(metadata, year, (period,), confirmed=True)
            if cleanup_confirmed
            else []
        )
        year_state["local_completed"] = all(
            periods.get(candidate.label, {}).get("local_completed") for candidate in targets
        )
        year_state["drive_cleaned"] = all(
            periods.get(candidate.label, {}).get("drive_cleaned") for candidate in targets
        )
        year_state["local_verified_facts"] = sum(
            int(periods.get(candidate.label, {}).get("local_verified_facts") or 0)
            for candidate in targets
        )
        self._write_metadata(metadata)
        return {
            "status": "complete-period", "year": year, "period": period.label,
            "applied_batches": applied, "deleted_drive_files": deleted,
        }

    def sync_ready_local(
        self,
        *,
        years: tuple[int, ...] = DEFAULT_YEARS,
        cleanup_confirmed: bool = False,
    ) -> dict[str, Any]:
        """Apply the first cloud-complete year, otherwise leave local data untouched."""
        metadata = self._read_metadata(list(years))
        if metadata is None:
            return {"status": "awaiting-cloud", "years": list(years)}
        for year in years:
            result = self.sync_local(
                year, years=years, cleanup_confirmed=cleanup_confirmed
            )
            if result["status"] != "up-to-date":
                return result
        return {"status": "up-to-date", "years": list(years)}

    def status(self, years: tuple[int, ...] = DEFAULT_YEARS) -> dict[str, Any]:
        return self._metadata(list(years))

    def _collect_period(
        self,
        metadata: dict[str, Any],
        year: int,
        period: FinancialPeriod,
        *,
        batch_size: int,
        max_batches: int,
    ) -> dict[str, Any]:
        if self._client is None:
            raise RuntimeError("클라우드 수집에는 OpenDART 클라이언트가 필요합니다.")
        companies = self._client.listed_companies()
        year_state = metadata["years"][str(year)]
        state = year_state["periods"].setdefault(
            period.label, {"next_offset": 0, "facts": 0, "batches": []}
        )
        catalog_hash = hashlib.sha256(
            "\n".join(company.corp_code for company in companies).encode("ascii")
        ).hexdigest()
        previous_hash = state.get("company_catalog_sha256")
        if previous_hash and previous_hash != catalog_hash:
            raise RuntimeError(
                "수집 도중 OpenDART 회사 목록이 변경되었습니다. 기존 체크포인트를 보존한 "
                "상태에서 명시적 목록 재검증이 필요합니다."
            )
        state["company_catalog_sha256"] = catalog_hash
        offset = int(state.get("next_offset") or 0)
        processed = 0
        folder = self._period_folder(year, period)
        with open_financial_repository() as repository, tempfile.TemporaryDirectory(
            prefix="stock-financial-cloud-"
        ) as temporary_name:
            repository.initialize_schema()
            work = Path(temporary_name)
            while offset < len(companies) and (not max_batches or processed < max_batches):
                selected = companies[offset : offset + batch_size]
                raw_rows = []
                for company in selected:
                    for scope in ("CFS", "OFS"):
                        rows = self._client.statements(company.corp_code, year, period, scope)
                        for row in rows:
                            row["_scope"] = scope
                        raw_rows.extend(rows)
                facts = self._staging.normalize(raw_rows, year=year, period=period)
                counts = repository.replace_staging_batch(
                    FinancialBatch(tuple(selected), facts), year=year, period=period
                )
                batch_id = f"financial-{year}-{period.label}-{offset:06d}"
                archive = repository.export_delta(
                    work / f"{batch_id}.tar.gz",
                    target_date=period.period_end(year),
                    git_commit=self._git_commit(),
                    batch_id=batch_id,
                )
                if sum(int(item["rows"]) for item in archive.manifest["tables"]) <= 0:
                    raise RuntimeError("0건인 재무 배치를 완료 처리할 수 없습니다.")
                encrypted = work / f"{batch_id}.enc"
                ArchiveCipher.encrypt(archive.path, encrypted, self._context.archive_key)
                file_id = self._context.drive.upload(
                    encrypted, name=encrypted.name, parent_id=folder
                )
                record = {
                    "id": file_id,
                    "name": encrypted.name,
                    "sha256": self._sha256(encrypted),
                    "batch_id": batch_id,
                    "offset": offset,
                    "companies": counts["companies"],
                    "facts": counts["facts"],
                    "local_applied": False,
                }
                state["batches"] = [
                    item for item in state["batches"] if item.get("batch_id") != batch_id
                ] + [record]
                offset += len(selected)
                state["next_offset"] = offset
                state["facts"] = sum(int(item["facts"]) for item in state["batches"])
                state["companies"] = len(companies)
                self._write_metadata(metadata)
                processed += 1
                archive.path.unlink(missing_ok=True)
                encrypted.unlink(missing_ok=True)
        if offset >= len(companies):
            if int(state.get("facts") or 0) <= 0:
                raise RuntimeError(f"{year} {period.label} 전체 재무자료가 0건입니다.")
            completed_companies = sum(
                int(item.get("companies") or 0) for item in state["batches"]
            )
            if completed_companies != len(companies):
                raise RuntimeError(
                    f"{year} {period.label} 회사 완료 검증 실패: "
                    f"기대={len(companies)}, 실제={completed_companies}"
                )
            state["cloud_completed"] = True
            self._write_metadata(metadata)
        return {
            "status": "complete" if state.get("cloud_completed") else "partial",
            "year": year,
            "period": period.label,
            "next_offset": offset,
            "companies": len(companies),
            "facts": state["facts"],
        }

    def _restore_next_deleted(
        self,
        metadata: dict[str, Any],
        *,
        years: tuple[int, ...],
        batch_size: int,
        max_batches: int,
    ) -> dict[str, Any]:
        requested = set(metadata.get("restore_deleted_targets") or [])
        for year in years:
            year_state = (metadata.get("years") or {}).get(str(year), {})
            for period in self._stored_targets(year_state):
                if f"{year}:{period.label}" not in requested:
                    continue
                state = (year_state.get("periods") or {}).get(period.label, {})
                if not (state.get("drive_cleaned") or state.get("restore_in_progress")):
                    continue
                if not state.get("restore_in_progress"):
                    state["deleted_batch_audit"] = [
                        {
                            key: record.get(key)
                            for key in ("batch_id", "offset", "companies", "facts")
                        }
                        for record in state.get("batches", [])
                    ]
                    state.update(
                        batches=[], facts=0, next_offset=0, cloud_completed=False,
                        drive_cleaned=False, restore_in_progress=True,
                    )
                    self._write_metadata(metadata)
                result = self._collect_period(
                    metadata, year, period,
                    batch_size=batch_size, max_batches=max_batches,
                )
                if result["status"] == "complete":
                    state["restore_in_progress"] = False
                    state["restored_for_multi_device"] = True
                    self._write_metadata(metadata)
                result["restore_deleted"] = True
                return result
        metadata["restore_deleted_requested"] = False
        metadata["restore_deleted_targets"] = []
        self._write_metadata(metadata)
        return {"status": "restore-complete", "years": list(years)}

    def _period_folder(self, year: int, period: FinancialPeriod) -> str:
        root = self._context.drive.ensure_folder("financial-backfill")
        year_folder = self._context.drive.ensure_folder(str(year), root)
        return self._context.drive.ensure_folder(period.label, year_folder)

    def _target_periods(
        self, year_state: dict[str, Any], year: int
    ) -> tuple[FinancialPeriod, ...]:
        targets = FinancialBackfillPolicy.available_periods(year)
        if not targets:
            raise RuntimeError(f"{year}년은 아직 수집 가능한 정기보고서가 없습니다.")
        labels = [period.label for period in targets]
        previous = list(year_state.get("target_periods") or [])
        if previous and labels[:len(previous)] != previous:
            raise RuntimeError(f"{year}년 수집 대상 기간 순서가 기존 체크포인트와 다릅니다.")
        if labels != previous:
            year_state["target_periods"] = labels
            year_state["local_completed"] = False
        return targets

    @staticmethod
    def _stored_targets(year_state: dict[str, Any]) -> tuple[FinancialPeriod, ...]:
        labels = year_state.get("target_periods") or [period.label for period in FinancialPeriod]
        return tuple(FinancialPeriod.parse(label) for label in labels)

    def _metadata(self, years: list[int]) -> dict[str, Any]:
        document = self._read_metadata(years)
        if document is None:
            document = {"format_version": 1, "year_order": years, "years": {}}
            self._write_metadata(document)
        return document

    def _read_metadata(self, years: list[int]) -> dict[str, Any] | None:
        document = self._context.drive.read_json(
            METADATA_NAME, self._context.drive.root_folder_id
        )
        if document is None:
            return None
        if document.get("format_version") != 1:
            raise RuntimeError("지원하지 않는 재무 백필 메타데이터 버전입니다.")
        stored = list(document.get("year_order") or [])
        merged = FinancialBackfillPolicy.extend_year_order(stored, years)
        if merged != stored:
            document["year_order"] = merged
            self._write_metadata(document)
        return document

    def _write_metadata(self, metadata: dict[str, Any]) -> None:
        self._context.drive.write_json(
            metadata, name=METADATA_NAME, parent_id=self._context.drive.root_folder_id
        )

    def _git_commit(self) -> str:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self._context.root,
            text=True, capture_output=True, check=False,
        )
        value = completed.stdout.strip()
        return value if completed.returncode == 0 and len(value) == 40 else "unknown"

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
