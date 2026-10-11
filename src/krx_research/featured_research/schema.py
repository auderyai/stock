"""PostgreSQL schema for daily featured-stock spreadsheets."""

SCHEMA_NAME = "featured_research"
SCHEMA_VERSION = 2

DDL = (
    "CREATE SCHEMA IF NOT EXISTS featured_research",
    """
    CREATE TABLE IF NOT EXISTS featured_research.schema_meta (
        key text PRIMARY KEY,
        value text NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS featured_research.import_batches (
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
    "CREATE INDEX IF NOT EXISTS idx_featured_batches_date ON featured_research.import_batches(report_date, status)",
    """
    CREATE TABLE IF NOT EXISTS featured_research.featured_stocks (
        row_id bigserial PRIMARY KEY,
        batch_id uuid NOT NULL REFERENCES featured_research.import_batches(batch_id) ON DELETE CASCADE,
        report_date date NOT NULL,
        source_row integer NOT NULL,
        source_ticker varchar(16),
        ticker char(6) CHECK (ticker IS NULL OR ticker ~ '^[0-9A-Z]{6}$'),
        ticker_source varchar(80),
        stock_name text NOT NULL,
        return_pct numeric(12,4),
        source_trading_value_eok numeric(20,4),
        theme_name text,
        reason text NOT NULL,
        db_trade_date date,
        trading_value numeric(24,2),
        trading_value_source varchar(64),
        trading_value_source_url text,
        trading_value_is_estimate boolean NOT NULL DEFAULT false,
        market varchar(32),
        market_source varchar(64),
        lookup_error text,
        public_checked_at timestamptz,
        source_file text NOT NULL,
        raw_data jsonb NOT NULL,
        UNIQUE(batch_id, source_row)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_featured_rows_date ON featured_research.featured_stocks(report_date)",
    "CREATE INDEX IF NOT EXISTS idx_featured_rows_ticker_date ON featured_research.featured_stocks(ticker, report_date)",
    "CREATE INDEX IF NOT EXISTS idx_featured_rows_name_date ON featured_research.featured_stocks(stock_name, report_date)",
    "ALTER TABLE featured_research.featured_stocks ADD COLUMN IF NOT EXISTS trading_value_source_url text",
    "ALTER TABLE featured_research.featured_stocks ADD COLUMN IF NOT EXISTS trading_value_is_estimate boolean NOT NULL DEFAULT false",
    "ALTER TABLE featured_research.featured_stocks ADD COLUMN IF NOT EXISTS public_checked_at timestamptz",
    "ALTER TABLE featured_research.featured_stocks ADD COLUMN IF NOT EXISTS ticker_source varchar(80)",
    "ALTER TABLE featured_research.featured_stocks DROP CONSTRAINT IF EXISTS featured_stocks_ticker_check",
    "ALTER TABLE featured_research.featured_stocks ADD CONSTRAINT featured_stocks_ticker_check CHECK (ticker IS NULL OR ticker ~ '^[0-9A-Z]{6}$')",
)

__all__ = ["DDL", "SCHEMA_NAME", "SCHEMA_VERSION"]
