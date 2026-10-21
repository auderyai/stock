"""Shared immutable labels and source identifiers for every workstation UI."""

SCREEN_TITLES = {
    "ema_similarity": "이동평균 유사배열",
    "high_52w": "당일 52주 신고가",
    "near_high_52w": "52주 최고가 대비 종가 구간",
    "bollinger_breakout": "주봉 볼린저 돌파",
    "kospi_weekly_gainers": "KOSPI 주간 상승률 Top",
    "kosdaq_weekly_gainers": "KOSDAQ 주간 상승률 Top",
    "weekly_return": "KOSPI+KOSDAQ 주간 상승률 Top",
    "kospi200_daily_gainers": "KOSPI 200 당일 상승률 Top",
    "kosdaq150_daily_gainers": "KOSDAQ 150 당일 상승률 Top",
    "kospi200_kosdaq150_daily_gainers": "KOSPI 200+KOSDAQ 150 당일 상승률 Top",
    "kospi200_weekly_gainers": "KOSPI 200 주간 상승률 Top",
    "kosdaq150_weekly_gainers": "KOSDAQ 150 주간 상승률 Top",
    "kospi200_kosdaq150_weekly_gainers": "KOSPI 200+KOSDAQ 150 주간 상승률 Top",
    "kospi_daily_gainers": "KOSPI 전체 당일 상승률 Top",
    "kosdaq_daily_gainers": "KOSDAQ 전체 당일 상승률 Top",
    "kospi_kosdaq_daily_gainers": "KOSPI+KOSDAQ 당일 상승률 Top",
    "kospi_kosdaq_daily_trading_value": "KOSPI+KOSDAQ 당일 거래대금 Top",
    "kospi_weekly_trading_value": "KOSPI 거래대금 주간 Top",
    "kosdaq_weekly_trading_value": "KOSDAQ 거래대금 주간 Top",
    "kospi_kosdaq_weekly_trading_value": "KOSPI+KOSDAQ 거래대금 주간 Top",
}

DATABASE_SOURCE_MODE = "database"
REALTIME_SOURCE_MODE = "realtime"
DATA_SOURCE_MODES = frozenset({DATABASE_SOURCE_MODE, REALTIME_SOURCE_MODE})

TIMEFRAME_LABELS = {
    "D": "일봉",
    "W": "주봉",
    "M": "월봉",
    "Q": "분기봉",
    "Y": "년봉",
}
