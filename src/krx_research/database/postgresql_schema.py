"""PostgreSQL schemas for market data and OpenDART financial data."""

from __future__ import annotations

MARKET_SCHEMA = "market"
FINANCIAL_SCHEMA = "financial"
FINANCIAL_SCHEMA_VERSION = 1

MARKET_TABLE_ORDER = (
    "security_master",
    "ohlcv_daily",
    "ohlcv_history_runs",
    "ohlcv_history_attempts",
    "ohlcv_quality_events",
    "technical_indicators_daily",
    "technical_indicators_weekly",
    "technical_indicator_state",
    "screen_runs",
    "screen_results",
    "artifacts",
    "artifact_views",
)

FINANCIAL_TABLES = (
    "schema_meta",
    "company_master",
    "filings",
    "statement_facts",
    "notes",
    "ingestion_runs",
)

POSTGRESQL_MARKET_SCHEMA = (
    "CREATE SCHEMA IF NOT EXISTS market",
    "SET search_path TO market, public",
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
        "key" VARCHAR(128) PRIMARY KEY,
        value VARCHAR(1024) NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS security_master (
        ticker CHAR(6) PRIMARY KEY,
        name VARCHAR(255), market VARCHAR(32), listing_date VARCHAR(10),
        listing_board VARCHAR(128), industry VARCHAR(255), industry_status VARCHAR(64),
        products TEXT, region VARCHAR(255), close DOUBLE PRECISION,
        open DOUBLE PRECISION, high DOUBLE PRECISION, low DOUBLE PRECISION,
        volume BIGINT, amount BIGINT, market_cap BIGINT, shares BIGINT,
        change_ratio DOUBLE PRECISION, source VARCHAR(255) NOT NULL,
        retrieved_at VARCHAR(40) NOT NULL,
        CONSTRAINT chk_security_ticker CHECK (ticker ~ '^[0-9]{6}$')
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_security_market ON security_master(market)",
    "CREATE INDEX IF NOT EXISTS idx_security_industry ON security_master(industry)",
    """
    CREATE TABLE IF NOT EXISTS ohlcv_daily (
        ticker CHAR(6) NOT NULL, trade_date VARCHAR(10) NOT NULL,
        open DOUBLE PRECISION NOT NULL, high DOUBLE PRECISION NOT NULL,
        low DOUBLE PRECISION NOT NULL, close DOUBLE PRECISION NOT NULL,
        volume BIGINT NOT NULL, change_ratio DOUBLE PRECISION,
        source VARCHAR(255) NOT NULL, adjusted SMALLINT NOT NULL,
        retrieved_at VARCHAR(40) NOT NULL, source_url TEXT,
        PRIMARY KEY (ticker, trade_date),
        CONSTRAINT chk_ohlcv_ticker CHECK (ticker ~ '^[0-9]{6}$'),
        CONSTRAINT chk_ohlcv_adjusted CHECK (adjusted IN (0, 1)),
        CONSTRAINT chk_ohlcv_volume CHECK (volume >= 0),
        CONSTRAINT chk_ohlcv_high CHECK (high >= open AND high >= low AND high >= close),
        CONSTRAINT chk_ohlcv_low CHECK (low <= open AND low <= high AND low <= close)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ohlcv_trade_date ON ohlcv_daily(trade_date)",
    """
    CREATE TABLE IF NOT EXISTS ohlcv_history_runs (
        run_id CHAR(36) PRIMARY KEY, requested_start VARCHAR(10) NOT NULL,
        requested_end VARCHAR(10) NOT NULL, status VARCHAR(16) NOT NULL,
        source VARCHAR(512) NOT NULL, tickers_requested INTEGER NOT NULL,
        tickers_selected INTEGER NOT NULL, tickers_attempted INTEGER NOT NULL DEFAULT 0,
        tickers_completed INTEGER NOT NULL DEFAULT 0,
        tickers_failed INTEGER NOT NULL DEFAULT 0,
        rows_written BIGINT NOT NULL DEFAULT 0, started_at VARCHAR(40) NOT NULL,
        finished_at VARCHAR(40), last_ticker CHAR(6), error_summary TEXT,
        CONSTRAINT chk_history_run_status
            CHECK (status IN ('running', 'partial', 'completed', 'failed')),
        CONSTRAINT chk_history_run_counts CHECK (
            tickers_requested >= 0 AND tickers_selected >= 0
            AND tickers_attempted >= 0 AND tickers_completed >= 0
            AND tickers_failed >= 0 AND rows_written >= 0
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ohlcv_history_attempts (
        run_id CHAR(36) NOT NULL, ticker CHAR(6) NOT NULL,
        requested_start VARCHAR(10) NOT NULL, requested_end VARCHAR(10) NOT NULL,
        status VARCHAR(16) NOT NULL, rows_written BIGINT NOT NULL DEFAULT 0,
        source VARCHAR(512), fallback_used SMALLINT, started_at VARCHAR(40) NOT NULL,
        finished_at VARCHAR(40), error_message TEXT,
        coverage_version INTEGER NOT NULL DEFAULT 0, coverage_json TEXT,
        PRIMARY KEY (run_id, ticker),
        CONSTRAINT fk_history_attempt_run FOREIGN KEY (run_id)
            REFERENCES ohlcv_history_runs(run_id),
        CONSTRAINT chk_history_attempt_status
            CHECK (status IN ('running', 'completed', 'failed')),
        CONSTRAINT chk_history_attempt_fallback CHECK (fallback_used IN (0, 1)),
        CONSTRAINT chk_history_attempt_rows CHECK (rows_written >= 0)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ohlcv_history_coverage
    ON ohlcv_history_attempts(ticker, status, requested_start, requested_end)
    """,
    """
    CREATE TABLE IF NOT EXISTS ohlcv_quality_events (
        event_id VARCHAR(128) PRIMARY KEY, ticker CHAR(6) NOT NULL,
        trade_date VARCHAR(10) NOT NULL, source VARCHAR(255) NOT NULL,
        source_url TEXT NOT NULL, action VARCHAR(64) NOT NULL,
        policy_version INTEGER NOT NULL, raw_json TEXT NOT NULL,
        normalized_json TEXT, retrieved_at VARCHAR(40) NOT NULL,
        CONSTRAINT chk_quality_ticker CHECK (ticker ~ '^[0-9]{6}$'),
        CONSTRAINT chk_quality_action CHECK (action IN (
            'no_trade_placeholder', 'bounds_adjusted_1krw',
            'bounds_adjusted_tick', 'bounds_adjusted_sub1000_rounding',
            'bounds_adjusted_provider_envelope', 'nonpositive_price_row_excluded'
        ))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ohlcv_quality_ticker_date
    ON ohlcv_quality_events(ticker, trade_date)
    """,
    """
    CREATE TABLE IF NOT EXISTS technical_indicators_daily (
        ticker CHAR(6) NOT NULL, trade_date VARCHAR(10) NOT NULL,
        close DOUBLE PRECISION NOT NULL, observations INTEGER NOT NULL,
        ema_5 DOUBLE PRECISION, ema_10 DOUBLE PRECISION, ema_15 DOUBLE PRECISION,
        ema_33 DOUBLE PRECISION, ema_56 DOUBLE PRECISION, ema_112 DOUBLE PRECISION,
        ema_224 DOUBLE PRECISION, ema_448 DOUBLE PRECISION,
        prior_high_52w DOUBLE PRECISION, high_52w DOUBLE PRECISION,
        distance_from_52w_high_pct DOUBLE PRECISION, is_52w_high SMALLINT,
        is_52w_breakout SMALLINT, ema_alignment VARCHAR(16) NOT NULL,
        close_above_ema5 SMALLINT, formula_version INTEGER NOT NULL,
        calculated_at VARCHAR(40) NOT NULL,
        PRIMARY KEY (ticker, trade_date),
        CONSTRAINT fk_technical_daily_ohlcv FOREIGN KEY (ticker, trade_date)
            REFERENCES ohlcv_daily(ticker, trade_date) ON DELETE CASCADE,
        CONSTRAINT chk_technical_daily_flags CHECK (
            is_52w_high IN (0, 1) AND is_52w_breakout IN (0, 1)
            AND close_above_ema5 IN (0, 1)
        )
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_technical_daily_date
    ON technical_indicators_daily(trade_date)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_technical_daily_alignment
    ON technical_indicators_daily(trade_date, ema_alignment)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_technical_daily_breakout
    ON technical_indicators_daily(trade_date, is_52w_breakout)
    """,
    """
    CREATE TABLE IF NOT EXISTS technical_indicators_weekly (
        ticker CHAR(6) NOT NULL, week_end VARCHAR(10) NOT NULL,
        last_trade_date VARCHAR(10) NOT NULL, open DOUBLE PRECISION NOT NULL,
        high DOUBLE PRECISION NOT NULL, low DOUBLE PRECISION NOT NULL,
        close DOUBLE PRECISION NOT NULL, volume BIGINT NOT NULL,
        trading_days INTEGER NOT NULL, previous_close DOUBLE PRECISION,
        weekly_return_pct DOUBLE PRECISION, bb_mid_20 DOUBLE PRECISION,
        bb_upper_20_2 DOUBLE PRECISION, bb_lower_20_2 DOUBLE PRECISION,
        is_bb_upper_breakout SMALLINT, formula_version INTEGER NOT NULL,
        calculated_at VARCHAR(40) NOT NULL,
        PRIMARY KEY (ticker, week_end),
        CONSTRAINT chk_technical_weekly_flag CHECK (is_bb_upper_breakout IN (0, 1))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_technical_weekly_end
    ON technical_indicators_weekly(week_end)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_technical_weekly_breakout
    ON technical_indicators_weekly(week_end, is_bb_upper_breakout)
    """,
    """
    CREATE TABLE IF NOT EXISTS technical_indicator_state (
        ticker CHAR(6) PRIMARY KEY, formula_version INTEGER NOT NULL,
        input_row_count BIGINT NOT NULL, input_first_date VARCHAR(10) NOT NULL,
        input_last_date VARCHAR(10) NOT NULL, input_max_retrieved_at VARCHAR(40) NOT NULL,
        daily_rows BIGINT NOT NULL, weekly_rows BIGINT NOT NULL,
        history_ready_448 SMALLINT NOT NULL, calculated_at VARCHAR(40) NOT NULL,
        CONSTRAINT chk_technical_state_flag CHECK (history_ready_448 IN (0, 1))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS screen_runs (
        run_id CHAR(36) PRIMARY KEY, as_of_date VARCHAR(10) NOT NULL,
        comparison_ticker CHAR(6), formula_version INTEGER NOT NULL,
        universe_count INTEGER NOT NULL, ema_similarity_count INTEGER NOT NULL,
        high_52w_count INTEGER NOT NULL, bollinger_breakout_count INTEGER NOT NULL,
        weekly_return_count INTEGER NOT NULL, output_directory TEXT NOT NULL,
        generated_at VARCHAR(40) NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_screen_runs_date
    ON screen_runs(as_of_date, generated_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS screen_results (
        run_id CHAR(36) NOT NULL, screen_type VARCHAR(32) NOT NULL,
        "rank" INTEGER NOT NULL, ticker CHAR(6) NOT NULL, name VARCHAR(255),
        market VARCHAR(32), industry VARCHAR(255), trade_date VARCHAR(10) NOT NULL,
        close DOUBLE PRECISION NOT NULL, volume BIGINT NOT NULL,
        estimated_trading_value DOUBLE PRECISION NOT NULL,
        daily_return_pct DOUBLE PRECISION, score DOUBLE PRECISION,
        ema_distance_pct DOUBLE PRECISION, ema_similarity_score DOUBLE PRECISION,
        ema_alignment VARCHAR(16), alignment_match SMALLINT,
        prior_high_52w DOUBLE PRECISION, high_52w DOUBLE PRECISION,
        distance_from_52w_high_pct DOUBLE PRECISION, is_52w_high SMALLINT,
        is_52w_breakout SMALLINT, week_end VARCHAR(10),
        weekly_last_trade_date VARCHAR(10), weekly_close DOUBLE PRECISION,
        weekly_return_pct DOUBLE PRECISION, bb_upper_20_2 DOUBLE PRECISION,
        is_bb_upper_breakout SMALLINT,
        PRIMARY KEY (run_id, screen_type, ticker),
        CONSTRAINT uq_screen_result_rank UNIQUE (run_id, screen_type, "rank"),
        CONSTRAINT fk_screen_result_run FOREIGN KEY (run_id)
            REFERENCES screen_runs(run_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_screen_results_lookup
    ON screen_results(screen_type, trade_date, "rank")
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_screen_results_ticker
    ON screen_results(ticker, trade_date)
    """,
    """
    CREATE TABLE IF NOT EXISTS artifacts (
        artifact_id CHAR(36) PRIMARY KEY, relative_path VARCHAR(512) NOT NULL UNIQUE,
        kind VARCHAR(32) NOT NULL, title VARCHAR(512) NOT NULL, ticker CHAR(6),
        company_name VARCHAR(255), report_date VARCHAR(10) NOT NULL,
        sha256 CHAR(64) NOT NULL, metadata_json TEXT NOT NULL,
        created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_artifacts_ticker_date
    ON artifacts(ticker, report_date)
    """,
    """
    CREATE TABLE IF NOT EXISTS artifact_views (
        artifact_id CHAR(36) NOT NULL, view_type VARCHAR(32) NOT NULL,
        view_key VARCHAR(128) NOT NULL, sector_id VARCHAR(128) NOT NULL DEFAULT '',
        PRIMARY KEY (artifact_id, view_type, view_key, sector_id),
        CONSTRAINT fk_artifact_view_artifact FOREIGN KEY (artifact_id)
            REFERENCES artifacts(artifact_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_artifact_views_lookup
    ON artifact_views(view_type, view_key, sector_id)
    """,
)

POSTGRESQL_FINANCIAL_SCHEMA = (
    "CREATE SCHEMA IF NOT EXISTS financial",
    """
    CREATE TABLE IF NOT EXISTS financial.schema_meta (
        "key" VARCHAR(128) PRIMARY KEY,
        value VARCHAR(1024) NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS financial.company_master (
        corp_code CHAR(8) PRIMARY KEY,
        ticker CHAR(6),
        corp_name VARCHAR(255) NOT NULL,
        corp_name_eng VARCHAR(255),
        market VARCHAR(32),
        modified_at DATE,
        source VARCHAR(64) NOT NULL DEFAULT 'OPENDART',
        source_url TEXT NOT NULL,
        retrieved_at TIMESTAMPTZ NOT NULL,
        CONSTRAINT chk_financial_corp_code CHECK (corp_code ~ '^[0-9]{8}$'),
        CONSTRAINT chk_financial_ticker CHECK (ticker IS NULL OR ticker ~ '^[0-9]{6}$')
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_financial_company_ticker
    ON financial.company_master(ticker) WHERE ticker IS NOT NULL
    """,
    """
    CREATE TABLE IF NOT EXISTS financial.filings (
        receipt_no CHAR(14) PRIMARY KEY,
        corp_code CHAR(8) NOT NULL,
        report_code CHAR(5),
        report_name TEXT NOT NULL,
        filing_date DATE NOT NULL,
        fiscal_year SMALLINT,
        fiscal_period VARCHAR(16),
        statement_scope VARCHAR(8),
        is_amended BOOLEAN NOT NULL DEFAULT FALSE,
        amended_from CHAR(14),
        source VARCHAR(64) NOT NULL DEFAULT 'OPENDART',
        source_url TEXT NOT NULL,
        retrieved_at TIMESTAMPTZ NOT NULL,
        raw_json JSONB,
        CONSTRAINT fk_financial_filing_company FOREIGN KEY (corp_code)
            REFERENCES financial.company_master(corp_code)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_financial_filings_company_date
    ON financial.filings(corp_code, filing_date DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS financial.statement_facts (
        fact_key CHAR(64) PRIMARY KEY,
        receipt_no CHAR(14) NOT NULL,
        corp_code CHAR(8) NOT NULL,
        fiscal_year SMALLINT NOT NULL,
        fiscal_period VARCHAR(16) NOT NULL,
        statement_scope VARCHAR(8) NOT NULL,
        statement_code VARCHAR(16) NOT NULL,
        account_id VARCHAR(255),
        account_name VARCHAR(500) NOT NULL,
        account_detail TEXT NOT NULL DEFAULT '',
        value_kind VARCHAR(32) NOT NULL DEFAULT 'current',
        period_start DATE,
        period_end DATE NOT NULL,
        amount NUMERIC(38, 4),
        currency VARCHAR(16),
        ordinal INTEGER,
        source VARCHAR(64) NOT NULL DEFAULT 'OPENDART',
        retrieved_at TIMESTAMPTZ NOT NULL,
        raw_json JSONB,
        CONSTRAINT fk_financial_fact_filing FOREIGN KEY (receipt_no)
            REFERENCES financial.filings(receipt_no) ON DELETE CASCADE,
        CONSTRAINT fk_financial_fact_company FOREIGN KEY (corp_code)
            REFERENCES financial.company_master(corp_code)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_financial_facts_company_period
    ON financial.statement_facts(corp_code, fiscal_year DESC, fiscal_period)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_financial_facts_account
    ON financial.statement_facts(account_id, account_name)
    """,
    """
    CREATE TABLE IF NOT EXISTS financial.notes (
        note_key CHAR(64) PRIMARY KEY,
        receipt_no CHAR(14) NOT NULL,
        section_code VARCHAR(128),
        section_title TEXT NOT NULL,
        content_text TEXT,
        raw_json JSONB,
        source VARCHAR(64) NOT NULL DEFAULT 'OPENDART',
        source_url TEXT NOT NULL,
        retrieved_at TIMESTAMPTZ NOT NULL,
        CONSTRAINT fk_financial_note_filing FOREIGN KEY (receipt_no)
            REFERENCES financial.filings(receipt_no) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_financial_notes_filing
    ON financial.notes(receipt_no)
    """,
    """
    CREATE TABLE IF NOT EXISTS financial.ingestion_runs (
        run_id UUID PRIMARY KEY,
        started_at TIMESTAMPTZ NOT NULL,
        finished_at TIMESTAMPTZ,
        status VARCHAR(16) NOT NULL,
        fiscal_year SMALLINT,
        fiscal_period VARCHAR(16),
        companies_requested INTEGER NOT NULL DEFAULT 0,
        companies_completed INTEGER NOT NULL DEFAULT 0,
        facts_written BIGINT NOT NULL DEFAULT 0,
        notes_written BIGINT NOT NULL DEFAULT 0,
        error_summary TEXT,
        CONSTRAINT chk_financial_run_status
            CHECK (status IN ('running', 'partial', 'completed', 'failed'))
    )
    """,
)
