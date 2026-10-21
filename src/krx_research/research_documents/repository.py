from __future__ import annotations

import json
from contextlib import AbstractContextManager
from typing import Any

from krx_research.data_engine.config import DataEngineSettings
from krx_research.data_engine.postgresql import BaseDataRepository


SCHEMA = """
CREATE SCHEMA IF NOT EXISTS research;
CREATE TABLE IF NOT EXISTS research.report (
 report_id bigserial PRIMARY KEY, sha256 char(64) UNIQUE NOT NULL,
 stock_code varchar(6), report_date date, broker text, title text, analyst text,
 source_url text, original_filename text NOT NULL, pdf_bytes bytea NOT NULL,
 page_count integer NOT NULL, imported_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS research_report_stock_date ON research.report(stock_code,report_date DESC);
CREATE TABLE IF NOT EXISTS research.page (
 report_id bigint NOT NULL REFERENCES research.report(report_id) ON DELETE CASCADE,
 page_no integer NOT NULL, body_text text NOT NULL, PRIMARY KEY(report_id,page_no));
CREATE TABLE IF NOT EXISTS research.extracted_table (
 report_id bigint NOT NULL REFERENCES research.report(report_id) ON DELETE CASCADE,
 page_no integer NOT NULL, table_no integer NOT NULL, cells jsonb NOT NULL,
 status text NOT NULL DEFAULT 'UNVERIFIED', PRIMARY KEY(report_id,page_no,table_no));
CREATE TABLE IF NOT EXISTS research.report_section (
 report_id bigint NOT NULL REFERENCES research.report(report_id) ON DELETE CASCADE,
 page_no integer NOT NULL, section_no integer NOT NULL,
 section_kind text NOT NULL CHECK(section_kind IN ('NARRATIVE','FINANCIAL','CONSENSUS','MIXED','OTHER')),
 section_text text NOT NULL, extraction_status text NOT NULL DEFAULT 'AUTO_EXTRACTED',
 PRIMARY KEY(report_id,page_no,section_no));
CREATE INDEX IF NOT EXISTS research_section_kind ON research.report_section(report_id,section_kind,page_no);
CREATE TABLE IF NOT EXISTS research.report_fact (
 fact_id bigserial PRIMARY KEY, report_id bigint NOT NULL REFERENCES research.report(report_id) ON DELETE CASCADE,
 page_no integer NOT NULL, table_no integer, row_no integer, column_no integer,
 stock_code varchar(6) NOT NULL, asof_date date NOT NULL,
 origin text NOT NULL CHECK(origin IN ('BROKER_REPORTED_ACTUAL','BROKER_FORECAST','MARKET_CONSENSUS')),
 statement_kind text NOT NULL, metric_code text NOT NULL, fiscal_period text NOT NULL,
 period_kind text NOT NULL CHECK(period_kind IN ('Q','FY','TTM')),
 accounting_scope text NOT NULL CHECK(accounting_scope IN ('CONSOLIDATED','SEPARATE','UNKNOWN')),
 unit text NOT NULL, amount numeric(28,6) NOT NULL, sample_count integer,
 review_status text NOT NULL DEFAULT 'PENDING' CHECK(review_status IN ('PENDING','VERIFIED','REJECTED')),
 UNIQUE(report_id,page_no,table_no,row_no,column_no,metric_code));
CREATE INDEX IF NOT EXISTS research_fact_lookup ON research.report_fact
 (stock_code,origin,metric_code,fiscal_period,asof_date DESC) WHERE review_status='VERIFIED';
CREATE OR REPLACE VIEW research.verified_fact AS SELECT f.* FROM research.report_fact f WHERE f.review_status='VERIFIED';
CREATE TABLE IF NOT EXISTS research.source_item (
 source_url text PRIMARY KEY, title text, pdf_url text, sha256 char(64),
 last_seen timestamptz NOT NULL DEFAULT now(), last_error text, imported_at timestamptz);
"""


class ResearchDocumentRepository(AbstractContextManager):
    def __init__(self, settings: DataEngineSettings | None = None) -> None:
        self._base = BaseDataRepository(
            settings or DataEngineSettings.from_environment(),
            application_name="research_document_repository",
            read_only=False,
        )

    def __enter__(self):
        self._base.__enter__()
        with self._base.conn.transaction():
            self._base.conn.execute(SCHEMA)
        return self

    def __exit__(self, *args):
        self._base.__exit__(*args)

    def save_report(self, checksum: str, header: dict[str, Any], source_url: str | None,
                    filename: str, raw: bytes, pages: list[tuple]) -> int:
        with self._base.conn.transaction():
            row = self._base.conn.execute(
                """INSERT INTO research.report
                (sha256,stock_code,report_date,broker,title,analyst,source_url,original_filename,pdf_bytes,page_count)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(sha256) DO UPDATE SET original_filename=research.report.original_filename
                RETURNING report_id""",
                (checksum, header["stock_code"], header["report_date"], header["broker"],
                 header["title"], header["analyst"], source_url, filename, raw, len(pages)),
            ).fetchone()
            report_id = int(row["report_id"])
            for page_no, text, tables, sections in pages:
                self._base.conn.execute(
                    """INSERT INTO research.page(report_id,page_no,body_text) VALUES (%s,%s,%s)
                    ON CONFLICT(report_id,page_no) DO UPDATE SET body_text=EXCLUDED.body_text""",
                    (report_id, page_no, text),
                )
                for table_no, cells in enumerate(tables, 1):
                    self._base.conn.execute(
                        """INSERT INTO research.extracted_table(report_id,page_no,table_no,cells)
                        VALUES (%s,%s,%s,%s::jsonb) ON CONFLICT(report_id,page_no,table_no)
                        DO UPDATE SET cells=EXCLUDED.cells,status='UNVERIFIED'""",
                        (report_id, page_no, table_no, json.dumps(cells, ensure_ascii=False)),
                    )
                for section_no, (kind, section_text) in enumerate(sections, 1):
                    self._base.conn.execute(
                        """INSERT INTO research.report_section
                        (report_id,page_no,section_no,section_kind,section_text) VALUES (%s,%s,%s,%s,%s)
                        ON CONFLICT(report_id,page_no,section_no) DO UPDATE SET
                        section_kind=EXCLUDED.section_kind,section_text=EXCLUDED.section_text,
                        extraction_status='AUTO_EXTRACTED'""",
                        (report_id, page_no, section_no, kind, section_text),
                    )
        return report_id

    def source_digest(self, source_url: str) -> str | None:
        row = self._base.conn.execute(
            "SELECT sha256 FROM research.source_item WHERE source_url=%s", (source_url,)
        ).fetchone()
        return None if row is None else str(row["sha256"] or "")

    def save_source(self, source_url: str, title: str, pdf_url: str, checksum: str) -> None:
        with self._base.conn.transaction():
            self._base.conn.execute(
                """INSERT INTO research.source_item
                (source_url,title,pdf_url,sha256,imported_at,last_error)
                VALUES (%s,%s,%s,%s,now(),NULL) ON CONFLICT(source_url) DO UPDATE SET
                title=EXCLUDED.title,pdf_url=EXCLUDED.pdf_url,sha256=EXCLUDED.sha256,
                imported_at=now(),last_seen=now(),last_error=NULL""",
                (source_url, title, pdf_url, checksum),
            )

    def save_source_error(self, source_url: str, title: str, error: str) -> None:
        with self._base.conn.transaction():
            self._base.conn.execute(
                """INSERT INTO research.source_item(source_url,title,last_error) VALUES (%s,%s,%s)
                ON CONFLICT(source_url) DO UPDATE SET title=EXCLUDED.title,
                last_error=EXCLUDED.last_error,last_seen=now()""",
                (source_url, title, error[:350]),
            )
