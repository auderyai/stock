"""Safe, deterministic paths for the local KRX research archive."""

from __future__ import annotations

import datetime as dt
import os
import hashlib
import re
import unicodedata
from pathlib import Path

from krx_research.collectors.market_data import normalize_ticker

INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WHITESPACE = re.compile(r"\s+")
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class ArchivePathError(ValueError):
    """Raised when an archive path or segment is unsafe."""


def safe_segment(value: object, *, max_length: int = 80) -> str:
    """Return a Windows-safe, readable path segment without traversal tokens."""

    if max_length < 8:
        raise ValueError("max_length must be at least 8")
    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = INVALID_WINDOWS_CHARS.sub("_", text)
    text = WHITESPACE.sub("_", text)
    text = re.sub(r"_+", "_", text).strip(" ._")
    if not text or text in {".", ".."}:
        raise ArchivePathError(f"Unsafe empty path segment: {value!r}")
    stem = text.split(".", maxsplit=1)[0].upper()
    if stem in WINDOWS_RESERVED_NAMES:
        text = f"_{text}"
    return text[:max_length].rstrip(" ._")


class ArchiveLayout:
    """Resolve canonical archive and output locations under the C:\\stock project root."""

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        configured = os.environ.get("KRX_SHARED_STORAGE_ROOT", "").strip()
        self.storage_root = (Path(configured).expanduser().resolve() if configured else self.project_root)
        if os.name == "nt" and self.storage_root != self.project_root:
            raise ArchivePathError("KRX_SHARED_STORAGE_ROOT는 C:\\stock 프로젝트 루트와 동일해야 합니다.")

    @property
    def database_path(self) -> Path:
        raise ArchivePathError("Stock은 파일 DB를 사용하지 않습니다. C:\\stock\\.env의 PostgreSQL 설정을 사용하십시오.")

    @property
    def index_root(self) -> Path:
        return self.storage_root / "90_공통관리" / "INDEX"

    @property
    def log_root(self) -> Path:
        """Keep new_stock runtime logs inside the new_stock project."""
        return self.project_root / "logs"

    @property
    def backup_root(self) -> Path:
        return self.storage_root / "90_공통관리" / "BACKUP"

    def daily_screen_root(self, as_of_date: dt.date) -> Path:
        """Return the dated directory for generated market-screen CSV files."""

        if not isinstance(as_of_date, dt.date):
            raise TypeError("as_of_date must be a date")
        return self.storage_root / "02_매일" / as_of_date.isoformat() / "SCREENS"

    def research_source_path(
        self, source: str | Path, report_date: dt.date, *, ticker: object | None = None,
        company_name: object | None = None, title: object | None = None,
    ) -> Path:
        """Return a canonical, immutable location for an imported research source."""

        path = Path(source)
        suffix = path.suffix.lower()
        if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}:
            raise ArchivePathError(f"지원하지 않는 연구자료 형식: {suffix}")
        if suffix == ".pdf" and ticker and company_name:
            return self.company_report_path(
                ticker, company_name, report_date, title or path.stem, suffix=suffix
            )
        digest = self.file_sha256(path)[:12]
        return (
            self.storage_root / "02_매일" / report_date.isoformat() / "SOURCES"
            / f"{digest}_{safe_segment(path.stem)}{suffix}"
        )

    def ensure(self) -> None:
        """Create the approved local archive directories if they are missing."""

        directories = (
            "00_INBOX",
            "01_기업분석",
            "02_매일",
            "03_주간",
            "04_월간",
            "05_분야별",
            "90_공통관리/DATABASE",
            "90_공통관리/INDEX",
            "90_공통관리/LOGS",
            "90_공통관리/BACKUP",
        )
        for relative in directories:
            (self.storage_root / relative).mkdir(parents=True, exist_ok=True)

    def company_report_path(
        self,
        ticker: object,
        company_name: object,
        report_date: dt.date,
        title: object,
        *,
        suffix: str = ".md",
    ) -> Path:
        """Return the canonical location for one dated company report."""

        code = normalize_ticker(ticker)
        if not isinstance(report_date, dt.date):
            raise TypeError("report_date must be a date")
        extension = suffix if suffix.startswith(".") else f".{suffix}"
        if not re.fullmatch(r"\.[A-Za-z0-9]{1,8}", extension):
            raise ArchivePathError(f"Unsafe file extension: {suffix!r}")
        company_directory = f"{code}_{safe_segment(company_name)}"
        filename = f"{report_date.isoformat()}_{safe_segment(title)}{extension.lower()}"
        return (
            self.storage_root
            / "01_기업분석"
            / company_directory
            / str(report_date.year)
            / filename
        )

    def relative_path(self, path: str | Path) -> str:
        """Return a stable POSIX-style path relative to the C:\\stock storage root."""

        resolved = Path(path).expanduser().resolve()
        try:
            relative = resolved.relative_to(self.storage_root)
        except ValueError as error:
            raise ArchivePathError(f"Path is outside C:\\stock: {resolved}") from error
        return relative.as_posix()

    @staticmethod
    def file_sha256(path: str | Path) -> str:
        """Calculate a file checksum without loading the whole file into memory."""

        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def period_view_keys(report_date: dt.date) -> dict[str, str]:
        """Return daily, ISO-weekly, and monthly keys for a report date."""

        iso_year, iso_week, _ = report_date.isocalendar()
        return {
            "daily": report_date.isoformat(),
            "weekly": f"{iso_year}-W{iso_week:02d}",
            "monthly": report_date.strftime("%Y-%m"),
        }
