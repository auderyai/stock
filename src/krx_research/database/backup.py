from __future__ import annotations
import os,subprocess
import csv
import hashlib
import re
import tempfile
from pathlib import Path
from .settings import PostgreSQLSettings


def is_checkpoint_table(table: str) -> bool:
    return any(part in table for part in ("checkpoint", "update_state", "collection_coverage", "ingestion_runs"))

def pg_dump_backup(settings:PostgreSQLSettings,destination:str|Path)->Path:
    dest=Path(destination).expanduser().resolve();dest.parent.mkdir(parents=True,exist_ok=True)
    cmd=[settings.dump_executable,'--format=custom','--host',settings.host,'--port',str(settings.port),'--username',settings.user,'--dbname',settings.database,'--file',str(dest)]
    env=os.environ.copy();env['PGPASSWORD']=settings.password
    result=subprocess.run(cmd,env=env,capture_output=True,text=True,check=False)
    if result.returncode!=0:raise RuntimeError('pg_dump 실패: '+(result.stderr.strip() or result.stdout.strip()))
    if not dest.is_file() or dest.stat().st_size<=0:raise RuntimeError('pg_dump 백업 파일이 비어 있습니다.')
    return dest


class PostgreSQLBackupArchive:
    """Inspect and restore a verified pg_dump archive without emitting source records."""

    _IDENTIFIER = r'(?:"(?:[^"]|"")*"|[A-Za-z_][A-Za-z_0-9$]*)'
    _COPY = re.compile(r'^COPY (' + _IDENTIFIER + r')\.(' + _IDENTIFIER + r') \((.*)\) FROM stdin;$')

    def __init__(self, executable: Path):
        self.executable = Path(executable)

    @staticmethod
    def _identifier(value: str) -> str:
        return value[1:-1].replace('""', '"') if value.startswith('"') else value

    def inspect(self, archive: Path, *, expected_size: int, expected_sha256: str, list_path: Path) -> dict:
        archive = Path(archive).resolve()
        if archive.stat().st_size != expected_size:
            raise ValueError("백업 파일 크기가 지정값과 다릅니다.")
        with archive.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest().upper()
        if digest != expected_sha256.upper():
            raise ValueError("백업 SHA-256이 지정값과 다릅니다.")
        version = subprocess.run([str(self.executable), "--version"], capture_output=True, text=True, check=True)
        if not re.search(r'\b18\.6\b', version.stdout):
            raise ValueError("PostgreSQL 18.6 pg_restore가 필요합니다.")
        listing = subprocess.run(
            [str(self.executable), "--list", str(archive)], capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
        if listing.returncode:
            raise RuntimeError("PostgreSQL 18.6 백업 목록 검사 실패")
        entries = listing.stdout.splitlines()
        expected_tables = sum(bool(re.match(r'^\d+;.* TABLE DATA ', line)) for line in entries)
        if not expected_tables:
            raise ValueError("백업에 테이블 데이터 항목이 없습니다.")
        # public already belongs to the local NOLOGIN owner; retain its existing schema.
        selected = [line for line in entries if not re.match(r'^\d+;.* SCHEMA - public ', line)]
        list_path.write_text("\n".join(selected) + "\n", encoding="utf-8")
        return {"sha256": digest, "bytes": expected_size, "table_data_entries": expected_tables}

    def source_summary(self, archive: Path, *, expected_tables: int) -> dict:
        from krx_research.financial_backfill.models import FinancialPeriod

        tables, active, latest_financial = {}, None, None
        with tempfile.TemporaryFile() as diagnostics:
            process = subprocess.Popen(
                [str(self.executable), "--data-only", "--no-owner", "--no-privileges", "--file", "-", str(archive)],
                stdout=subprocess.PIPE, stderr=diagnostics,
            )
            try:
                for raw in process.stdout:
                    if active is None:
                        if not raw.startswith(b"COPY "):
                            continue
                        match = self._COPY.fullmatch(raw.decode("utf-8").rstrip("\r\n"))
                        if not match:
                            raise ValueError("지원하지 않는 백업 COPY 헤더 형식")
                        schema, table = map(self._identifier, match.group(1, 2))
                        columns = next(csv.reader([match.group(3)], skipinitialspace=True))
                        key = schema + "." + table
                        if key in tables:
                            raise ValueError("백업에 중복된 COPY 대상이 있습니다.")
                        active = {"schema": schema, "table": table, "columns": columns, "rows": 0,
                                  "dates": {}, "statuses": {}}
                        tables[key] = active
                        checkpoint = is_checkpoint_table(table)
                        date_indexes = [(i, name) for i, name in enumerate(columns)
                                        if name == "trade_date" or (checkpoint and name.endswith("_date"))]
                        status_index = columns.index("status") if checkpoint and "status" in columns else None
                        financial_indexes = (columns.index("fiscal_year"), columns.index("fiscal_period")) \
                            if key == "financial.statement_facts" else None
                    elif raw.rstrip(b"\r\n") == b"\\.":
                        active = None
                    else:
                        active["rows"] += 1
                        if not (date_indexes or status_index is not None or financial_indexes):
                            continue
                        fields = raw.rstrip(b"\r\n").split(b"\t")
                        for index, name in date_indexes:
                            value = fields[index].decode("utf-8")
                            if value != r"\N":
                                active["dates"][name] = max(active["dates"].get(name, ""), value)
                        if status_index is not None:
                            value = fields[status_index].decode("utf-8")
                            active["statuses"][value] = active["statuses"].get(value, 0) + 1
                        if financial_indexes:
                            year = int(fields[financial_indexes[0]])
                            period = FinancialPeriod.parse(fields[financial_indexes[1]].decode("utf-8"))
                            candidate = (year, period.month, period.label)
                            latest_financial = max(latest_financial or candidate, candidate)
                exit_code = process.wait()
                if exit_code or active is not None:
                    diagnostics.seek(0)
                    headline = self._error_headline(diagnostics.read())
                    raise RuntimeError(f"백업 원본 검사 실패 (exit={exit_code}, incomplete_copy={active is not None}): {headline}")
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait()
                process.stdout.close()
        if len(tables) != expected_tables:
            raise ValueError("백업 목록과 COPY 데이터 테이블 수가 일치하지 않습니다.")
        if not latest_financial:
            raise ValueError("백업에 검증할 재무자료가 없습니다.")
        return {"tables": tables, "latest_financial": latest_financial}

    @staticmethod
    def _error_headline(diagnostics: bytes) -> str:
        lines = diagnostics.decode("utf-8", errors="replace").splitlines()
        headline = next((line for line in lines if line.startswith("pg_restore: error:")), "추가 오류 제목 없음")
        return re.sub(r'"[^"]*"|\x27[^\x27]*\x27', "[REDACTED]", headline)

    def restore(self, archive: Path, settings: PostgreSQLSettings, *, list_path: Path) -> None:
        if (settings.host, settings.port, settings.database, settings.user) != (
            "127.0.0.1", 5433, "krx_research", "postgres",
        ):
            raise ValueError("복원 대상은 PostgreSQL 18의 로컬 5433/krx_research로 제한됩니다.")
        from .provisioning import PostgreSQLProvisioningRepository

        environment = os.environ.copy()
        environment["PGPASSWORD"] = settings.password
        environment["PGOPTIONS"] = PostgreSQLProvisioningRepository.QUIET_OPTIONS
        with tempfile.TemporaryFile() as diagnostics:
            result = subprocess.run(
                [str(self.executable), "--host", settings.host, "--port", str(settings.port),
                 "--username", settings.user, "--dbname", settings.database,
                 "--role", "krx_owner", "--no-owner", "--no-privileges", "--no-tablespaces",
                 "--single-transaction", "--exit-on-error", "--use-list", str(list_path), str(archive)],
                env=environment, stdout=subprocess.DEVNULL, stderr=diagnostics, check=False,
            )
            if result.returncode:
                diagnostics.seek(0)
                headline = self._error_headline(diagnostics.read())
                raise RuntimeError(f"복원 트랜잭션 실패 (exit={result.returncode}): {headline}")
