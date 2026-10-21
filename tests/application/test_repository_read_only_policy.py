from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from krx_research.data_engine.config import DataEngineSettings
from krx_research.data_engine.postgresql import BaseDataRepository
from krx_research.featured_research.repository import FeaturedResearchRepository
from krx_research.theme_research.repository import ThemeResearchRepository
from krx_research_nextgen.infrastructure.db_settings import PostgreSQLSettings
from krx_research_nextgen.infrastructure.postgresql import open_connection


class RepositoryReadOnlyPolicyTests(unittest.TestCase):
    @staticmethod
    def _connection() -> MagicMock:
        connection = MagicMock()
        connection.execute.return_value.fetchall.return_value = []
        return connection

    def test_repository_is_read_only_by_default(self):
        connection = self._connection()
        settings = DataEngineSettings(conninfo="postgresql://test:test@localhost/test")

        with patch(
            "krx_research.data_engine.postgresql.psycopg.connect",
            return_value=connection,
        ):
            repository = BaseDataRepository(settings)

        self.assertTrue(repository.read_only)
        connection.execute.assert_any_call("SET default_transaction_read_only TO on")

    def test_writer_must_explicitly_disable_read_only_mode(self):
        connection = self._connection()
        settings = DataEngineSettings(conninfo="postgresql://test:test@localhost/test")

        with patch(
            "krx_research.data_engine.postgresql.psycopg.connect",
            return_value=connection,
        ):
            repository = BaseDataRepository(settings, read_only=False)

        self.assertFalse(repository.read_only)
        statements = [call.args[0] for call in connection.execute.call_args_list]
        self.assertNotIn("SET default_transaction_read_only TO on", statements)

    def test_nextgen_connection_uses_the_same_read_only_default(self):
        connection = self._connection()
        settings = PostgreSQLSettings(
            host="localhost", port=5432, dbname="test", user="reader", password="secret"
        )

        with patch(
            "krx_research_nextgen.infrastructure.postgresql.psycopg.connect",
            return_value=connection,
        ):
            returned = open_connection(settings, application_name="test")

        self.assertIs(returned, connection)
        connection.execute.assert_called_once_with(
            "SET default_transaction_read_only TO on"
        )

    def test_daily_research_repositories_are_read_only_by_default(self):
        settings = DataEngineSettings(conninfo="postgresql://test:test@localhost/test")
        for repository_type, target in (
            (
                FeaturedResearchRepository,
                "krx_research.featured_research.repository.psycopg.connect",
            ),
            (
                ThemeResearchRepository,
                "krx_research.theme_research.repository.psycopg.connect",
            ),
        ):
            with self.subTest(repository=repository_type.__name__):
                connection = self._connection()
                with patch(target, return_value=connection):
                    repository_type(settings)
                connection.execute.assert_called_once_with(
                    "SET default_transaction_read_only TO on"
                )
                self.assertFalse(connection.autocommit)

    def test_daily_research_writer_is_explicit(self):
        connection = self._connection()
        settings = DataEngineSettings(conninfo="postgresql://test:test@localhost/test")
        with patch(
            "krx_research.featured_research.repository.psycopg.connect",
            return_value=connection,
        ):
            FeaturedResearchRepository(settings, read_only=False)
        connection.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
