import unittest
from unittest.mock import MagicMock, patch

from krx_research.financial_backfill.repository import (
    FinancialRepository,
    open_financial_repository,
)


class FinancialRepositoryStructureTests(unittest.TestCase):
    def test_writer_methods_remain_on_repository_class(self):
        required = {
            "batch_counts", "_write_companies", "_write_filings", "_write_facts",
            "apply_archive", "export_delta", "period_fact_count", "year_fact_count",
        }
        self.assertFalse(required.difference(vars(FinancialRepository)))

    def test_connection_lifecycle_is_owned_by_repository_factory(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.__exit__.return_value = False
        with patch(
            "krx_research.financial_backfill.repository.database_conninfo",
            return_value="postgresql://masked",
        ), patch(
            "krx_research.financial_backfill.repository.psycopg.connect",
            return_value=connection,
        ) as connect:
            with open_financial_repository() as repository:
                self.assertIsInstance(repository, FinancialRepository)
        connect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
