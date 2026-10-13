from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import base64
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from typing import Any, Iterator

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from .models import ARCHIVE_FORMAT_VERSION, TableSpec, WORKER_TABLES


ARCHIVE_MAGIC = b"STOCKDRIVE1\n"


class CloudArchiveError(RuntimeError):
    pass


class ArchiveCipher:
    """Authenticated archive encryption; keys are supplied outside Git and Drive."""

    @staticmethod
    def generate_key() -> str:
        return base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)).decode("ascii")

    @staticmethod
    def encrypt(source: Path, target: Path, encoded_key: str) -> None:
        key = ArchiveCipher._decode_key(encoded_key)
        nonce = os.urandom(12)
        ciphertext = AESGCM(key).encrypt(nonce, source.read_bytes(), ARCHIVE_MAGIC)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(ARCHIVE_MAGIC + nonce + ciphertext)
        os.replace(temporary, target)

    @staticmethod
    def decrypt(source: Path, target: Path, encoded_key: str) -> None:
        payload = source.read_bytes()
        if not payload.startswith(ARCHIVE_MAGIC) or len(payload) < len(ARCHIVE_MAGIC) + 29:
            raise CloudArchiveError("암호화된 Stock Drive 아카이브 형식이 아닙니다.")
        offset = len(ARCHIVE_MAGIC)
        nonce, ciphertext = payload[offset : offset + 12], payload[offset + 12 :]
        try:
            clear = AESGCM(ArchiveCipher._decode_key(encoded_key)).decrypt(
                nonce, ciphertext, ARCHIVE_MAGIC
            )
        except Exception as exc:
            raise CloudArchiveError("아카이브 인증 또는 복호화에 실패했습니다.") from exc
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(clear)
        os.replace(temporary, target)

    @staticmethod
    def _decode_key(encoded_key: str) -> bytes:
        try:
            key = base64.urlsafe_b64decode(encoded_key.encode("ascii"))
        except Exception as exc:
            raise CloudArchiveError("아카이브 암호화 키 형식이 잘못되었습니다.") from exc
        if len(key) != 32:
            raise CloudArchiveError("아카이브 암호화 키는 256비트여야 합니다.")
        return key


@dataclass(frozen=True, slots=True)
class ArchiveResult:
    path: Path
    manifest: dict[str, Any]


class DatabaseArchiveService:
    def __init__(
        self,
        conn,
        tables: tuple[TableSpec, ...] = WORKER_TABLES,
        *,
        conninfo: str | None = None,
    ) -> None:
        self._conn = conn
        self._tables = tables
        self._conninfo = conninfo

    def export_snapshot(
        self,
        output: Path,
        *,
        pg_dump: Path,
        reference_date: date | None = None,
        git_commit: str = "unknown",
    ) -> ArchiveResult:
        selected = reference_date or self._latest_market_date()
        return self._export(
            output,
            kind="worker-state",
            reference_date=selected,
            pg_dump=pg_dump,
            git_commit=git_commit,
        )

    def export_delta(
        self,
        output: Path,
        *,
        target_date: date,
        git_commit: str = "unknown",
    ) -> ArchiveResult:
        return self._export(
            output,
            kind="daily-delta",
            reference_date=target_date,
            pg_dump=None,
            git_commit=git_commit,
        )

    def _export(
        self,
        output: Path,
        *,
        kind: str,
        reference_date: date,
        pg_dump: Path | None,
        git_commit: str,
    ) -> ArchiveResult:
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="stock-drive-export-") as temporary_name:
            temporary = Path(temporary_name)
            if pg_dump is not None:
                self._dump_schema(pg_dump, temporary / "schema.sql")
            table_items: list[dict[str, Any]] = []
            for spec in self._tables:
                if not self._relation_exists(spec):
                    continue
                columns = self._columns(spec)
                data_file = temporary / f"{spec.schema}__{spec.table}.csv"
                row_count = self._copy_out(spec, columns, data_file, kind, reference_date)
                table_items.append(
                    {
                        "relation": spec.relation,
                        "columns": columns,
                        "key_columns": list(spec.key_columns),
                        "file": data_file.name,
                        "rows": row_count,
                        "sha256": _sha256(data_file),
                    }
                )
            created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            batch_id = f"{reference_date.isoformat()}-{created.replace(':', '').replace('+00:00', 'Z')}"
            manifest: dict[str, Any] = {
                "format_version": ARCHIVE_FORMAT_VERSION,
                "kind": kind,
                "batch_id": batch_id,
                "reference_date": reference_date.isoformat(),
                "created_at": created,
                "git_commit": git_commit,
                "tables": table_items,
            }
            (temporary / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary_output = output.with_suffix(output.suffix + ".tmp")
            with tarfile.open(temporary_output, "w:gz") as archive:
                for path in sorted(temporary.iterdir(), key=lambda item: item.name):
                    archive.add(path, arcname=path.name, recursive=False)
            os.replace(temporary_output, output)
        return ArchiveResult(output, manifest)

    def restore_snapshot(self, archive: Path, *, psql: Path) -> dict[str, Any]:
        with _extracted_archive(archive) as extracted:
            manifest = _load_and_verify_manifest(extracted, expected_kind="worker-state")
            schema = extracted / "schema.sql"
            if not schema.is_file():
                raise CloudArchiveError("작업 상태 아카이브에 schema.sql이 없습니다.")
            self._restore_schema(psql, schema)
            with self._conn.transaction():
                for item in manifest["tables"]:
                    self._copy_in(extracted, item, replace=True)
            return manifest

    def _copy_out(
        self,
        spec: TableSpec,
        columns: list[str],
        path: Path,
        kind: str,
        reference_date: date,
    ) -> int:
        relation = sql.Identifier(spec.schema, spec.table)
        selection = sql.SQL("SELECT {} FROM {}").format(
            sql.SQL(",").join(map(sql.Identifier, columns)), relation
        )
        params: list[Any] = []
        if kind == "worker-state" and spec.snapshot_days and spec.delta_date_column:
            selection += sql.SQL(" WHERE {}::date >= %s").format(
                sql.Identifier(spec.delta_date_column)
            )
            params.append(reference_date - timedelta(days=spec.snapshot_days))
        elif kind == "daily-delta" and spec.delta_date_column:
            selection += sql.SQL(" WHERE {}::date = %s").format(
                sql.Identifier(spec.delta_date_column)
            )
            params.append(reference_date)
        elif kind == "daily-delta" and not spec.full_in_delta:
            return 0
        copy_query = sql.SQL("COPY ({}) TO STDOUT WITH (FORMAT CSV, HEADER TRUE)").format(
            selection
        )
        with path.open("wb") as stream, self._conn.cursor() as cursor:
            with cursor.copy(copy_query, params) as copy:
                for chunk in copy:
                    stream.write(chunk)
        # Count CSV records rather than physical lines: JSON/text columns may contain
        # quoted newlines and a line count would make the manifest incorrect.
        with path.open("r", encoding="utf-8", newline="") as stream:
            return max(0, sum(1 for _ in csv.reader(stream)) - 1)

    def _copy_in(self, extracted: Path, item: dict[str, Any], *, replace: bool) -> None:
        relation_name = str(item["relation"])
        spec = next((candidate for candidate in self._tables if candidate.relation == relation_name), None)
        if spec is None:
            raise CloudArchiveError(f"허용되지 않은 테이블입니다: {relation_name}")
        columns = [str(column) for column in item["columns"]]
        path = extracted / str(item["file"])
        relation = sql.Identifier(spec.schema, spec.table)
        if replace:
            self._conn.execute(sql.SQL("TRUNCATE TABLE {}").format(relation))
        copy_query = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT CSV, HEADER TRUE)").format(
            relation, sql.SQL(",").join(map(sql.Identifier, columns))
        )
        with path.open("rb") as stream, self._conn.cursor() as cursor:
            with cursor.copy(copy_query) as copy:
                while chunk := stream.read(1024 * 1024):
                    copy.write(chunk)

    def _dump_schema(self, executable: Path, output: Path) -> None:
        if not executable.is_file():
            raise CloudArchiveError(f"pg_dump 실행 파일이 없습니다: {executable}")
        schema = self._compatible_restore_schema(schema)
        parameters = self._parameters()
        environment = os.environ.copy()
        if parameters.get("password"):
            environment["PGPASSWORD"] = parameters["password"]
        command = [
            str(executable),
            "--schema-only",
            "--no-owner",
            "--no-privileges",
            "--host",
            parameters.get("host", "127.0.0.1"),
            "--port",
            parameters.get("port", "5432"),
            "--username",
            parameters.get("user", ""),
            "--dbname",
            parameters.get("dbname", ""),
            "--file",
            str(output),
        ]
        for spec in self._tables:
            command.extend(("--table", spec.relation))
        completed = subprocess.run(
            command, env=environment, text=True, capture_output=True, check=False
        )
        if completed.returncode:
            detail = _safe_process_detail(completed.stderr)
            raise CloudArchiveError(
                f"작업 상태 스키마 추출 실패: pg_dump 종료코드 {completed.returncode}"
                + (f" ({detail})" if detail else "")
            )

    def _restore_schema(self, executable: Path, schema: Path) -> None:
        if not executable.is_file():
            raise CloudArchiveError(f"psql 실행 파일이 없습니다: {executable}")
        # A table-filtered pg_dump does not promise to emit CREATE SCHEMA.  Create
        # only the two allow-listed namespaces before invoking psql.
        with self._conn.transaction():
            self._conn.execute("CREATE SCHEMA IF NOT EXISTS market")
            self._conn.execute("CREATE SCHEMA IF NOT EXISTS market_core")
        parameters = self._parameters()
        environment = os.environ.copy()
        if parameters.get("password"):
            environment["PGPASSWORD"] = parameters["password"]
        command = [
            str(executable),
            "--set",
            "ON_ERROR_STOP=1",
            "--host",
            parameters.get("host", "127.0.0.1"),
            "--port",
            parameters.get("port", "5432"),
            "--username",
            parameters.get("user", ""),
            "--dbname",
            parameters.get("dbname", ""),
            "--file",
            str(schema),
        ]
        completed = subprocess.run(
            command, env=environment, text=True, capture_output=True, check=False
        )
        if completed.returncode:
            detail = _safe_process_detail(completed.stderr)
            raise CloudArchiveError(
                f"작업 상태 스키마 복원 실패: psql 종료코드 {completed.returncode}"
                + (f" ({detail})" if detail else "")
            )

    @staticmethod
    def _compatible_restore_schema(schema: Path) -> Path:
        """Remove newer-server session settings unsupported by PostgreSQL 16."""
        source = schema.read_text(encoding="utf-8")
        lines = source.splitlines(keepends=True)
        compatible = [
            line for line in lines
            if not line.lstrip().startswith("SET transaction_timeout =")
        ]
        if len(compatible) == len(lines):
            return schema
        target = schema.with_name("schema-compatible.sql")
        target.write_text("".join(compatible), encoding="utf-8")
        return target

    def _latest_market_date(self) -> date:
        row = self._conn.execute(
            "SELECT max(trade_date::date) AS latest FROM market.ohlcv_daily"
        ).fetchone()
        if not row or row["latest"] is None:
            raise CloudArchiveError("작업 상태 기준 거래일을 찾지 못했습니다.")
        return row["latest"]

    def _parameters(self) -> dict[str, str]:
        parameters = dict(self._conn.info.get_parameters())
        if self._conninfo:
            parameters.update(
                {key: value for key, value in conninfo_to_dict(self._conninfo).items() if value}
            )
        return parameters

    def _relation_exists(self, spec: TableSpec) -> bool:
        row = self._conn.execute("SELECT to_regclass(%s) AS relation", (spec.relation,)).fetchone()
        return bool(row and row["relation"])

    def _columns(self, spec: TableSpec) -> list[str]:
        rows = self._conn.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position""",
            (spec.schema, spec.table),
        ).fetchall()
        columns = [str(row["column_name"]) for row in rows]
        if not columns or any(key not in columns for key in spec.key_columns):
            raise CloudArchiveError(f"테이블 열 또는 기본키 정의가 맞지 않습니다: {spec.relation}")
        return columns


class DeltaArchiveApplier:
    def __init__(self, conn, tables: tuple[TableSpec, ...] = WORKER_TABLES) -> None:
        self._conn = conn
        self._tables = {spec.relation: spec for spec in tables}

    def apply(self, archive: Path) -> dict[str, Any]:
        with _extracted_archive(archive) as extracted:
            manifest = _load_and_verify_manifest(extracted, expected_kind="daily-delta")
            self._ensure_history_table()
            batch_id = str(manifest["batch_id"])
            if self._already_applied(batch_id):
                return {**manifest, "apply_status": "already-applied"}
            with self._conn.transaction():
                for item in manifest["tables"]:
                    self._apply_table(extracted, item)
                self._conn.execute(
                    """INSERT INTO market_core.drive_sync_batches
                       (batch_id,reference_date,git_commit,manifest)
                       VALUES (%s,%s,%s,%s::jsonb)""",
                    (
                        batch_id,
                        manifest["reference_date"],
                        manifest.get("git_commit", "unknown"),
                        json.dumps(manifest, ensure_ascii=False),
                    ),
                )
            return {**manifest, "apply_status": "applied"}

    def _apply_table(self, extracted: Path, item: dict[str, Any]) -> None:
        relation_name = str(item["relation"])
        spec = self._tables.get(relation_name)
        if spec is None:
            raise CloudArchiveError(f"허용되지 않은 변경분 테이블입니다: {relation_name}")
        columns = [str(column) for column in item["columns"]]
        if any(key not in columns for key in spec.key_columns):
            raise CloudArchiveError(f"변경분 기본키가 없습니다: {relation_name}")
        relation = sql.Identifier(spec.schema, spec.table)
        temporary_name = f"drive_stage_{spec.schema}_{spec.table}"
        temporary = sql.Identifier(temporary_name[:63])
        self._conn.execute(
            sql.SQL("CREATE TEMP TABLE {} (LIKE {} INCLUDING DEFAULTS) ON COMMIT DROP").format(
                temporary, relation
            )
        )
        copy_query = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT CSV, HEADER TRUE)").format(
            temporary, sql.SQL(",").join(map(sql.Identifier, columns))
        )
        path = extracted / str(item["file"])
        with path.open("rb") as stream, self._conn.cursor() as cursor:
            with cursor.copy(copy_query) as copy:
                while chunk := stream.read(1024 * 1024):
                    copy.write(chunk)
        non_keys = [column for column in columns if column not in spec.key_columns]
        insert = sql.SQL("INSERT INTO {} ({}) SELECT {} FROM {}").format(
            relation,
            sql.SQL(",").join(map(sql.Identifier, columns)),
            sql.SQL(",").join(map(sql.Identifier, columns)),
            temporary,
        )
        conflict = sql.SQL(" ON CONFLICT ({}) ").format(
            sql.SQL(",").join(map(sql.Identifier, spec.key_columns))
        )
        if non_keys:
            assignments = sql.SQL(",").join(
                sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(column), sql.Identifier(column))
                for column in non_keys
            )
            self._conn.execute(insert + conflict + sql.SQL("DO UPDATE SET ") + assignments)
        else:
            self._conn.execute(insert + conflict + sql.SQL("DO NOTHING"))

    def _ensure_history_table(self) -> None:
        with self._conn.transaction():
            self._conn.execute("CREATE SCHEMA IF NOT EXISTS market_core")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS market_core.drive_sync_batches (
                   batch_id text PRIMARY KEY, reference_date date NOT NULL,
                   git_commit text NOT NULL, manifest jsonb NOT NULL,
                   applied_at timestamptz NOT NULL DEFAULT now())"""
            )

    def _already_applied(self, batch_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM market_core.drive_sync_batches WHERE batch_id=%s", (batch_id,)
        ).fetchone()
        return row is not None


@contextmanager
def _extracted_archive(path: Path) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="stock-drive-import-") as temporary_name:
        target = Path(temporary_name)
        try:
            with tarfile.open(path, "r:gz") as archive:
                root = target.resolve()
                for member in archive.getmembers():
                    destination = (target / member.name).resolve()
                    if root not in destination.parents and destination != root:
                        raise CloudArchiveError("아카이브 경로가 안전하지 않습니다.")
                    if member.isdir():
                        destination.mkdir(parents=True, exist_ok=True)
                        continue
                    if not member.isfile() or member.issym() or member.islnk():
                        raise CloudArchiveError("아카이브에 허용되지 않은 항목이 있습니다.")
                    source = archive.extractfile(member)
                    if source is None:
                        raise CloudArchiveError("아카이브 파일을 읽을 수 없습니다.")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with source, destination.open("wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
        except (OSError, tarfile.TarError) as exc:
            raise CloudArchiveError("Stock Drive 아카이브를 열 수 없습니다.") from exc
        yield target


def _load_and_verify_manifest(extracted: Path, *, expected_kind: str) -> dict[str, Any]:
    try:
        manifest = json.loads((extracted / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise CloudArchiveError("아카이브 manifest.json을 읽을 수 없습니다.") from exc
    if manifest.get("format_version") != ARCHIVE_FORMAT_VERSION:
        raise CloudArchiveError("지원하지 않는 아카이브 버전입니다.")
    if manifest.get("kind") != expected_kind:
        raise CloudArchiveError("요청한 종류와 다른 아카이브입니다.")
    for item in manifest.get("tables", []):
        path = extracted / str(item.get("file", ""))
        if not path.is_file() or _sha256(path) != item.get("sha256"):
            raise CloudArchiveError(f"아카이브 파일 검증 실패: {path.name}")
    return manifest


def verify_archive(path: Path, *, expected_kind: str) -> dict[str, Any]:
    """Verify safe extraction, format, kind, and every payload hash."""
    with _extracted_archive(path) as extracted:
        return _load_and_verify_manifest(extracted, expected_kind=expected_kind)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_process_detail(stderr: str) -> str:
    lines = [line.strip() for line in str(stderr).splitlines() if line.strip()]
    detail = lines[-1] if lines else ""
    # PostgreSQL diagnostics should never contain credentials, but keep the
    # persisted/displayed detail deliberately short and single-line.
    return detail[:500]
