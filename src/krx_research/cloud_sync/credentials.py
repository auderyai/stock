from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from krx_research.infrastructure.windows_dpapi_store import WindowsDpapiJsonStore

from .archive import ArchiveCipher, CloudArchiveError


@dataclass(frozen=True, slots=True)
class DriveCredentials:
    client_id: str
    client_secret: str
    refresh_token: str
    root_folder_id: str
    archive_key: str

    @classmethod
    def from_environment(cls) -> "DriveCredentials":
        return cls._validated(
            os.getenv("GOOGLE_CLIENT_ID", ""),
            os.getenv("GOOGLE_CLIENT_SECRET", ""),
            os.getenv("GOOGLE_REFRESH_TOKEN", ""),
            os.getenv("GOOGLE_DRIVE_FOLDER_ID", ""),
            os.getenv("DRIVE_ARCHIVE_KEY", ""),
        )

    @classmethod
    def from_windows_store(cls, path: Path, *, create_archive_key: bool = True) -> "DriveCredentials":
        store = WindowsDpapiJsonStore(path)
        document = store.load()
        key = str(document.get("archive_key") or "").strip()
        if not key and create_archive_key:
            key = ArchiveCipher.generate_key()
            document["archive_key"] = key
            store.save(document)
        return cls._validated(
            document.get("client_id", ""),
            document.get("client_secret", ""),
            document.get("refresh_token", ""),
            document.get("root_folder_id", ""),
            key,
        )

    @classmethod
    def _validated(cls, *values: object) -> "DriveCredentials":
        normalized = tuple(str(value).strip() for value in values)
        if any(not value for value in normalized):
            raise CloudArchiveError("Google Drive 동기화 자격증명이 완전하지 않습니다.")
        ArchiveCipher._decode_key(normalized[4])
        return cls(*normalized)
