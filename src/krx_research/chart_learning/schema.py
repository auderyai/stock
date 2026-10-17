SCHEMA_VERSION = 1

DDL = (
    "CREATE SCHEMA IF NOT EXISTS chart_learning",
    """CREATE TABLE IF NOT EXISTS chart_learning.schema_meta(
        key text PRIMARY KEY, value text NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS chart_learning.pattern_samples(
        sample_id uuid PRIMARY KEY,
        sha256 char(64) NOT NULL,
        ticker varchar(6) NOT NULL,
        company_name text NOT NULL,
        pattern_start date NOT NULL,
        pattern_end date NOT NULL,
        db_reference_date date NOT NULL,
        canonical_path text NOT NULL,
        assessment text NOT NULL,
        rationale text NOT NULL,
        policy_version integer NOT NULL,
        policy jsonb NOT NULL,
        features jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CHECK(pattern_start<=pattern_end),
        UNIQUE(sha256,ticker,pattern_start,pattern_end))""",
    "CREATE INDEX IF NOT EXISTS idx_chart_learning_ticker ON chart_learning.pattern_samples(ticker,pattern_end DESC)",
)
