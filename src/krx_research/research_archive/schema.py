SCHEMA_VERSION = 1

DDL = (
    "CREATE SCHEMA IF NOT EXISTS research_archive",
    """CREATE TABLE IF NOT EXISTS research_archive.schema_meta(
        key text PRIMARY KEY, value text NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS research_archive.documents(
        document_id uuid PRIMARY KEY, sha256 char(64) NOT NULL UNIQUE,
        document_kind varchar(16) NOT NULL CHECK(document_kind IN ('PDF','IMAGE')),
        report_date date NOT NULL, ticker varchar(6), company_name text,
        title text NOT NULL, provider text, original_filename text NOT NULL,
        canonical_path text NOT NULL UNIQUE, mime_type text NOT NULL, file_size bigint NOT NULL,
        extraction_status varchar(16) NOT NULL, metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
        imported_at timestamptz NOT NULL DEFAULT now())""",
    "CREATE INDEX IF NOT EXISTS idx_research_documents_date ON research_archive.documents(report_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_research_documents_ticker ON research_archive.documents(ticker,report_date DESC)",
    """CREATE TABLE IF NOT EXISTS research_archive.pages(
        document_id uuid NOT NULL REFERENCES research_archive.documents(document_id) ON DELETE CASCADE,
        page_number integer NOT NULL CHECK(page_number>0), page_text text NOT NULL,
        PRIMARY KEY(document_id,page_number))""",
    """CREATE TABLE IF NOT EXISTS research_archive.observations(
        observation_id bigserial PRIMARY KEY,
        document_id uuid NOT NULL REFERENCES research_archive.documents(document_id) ON DELETE CASCADE,
        source_order integer NOT NULL, category text, source_ticker text,
        ticker varchar(6), stock_name text NOT NULL, reason text,
        source_return_pct numeric(14,4), source_trading_value_eok numeric(24,4),
        db_trade_date date, db_return_pct numeric(14,4), db_trading_value_eok numeric(24,4),
        db_close numeric(24,4), market text,
        authority varchar(24) NOT NULL CHECK(authority IN ('DB_AUTHORITY','SOURCE_ONLY','UNRESOLVED')),
        raw_data jsonb NOT NULL DEFAULT '{}'::jsonb,
        UNIQUE(document_id,source_order))""",
    "CREATE INDEX IF NOT EXISTS idx_research_observations_ticker ON research_archive.observations(ticker)",
    "CREATE INDEX IF NOT EXISTS idx_research_observations_name ON research_archive.observations(stock_name)",
)
