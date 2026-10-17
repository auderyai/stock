from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import subprocess
import tempfile
from typing import Any

import psycopg
from psycopg.rows import dict_row

from krx_research.cloud_sync.archive import ArchiveCipher, DatabaseArchiveService
from krx_research.cloud_sync.drive import GoogleDriveClient
from krx_research.cloud_sync.models import FINANCIAL_TABLES
from krx_research.data_engine.config import database_conninfo

from .client import OpenDartClient
from .models import FinancialBatch, FinancialPeriod
from .policy import FinancialBackfillPolicy
from .repository import FinancialRepository
from .staging import DuckDbFinancialStagingRepository


METADATA_NAME = "financial-backfill.json"


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
        years: tuple[int, ...] = (2025, 2024, 2023),
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
        FinancialBackfillPolicy.require_previous_local_completion(
            ordered_years, metadata, year
        )
        year_state = (metadata["years"]).setdefault(str(year), {"periods": {}})
        period = FinancialBackfillPolicy.next_period(year_state)
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
        years: tuple[int, ...] = (2025, 2024, 2023),
        batch_size: int = 100,
        max_batches: int = 0,
    ) -> dict[str, Any]:
        metadata = self._metadata(list(years))
        for index, year in enumerate(years):
            state = (metadata.get("years") or {}).get(str(year), {})
            if index and not (
                (metadata.get("years") or {}).get(str(years[index - 1]), {}).get(
                    "local_completed"
                )
            ):
                return {"status": "awaiting-local", "year": years[index - 1]}
            if FinancialBackfillPolicy.next_period(state) is not None:
                return self.cloud_collect(
                    year,
                    years=years,
                    batch_size=batch_size,
                    max_batches=max_batches,
                )
            if not state.get("local_completed"):
                return {"status": "awaiting-local", "year": year}
        return {"status": "complete", "years": list(years)}

    def sync_local(
        self, year: int, *, years: tuple[int, ...] = (2025, 2024, 2023)
    ) -> dict[str, Any]:
        metadata = self._metadata(list(years))
        year_state = (metadata.get("years") or {}).get(str(year)) or {}
        periods = year_state.get("periods") or {}
        if any(
            not periods.get(period.label, {}).get("cloud_completed")
            for period in FinancialPeriod
        ):
            raise RuntimeError(f"{year}년 클라우드 4개 보고서가 아직 완료되지 않았습니다.")
        applied: list[str] = []
        with self._connection() as connection, tempfile.TemporaryDirectory(
            prefix="stock-financial-local-"
        ) as temporary_name:
            repository = FinancialRepository(connection)
            repository.initialize_schema()
            work = Path(temporary_name)
            for period in FinancialPeriod:
                state = periods[period.label]
                for record in state.get("batches", []):
                    if record.get("local_applied"):
                        continue
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
            expected_facts = sum(
                int(periods[period.label].get("facts") or 0)
                for period in FinancialPeriod
            )
            actual_facts = repository.year_fact_count(year)
            if not expected_facts or actual_facts < expected_facts:
                raise RuntimeError(
                    f"{year}년 로컬 재무자료 검증 실패: "
                    f"기대={expected_facts}, 실제={actual_facts}"
                )
        year_state["local_completed"] = True
        self._write_metadata(metadata)
        return {"status": "complete", "year": year, "applied_batches": applied}

    def sync_ready_local(
        self, *, years: tuple[int, ...] = (2025, 2024, 2023)
    ) -> dict[str, Any]:
        """Apply the first cloud-complete year, otherwise leave local data untouched."""
        metadata = self._read_metadata(list(years))
        if metadata is None:
            return {"status": "awaiting-cloud", "years": list(years)}
        for year in years:
            state = (metadata.get("years") or {}).get(str(year), {})
            if state.get("local_completed"):
                continue
            periods = state.get("periods") or {}
            if all(
                periods.get(period.label, {}).get("cloud_completed")
                for period in FinancialPeriod
            ):
                return self.sync_local(year, years=years)
            return {"status": "awaiting-cloud", "year": year}
        return {"status": "up-to-date", "years": list(years)}

    def status(self, years: tuple[int, ...] = (2025, 2024, 2023)) -> dict[str, Any]:
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
        with self._connection() as connection, tempfile.TemporaryDirectory(
            prefix="stock-financial-cloud-"
        ) as temporary_name:
            repository = FinancialRepository(connection)
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
                archive = DatabaseArchiveService(
                    connection, FINANCIAL_TABLES
                ).export_delta(
                    work / f"{batch_id}.tar.gz",
                    target_date=period.period_end(year),
                    git_commit=self._git_commit(),
                    kind="financial-delta",
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

    def _period_folder(self, year: int, period: FinancialPeriod) -> str:
        root = self._context.drive.ensure_folder("financial-backfill")
        year_folder = self._context.drive.ensure_folder(str(year), root)
        return self._context.drive.ensure_folder(period.label, year_folder)

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
        if list(document.get("year_order") or []) != years:
            raise RuntimeError("기존 재무 백필 사업연도 순서와 요청이 다릅니다.")
        return document

    def _write_metadata(self, metadata: dict[str, Any]) -> None:
        self._context.drive.write_json(
            metadata, name=METADATA_NAME, parent_id=self._context.drive.root_folder_id
        )

    @staticmethod
    def _connection():
        return psycopg.connect(database_conninfo(), row_factory=dict_row)

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
