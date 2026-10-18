from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from krx_research.cloud_sync.drive import GoogleDriveClient

from .models import FinancialPeriod


class FinancialDriveCleanupService:
    """Deletes only locally verified financial archives and checkpoints each deletion."""

    def __init__(
        self,
        drive: GoogleDriveClient,
        save: Callable[[dict[str, Any]], None],
    ) -> None:
        self._drive = drive
        self._save = save

    def cleanup(
        self,
        metadata: dict[str, Any],
        year: int,
        periods: Iterable[FinancialPeriod],
    ) -> list[str]:
        state = (metadata.get("years") or {}).get(str(year)) or {}
        period_states = state.get("periods") or {}
        selected = list(periods)
        targets = [period_states.get(period.label) or {} for period in selected]
        records = [record for target in targets for record in target.get("batches", [])]
        if not targets or any(
            not target.get("cloud_completed")
            or not target.get("local_completed")
            or not target.get("batches")
            or any(not record.get("local_applied") for record in target["batches"])
            or int(target.get("facts") or 0) <= 0
            or int(target.get("local_verified_facts") or 0) != int(target.get("facts") or 0)
            for target in targets
        ):
            labels = ", ".join(period.label for period in selected)
            raise RuntimeError(
                f"{year}년 {labels} 로컬 완전 반영이 검증되지 않아 Drive를 정리할 수 없습니다."
            )
        deleted = []
        for record in records:
            if record.get("drive_deleted"):
                continue
            file_id = str(record.get("id") or "")
            if not file_id:
                raise RuntimeError("Drive 정리 대상의 파일 ID가 없습니다.")
            self._drive.delete(file_id)
            deleted.append(str(record.get("name") or file_id))
            record["drive_deleted"] = True
            record.pop("id", None)
            record.pop("sha256", None)
            self._save(metadata)
        for target in targets:
            target["drive_cleaned"] = True
        all_periods = list(period_states.values())
        state["drive_cleaned"] = bool(all_periods) and all(
            target.get("drive_cleaned") for target in all_periods
        )
        self._save(metadata)
        return deleted
