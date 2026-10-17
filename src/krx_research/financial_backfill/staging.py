from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any, Iterable

from .models import FinancialPeriod


class FinancialStagingError(RuntimeError):
    pass


class DuckDbFinancialStagingRepository:
    """Validates and deduplicates one API batch in disposable DuckDB memory."""

    def normalize(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        year: int,
        period: FinancialPeriod,
    ) -> tuple[dict[str, Any], ...]:
        normalized = tuple(
            fact
            for row in rows
            for fact in self._facts(row, year=year, period=period)
        )
        if not normalized:
            return ()
        try:
            import duckdb
        except ImportError as exc:
            raise FinancialStagingError(
                "DuckDB가 설치되지 않았습니다. requirements-cloud-worker.txt를 설치하십시오."
            ) from exc
        connection = duckdb.connect(":memory:")
        try:
            connection.execute(
                "CREATE TABLE facts(fact_key VARCHAR, receipt_no VARCHAR, corp_code VARCHAR, "
                "amount DECIMAL(38,4), raw_json JSON)"
            )
            connection.executemany(
                "INSERT INTO facts VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        fact["fact_key"], fact["receipt_no"], fact["corp_code"],
                        fact["amount"], json.dumps(fact["raw_json"], ensure_ascii=False),
                    )
                    for fact in normalized
                ],
            )
            invalid, duplicates = connection.execute(
                "SELECT count(*) FILTER (WHERE receipt_no='' OR corp_code=''), "
                "count(*)-count(DISTINCT fact_key) FROM facts"
            ).fetchone()
            if invalid or duplicates:
                raise FinancialStagingError(
                    f"DuckDB 검증 실패: 필수값 누락={invalid}, 중복={duplicates}"
                )
        finally:
            connection.close()
        return normalized

    @classmethod
    def _facts(
        cls, row: dict[str, Any], *, year: int, period: FinancialPeriod
    ) -> tuple[dict[str, Any], ...]:
        receipt_no = str(row.get("rcept_no") or "").strip()
        corp_code = str(row.get("corp_code") or "").strip()
        account_name = str(row.get("account_nm") or "").strip()
        if len(receipt_no) != 14 or not receipt_no.isdigit():
            raise FinancialStagingError(f"접수번호 형식이 잘못되었습니다: {receipt_no}")
        if len(corp_code) != 8 or not corp_code.isdigit() or not account_name:
            raise FinancialStagingError("기업코드 또는 계정명이 누락되었습니다.")
        result = []
        for source_field, value_kind in (
            ("thstrm_amount", "current"),
            ("thstrm_add_amount", "current_cumulative"),
        ):
            amount = cls._amount(row.get(source_field))
            if amount is None:
                continue
            identity = "|".join((
                receipt_no, corp_code,
                str(year), period.label, str(row.get("fs_div") or row.get("_scope") or ""),
                str(row.get("sj_div") or ""), str(row.get("account_id") or ""),
                str(row.get("account_nm") or ""), str(row.get("account_detail") or ""),
                value_kind,
            ))
            result.append({
                "fact_key": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                "receipt_no": receipt_no,
                "corp_code": corp_code,
                "fiscal_year": year,
                "fiscal_period": period.label,
                "statement_scope": str(row.get("fs_div") or row.get("_scope") or "").strip(),
                "statement_code": str(row.get("sj_div") or "").strip(),
                "account_id": str(row.get("account_id") or "").strip() or None,
                "account_name": account_name,
                "account_detail": str(row.get("account_detail") or "").strip(),
                "value_kind": value_kind,
                "period_start": cls._period_start(year, period, row, value_kind),
                "period_end": period.period_end(year),
                "amount": amount,
                "currency": str(row.get("currency") or "").strip() or None,
                "ordinal": cls._integer(row.get("ord")),
                "raw_json": row,
            })
        return tuple(result)

    @staticmethod
    def _amount(value: object) -> Decimal | None:
        text = str(value or "").replace(",", "").strip()
        if not text or text == "-":
            return None
        try:
            return Decimal(text)
        except InvalidOperation as exc:
            raise FinancialStagingError(f"금액 형식이 잘못되었습니다: {text}") from exc

    @staticmethod
    def _integer(value: object) -> int | None:
        text = str(value or "").strip()
        return int(text) if text.lstrip("-").isdigit() else None

    @staticmethod
    def _period_start(
        year: int, period: FinancialPeriod, row: dict[str, Any], value_kind: str
    ) -> date | None:
        if str(row.get("sj_div") or "") == "BS":
            return None
        if value_kind == "current_cumulative" or period is FinancialPeriod.ANNUAL:
            return date(year, 1, 1)
        start_month = {
            FinancialPeriod.Q1: 1,
            FinancialPeriod.HALF: 4,
            FinancialPeriod.Q3: 7,
        }.get(period, 1)
        return date(year, start_month, 1)
