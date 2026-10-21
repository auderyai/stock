from __future__ import annotations

from datetime import date

from krx_research_nextgen.infrastructure.db_settings import PostgreSQLSettings
from krx_research_nextgen.infrastructure.postgresql import open_connection


class BollingerBreadthRepository:
    """Persist reproducible derived breadth results without modifying source facts."""

    def __init__(self, settings: PostgreSQLSettings | None = None) -> None:
        self._settings = settings or PostgreSQLSettings.from_c_stock_env(read_only=False)

    def save(
        self,
        trade_date: date,
        rows: list[dict[str, object]],
        universe_count: int,
        counts: dict[str, int],
        formula_version: str,
    ) -> None:
        if universe_count <= 0:
            raise ValueError("볼린저 시장 집계의 전체 종목 수는 0보다 커야 합니다.")
        with open_connection(
            self._settings,
            application_name="krx_bollinger_breadth",
            read_only=False,
            autocommit=False,
        ) as conn:
            conn.execute("CREATE SCHEMA IF NOT EXISTS market_analysis")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_analysis.bollinger_breakout_daily (
                    trade_date date NOT NULL, direction varchar(5) NOT NULL,
                    stock_code varchar(6) NOT NULL, market varchar(16) NOT NULL,
                    close_price double precision NOT NULL, band_value double precision NOT NULL,
                    distance_pct double precision NOT NULL,
                    formula_version varchar(32) NOT NULL,
                    calculated_at timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (trade_date, direction, stock_code),
                    CHECK (direction IN ('UPPER','LOWER'))
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_analysis.bollinger_breadth_daily (
                    trade_date date PRIMARY KEY, universe_count integer NOT NULL CHECK (universe_count > 0),
                    upper_breakout_count integer NOT NULL CHECK (upper_breakout_count >= 0),
                    lower_breakout_count integer NOT NULL CHECK (lower_breakout_count >= 0),
                    kospi_upper_count integer NOT NULL DEFAULT 0 CHECK (kospi_upper_count >= 0),
                    kospi_lower_count integer NOT NULL DEFAULT 0 CHECK (kospi_lower_count >= 0),
                    kosdaq_upper_count integer NOT NULL DEFAULT 0 CHECK (kosdaq_upper_count >= 0),
                    kosdaq_lower_count integer NOT NULL DEFAULT 0 CHECK (kosdaq_lower_count >= 0),
                    formula_version varchar(32) NOT NULL,
                    calculated_at timestamptz NOT NULL DEFAULT now()
                )
            """)
            for column in ("kospi_upper_count", "kospi_lower_count", "kosdaq_upper_count", "kosdaq_lower_count"):
                conn.execute(f"ALTER TABLE market_analysis.bollinger_breadth_daily ADD COLUMN IF NOT EXISTS {column} integer NOT NULL DEFAULT 0 CHECK ({column} >= 0)")
            conn.execute("DELETE FROM market_analysis.bollinger_breakout_daily WHERE trade_date=%s", (trade_date,))
            if rows:
                with conn.cursor() as cursor:
                    cursor.executemany("""
                        INSERT INTO market_analysis.bollinger_breakout_daily
                        (trade_date,direction,stock_code,market,close_price,band_value,distance_pct,formula_version)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """, [(trade_date, row["direction"], row["stock_code"], row["market"], row["close"],
                            row["band"], row["distance_pct"], row["formula_version"]) for row in rows])
            conn.execute("""
                INSERT INTO market_analysis.bollinger_breadth_daily
                (trade_date,universe_count,upper_breakout_count,lower_breakout_count,
                 kospi_upper_count,kospi_lower_count,kosdaq_upper_count,kosdaq_lower_count,formula_version)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (trade_date) DO UPDATE SET
                  universe_count=EXCLUDED.universe_count,
                  upper_breakout_count=EXCLUDED.upper_breakout_count,
                  lower_breakout_count=EXCLUDED.lower_breakout_count,
                  kospi_upper_count=EXCLUDED.kospi_upper_count,
                  kospi_lower_count=EXCLUDED.kospi_lower_count,
                  kosdaq_upper_count=EXCLUDED.kosdaq_upper_count,
                  kosdaq_lower_count=EXCLUDED.kosdaq_lower_count,
                  formula_version=EXCLUDED.formula_version,
                  calculated_at=now()
            """, (trade_date, universe_count, counts["upper"], counts["lower"],
                    counts["kospi_upper"], counts["kospi_lower"],
                    counts["kosdaq_upper"], counts["kosdaq_lower"],
                    formula_version))
