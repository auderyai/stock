from __future__ import annotations

import re

import pandas as pd

from krx_research.database import open_research_store


class ReadOnlyDatabaseTool:
    """Strict read-only SQL gateway with row and execution limits."""

    _BLOCKED = re.compile(
        r"\b(insert|update|delete|merge|alter|drop|truncate|create|grant|revoke|copy|call|do|"
        r"vacuum|analyze|refresh|reindex|cluster|comment|security|set|reset|listen|notify|"
        r"pg_[a-z_]+|dblink|nextval|setval|lo_import|lo_export|into)\b|\bfor\s+(update|share)\b",
        re.I,
    )

    def __init__(self, database_target, *, limit: int = 500, max_limit: int = 500_000):
        self.database_target, self.limit, self.max_limit = database_target, int(limit), int(max_limit)

    def query(self, sql: str, *, limit: int | None = None,
              require_complete: bool = False) -> pd.DataFrame:
        statement = str(sql).strip().rstrip(";").strip()
        if not re.match(r"^(select|with)\b", statement, re.I) or self._BLOCKED.search(statement):
            raise ValueError("DB 도구는 읽기 전용 SELECT/CTE만 허용합니다.")
        if ";" in statement or "--" in statement or "/*" in statement:
            raise ValueError("다중 문장과 SQL 주석은 허용하지 않습니다.")
        row_limit = self.limit if limit is None else min(max(int(limit), 1), self.max_limit)
        wrapped = f"SELECT * FROM ({statement}) AS assistant_result LIMIT {row_limit + 1}"
        with open_research_store(self.database_target, read_only=True) as store:
            store.conn.execute("SET statement_timeout TO '20s'")
            rows = store.conn.execute(wrapped).fetchall()
        truncated = len(rows) > row_limit
        if truncated and require_complete:
            raise ValueError(
                f"분석 입력이 {row_limit:,}행을 초과했습니다. 기간 또는 대상 범위를 나누십시오."
            )
        frame = pd.DataFrame(rows[:row_limit])
        frame.attrs["truncated"] = truncated
        return frame

    def catalog(self) -> list[dict[str, str]]:
        sql = """
            SELECT table_schema, table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY table_schema, table_name, ordinal_position
            LIMIT 1000
        """
        with open_research_store(self.database_target, read_only=True) as store:
            rows = store.conn.execute(sql).fetchall()
        return [dict(row) for row in rows]
