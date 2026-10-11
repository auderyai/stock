"""PostgreSQL schema for normalized daily hot-theme spreadsheets."""

SCHEMA_NAME = "theme_research"
SCHEMA_VERSION = 3

DDL = (
    "CREATE SCHEMA IF NOT EXISTS theme_research",
    """
    CREATE TABLE IF NOT EXISTS theme_research.schema_meta (
        key text PRIMARY KEY,
        value text NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS theme_research.import_batches (
        batch_id uuid PRIMARY KEY,
        report_date date NOT NULL,
        file_name text NOT NULL,
        file_sha256 char(64) NOT NULL UNIQUE,
        sheet_name text NOT NULL,
        imported_at timestamptz NOT NULL DEFAULT now(),
        row_count integer NOT NULL CHECK (row_count >= 0),
        matched_count integer NOT NULL CHECK (matched_count >= 0),
        unmatched_count integer NOT NULL CHECK (unmatched_count >= 0),
        status varchar(16) NOT NULL CHECK (status IN ('active', 'superseded'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_theme_batches_date ON theme_research.import_batches(report_date, status)",
    """
    CREATE TABLE IF NOT EXISTS theme_research.hot_theme_stocks (
        row_id bigserial PRIMARY KEY,
        batch_id uuid NOT NULL REFERENCES theme_research.import_batches(batch_id) ON DELETE CASCADE,
        report_date date NOT NULL,
        source_row integer NOT NULL,
        theme_name text NOT NULL,
        ticker char(6) CHECK (ticker ~ '^[0-9A-Z]{6}$'),
        ticker_source varchar(80),
        stock_name text NOT NULL,
        return_pct numeric(12,4),
        reason text NOT NULL,
        source_trading_value_eok numeric(20,4),
        db_trade_date date,
        trading_value numeric(24,2),
        trading_value_source varchar(48),
        trading_value_source_url text,
        trading_value_is_estimate boolean NOT NULL DEFAULT false,
        market varchar(32),
        market_source varchar(48),
        public_checked_at timestamptz,
        lookup_error text,
        source_file text NOT NULL,
        raw_data jsonb NOT NULL,
        UNIQUE(batch_id, source_row)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_theme_rows_date ON theme_research.hot_theme_stocks(report_date)",
    "CREATE INDEX IF NOT EXISTS idx_theme_rows_ticker_date ON theme_research.hot_theme_stocks(ticker, report_date)",
    "CREATE INDEX IF NOT EXISTS idx_theme_rows_theme_date ON theme_research.hot_theme_stocks(theme_name, report_date)",
    "ALTER TABLE theme_research.hot_theme_stocks ADD COLUMN IF NOT EXISTS trading_value_source_url text",
    "ALTER TABLE theme_research.hot_theme_stocks ADD COLUMN IF NOT EXISTS trading_value_is_estimate boolean NOT NULL DEFAULT false",
    "ALTER TABLE theme_research.hot_theme_stocks ADD COLUMN IF NOT EXISTS market_source varchar(48)",
    "ALTER TABLE theme_research.hot_theme_stocks ADD COLUMN IF NOT EXISTS public_checked_at timestamptz",
    "ALTER TABLE theme_research.hot_theme_stocks ADD COLUMN IF NOT EXISTS lookup_error text",
    "ALTER TABLE theme_research.hot_theme_stocks ALTER COLUMN ticker DROP NOT NULL",
    "ALTER TABLE theme_research.hot_theme_stocks ADD COLUMN IF NOT EXISTS ticker_source varchar(80)",
    "ALTER TABLE theme_research.hot_theme_stocks DROP CONSTRAINT IF EXISTS hot_theme_stocks_ticker_check",
    "ALTER TABLE theme_research.hot_theme_stocks ADD CONSTRAINT hot_theme_stocks_ticker_check CHECK (ticker ~ '^[0-9A-Z]{6}$')",
)

__all__ = ["DDL", "SCHEMA_NAME", "SCHEMA_VERSION"]
