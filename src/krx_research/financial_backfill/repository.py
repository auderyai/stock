from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from krx_research.cloud_sync.archive import DeltaArchiveApplier
from krx_research.cloud_sync.models import FINANCIAL_TABLES
from krx_research.database.postgresql_schema import POSTGRESQL_FINANCIAL_SCHEMA

from .models import FinancialBatch, FinancialPeriod


class FinancialRepository:
    """The only PostgreSQL writer used by the OpenDART backfill service."""

    def __init__(self, connection) -> None:
        self._connection = connection

    def initialize_schema(self) -> None:
        with self._connection.transaction():
            for statement in POSTGRESQL_FINANCIAL_SCHEMA:
                self._connection.execute(statement)
            self._connection.execute(
                "ALTER TABLE financial.statement_facts "
                "ADD COLUMN IF NOT EXISTS value_kind VARCHAR(32) NOT NULL DEFAULT 'current'"
            )

    def replace_staging_batch(
        self, batch: FinancialBatch, *, year: int, period: FinancialPeriod
    ) -> dict[str, int | str]:
        run_id = str(uuid4())
        now = datetime.now(timezone.utc)
        with self._connection.transaction():
            self._connection.execute(
                "TRUNCATE financial.statement_facts, financial.filings, "
                "financial.company_master, financial.ingestion_runs CASCADE"
            )
            self._connection.execute(
                "INSERT INTO financial.ingestion_runs "
                "(run_id,started_at,status,fiscal_year,fiscal_period,companies_requested) "
                "VALUES (%s,%s,'running',%s,%s,%s)",
                (run_id, now, year, period.label, len(batch.companies)),
            )
            self._write_companies(batch, now)
            self._write_filings(batch, year, period, now)
            self._write_facts(batch, now)
            self._connection.execute(
                "UPDATE financial.ingestion_runs SET finished_at=%s,status='completed',"
                "companies_completed=%s,facts_written=%s WHERE run_id=%s",
                (now, len(batch.companies), batch.fact_count, run_id),
            )
        result = self.batch_counts()
        if result["companies"] != len(batch.companies) or result["facts"] != batch.fact_count:
            raise RuntimeError("PostgreSQL 배치 저장 행 수 검증에 실패했습니다.")
        return {"run_id": run_id, **result}

    def apply_archive(self, archive: Path) -> dict[str, Any]:
        self.initialize_schema()
        return DeltaArchiveApplier(
            self._connection, FINANCIAL_TABLES, expected_kind="financial-delta"
        ).apply(archive)

    def year_fact_count(self, year: int) -> int:
        row = self._connection.execute(
            "SELECT count(*) AS count FROM financial.statement_facts WHERE fiscal_year=%s",
            (year,),
        ).fetchone()
        return int(row["count"] if isinstance(row, dict) else row[0])

    def batch_counts(self) -> dict[str, int]:
        row = self._connection.execute(
            "SELECT (SELECT count(*) FROM financial.company_master) AS companies, "
            "(SELECT count(*) FROM financial.statement_facts) AS facts"
        ).fetchone()
        return {
            "companies": int(row["companies"] if isinstance(row, dict) else row[0]),
            "facts": int(row["facts"] if isinstance(row, dict) else row[1]),
        }

    def _write_companies(self, batch: FinancialBatch, retrieved_at: datetime) -> None:
        for company in batch.companies:
            self._connection.execute(
                """INSERT INTO financial.company_master
                   (corp_code,ticker,corp_name,corp_name_eng,modified_at,source_url,retrieved_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (corp_code) DO UPDATE SET ticker=EXCLUDED.ticker,
                   corp_name=EXCLUDED.corp_name,corp_name_eng=EXCLUDED.corp_name_eng,
                   modified_at=EXCLUDED.modified_at,retrieved_at=EXCLUDED.retrieved_at""",
                (
                    company.corp_code, company.ticker, company.name,
                    company.english_name or None, company.modified_at,
                    "https://opendart.fss.or.kr/api/corpCode.xml", retrieved_at,
                ),
            )

    def _write_filings(
        self, batch: FinancialBatch, year: int, period: FinancialPeriod, retrieved_at: datetime
    ) -> None:
        by_receipt = {str(fact["receipt_no"]): fact for fact in batch.facts}
        for receipt_no, fact in by_receipt.items():
            filing_date = datetime.strptime(receipt_no[:8], "%Y%m%d").date()
            self._connection.execute(
                """INSERT INTO financial.filings
                   (receipt_no,corp_code,report_code,report_name,filing_date,fiscal_year,
                    fiscal_period,statement_scope,source_url,retrieved_at,raw_json)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'MIXED',%s,%s,%s::jsonb)
                   ON CONFLICT (receipt_no) DO UPDATE SET retrieved_at=EXCLUDED.retrieved_at,
                   raw_json=EXCLUDED.raw_json""",
                (
                    receipt_no, fact["corp_code"], period.report_code,
                    f"{year} {period.label}", filing_date, year, period.label,
                    f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt_no}",
                    retrieved_at, json.dumps(fact["raw_json"], ensure_ascii=False),
                ),
            )

    def _write_facts(self, batch: FinancialBatch, retrieved_at: datetime) -> None:
        for fact in batch.facts:
            self._connection.execute(
                """INSERT INTO financial.statement_facts
                   (fact_key,receipt_no,corp_code,fiscal_year,fiscal_period,statement_scope,
                    statement_code,account_id,account_name,account_detail,value_kind,
                    period_start,period_end,amount,currency,ordinal,retrieved_at,raw_json)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                   ON CONFLICT (fact_key) DO UPDATE SET amount=EXCLUDED.amount,
                   retrieved_at=EXCLUDED.retrieved_at,raw_json=EXCLUDED.raw_json""",
                (
                    fact["fact_key"], fact["receipt_no"], fact["corp_code"],
                    fact["fiscal_year"], fact["fiscal_period"], fact["statement_scope"],
                    fact["statement_code"], fact["account_id"], fact["account_name"],
                    fact["account_detail"], fact["value_kind"], fact["period_start"],
                    fact["period_end"], fact["amount"], fact["currency"], fact["ordinal"],
                    retrieved_at, json.dumps(fact["raw_json"], ensure_ascii=False),
                ),
            )
