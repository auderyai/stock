from __future__ import annotations

import unittest

from krx_research.infrastructure.xing_db import PostgreSQLXingCloudRepository


class _Transaction:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _Result:
    def fetchone(self):
        return {"relation": "market_core.venue_ohlcv_daily"}


class _Connection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def transaction(self):
        return _Transaction()

    def execute(self, statement: str):
        self.statements.append(statement)
        return _Result()


class _BaseRepository:
    def __init__(self) -> None:
        self.conn = _Connection()

    def initialize_schema(self) -> None:
        raise AssertionError("cloud initialization must not create local schema")


class CloudRepositoryTests(unittest.TestCase):
    def test_initialize_creates_only_cloud_owned_relations(self) -> None:
        repository = PostgreSQLXingCloudRepository.__new__(PostgreSQLXingCloudRepository)
        repository._repo = _BaseRepository()

        repository.initialize()

        ddl = repository._repo.conn.statements[0].lower()
        self.assertIn("cloud_stock_universe", ddl)
        self.assertIn("ls_investor_t1702_raw", ddl)
        self.assertIn("ls_investor_t1702_checkpoint", ddl)
        for token in ("ls_sector_" + "master", "ls_security_" + "master", "ls_index_" + "membership"):
            self.assertNotIn(token, ddl)


if __name__ == "__main__":
    unittest.main()
