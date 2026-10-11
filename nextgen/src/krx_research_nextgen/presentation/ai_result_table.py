from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import pandas as pd

from krx_research.table_alignment import alignment


@dataclass(frozen=True, slots=True)
class AiResultPresentation:
    headers: tuple[str, ...]
    alignments: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    codes: tuple[str, ...]
    ticker_column: int


class AiResultPresenter:
    """Apply the shared text/identity/number rules to an AI result frame."""

    _IDENTITIES = ("ticker", "stock_code", "code")

    def present(self, frame: pd.DataFrame, labels: dict[str, str]) -> AiResultPresentation:
        columns = list(frame.columns)
        ticker_column = next((columns.index(name) for name in self._IDENTITIES if name in columns), -1)
        headers = tuple(labels.get(column, str(column)) for column in columns)
        alignments = tuple(alignment(column, headers[index], frame[column].tolist())
                           for index, column in enumerate(columns))
        rows = tuple(tuple(self._display(value, alignments[index])
                           for index, value in enumerate(values))
                     for values in frame.itertuples(index=False, name=None))
        codes = tuple(self._code(values[ticker_column]) if ticker_column >= 0 else ""
                      for values in frame.itertuples(index=False, name=None))
        if ticker_column >= 0:
            rows = tuple(tuple(code if index == ticker_column else value
                               for index, value in enumerate(row))
                         for row, code in zip(rows, codes))
        return AiResultPresentation(headers, alignments, rows, codes, ticker_column)

    @staticmethod
    def _code(value) -> str:
        text = "" if pd.isna(value) else str(value).strip().removesuffix(".0")
        return text.zfill(6) if text.isdigit() and len(text) <= 6 else text

    @staticmethod
    def _display(value, rule: str) -> str:
        if value is None or (not isinstance(value, str) and pd.isna(value)): return ""
        text = str(value).strip()
        if rule != "right": return text
        try: number = Decimal(text.replace(",", ""))
        except InvalidOperation: return text
        if not number.is_finite(): return ""
        decimals = min(4, max(0, -number.as_tuple().exponent))
        return f"{number:,.{decimals}f}".rstrip("0").rstrip(".") if decimals else f"{number:,.0f}"
