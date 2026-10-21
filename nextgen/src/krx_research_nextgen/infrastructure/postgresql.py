from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from krx_research_nextgen.infrastructure.db_settings import PostgreSQLSettings


def open_connection(
    settings: PostgreSQLSettings,
    *,
    application_name: str,
    read_only: bool = True,
    autocommit: bool = True,
):
    """Open one PostgreSQL session with read-only mode enforced by default."""

    connection = psycopg.connect(
        **settings.connect_kwargs(),
        row_factory=dict_row,
        autocommit=autocommit,
        application_name=application_name,
    )
    if read_only:
        connection.execute("SET default_transaction_read_only TO on")
    return connection
