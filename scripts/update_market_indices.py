"""Incrementally load official KOSPI/KOSDAQ indices into PostgreSQL."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from krx_research.data_engine.config import DataEngineSettings
from krx_research.data_engine.postgresql import BaseDataRepository
from krx_research.data_engine.market_indices import ensure_schema
from krx_research.collectors.ls_index_api import LSIndexClient


def load_krx_credentials(project_root: Path) -> bool:
    """Load existing account settings without overriding process credentials."""
    for path in (project_root / '.env', project_root / 'config' / 'krx.env'):
        if not path.is_file():
            continue
        for raw in path.read_text(encoding='utf-8-sig').splitlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            name, sep, value = line.partition('=')
            name = name.strip()
            if not sep or name not in ('KRX_ID', 'KRX_PW'):
                continue
            value = value.strip()
            if value.startswith('"'):
                value = json.loads(value)
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1]
            if value:
                os.environ.setdefault(name, value)
    return bool(os.environ.get('KRX_ID') and os.environ.get('KRX_PW'))


def ls_value_multiplier(project_root: Path) -> int:
    """Allow the broker's raw amount unit to be configured without changing code."""
    import json
    value = os.getenv('LS_INDEX_VALUE_WON_MULTIPLIER', '').strip()
    if not value:
        for config in (project_root / '.env', project_root / 'config' / 'xingapi.env'):
            if config.is_file():
                for raw in config.read_text(encoding='utf-8-sig').splitlines():
                    name, sep, field = raw.strip().partition('=')
                    if sep and name == 'LS_INDEX_VALUE_WON_MULTIPLIER':
                        field = field.strip()
                        value = str(json.loads(field)) if field.startswith('"') else field
                        break
            if value:
                break
    factor = int(value or '1000000')
    if factor <= 0:
        raise ValueError('LS_INDEX_VALUE_WON_MULTIPLIER는 양의 정수여야 합니다.')
    return factor

# Known KRX sector codes, used when the live pykrx index directory is unavailable.
# Codes are still verified by the data request; failed indices never receive fake bars.
SECTOR_CODES = {
    'KOSPI': ('1005','1006','1007','1008','1009','1010','1011','1012','1013',
              '1014','1015','1016','1017','1018','1019','1020','1021','1022',
              '1024','1025','1026','1027','1150','1151','1152','1153','1154',
              '1155','1156','1157','1158','1159','1160'),
    'KOSDAQ': ('2012','2015','2024','2026','2027','2029','2031','2037','2041',
               '2042','2043','2056','2058','2062','2063','2065','2066','2067',
               '2068','2070','2072','2074','2075','2077','2151','2152','2153',
               '2154','2155','2156','2157','2158','2159','2160','2212','2213',
               '2214','2215','2216','2217','2218'),
}


def chunks(start: dt.date, end: dt.date):
    while start <= end:
        stop = min(dt.date(start.year, 12, 31), end)
        yield start, stop
        start = stop + dt.timedelta(days=1)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='KRX 종합·업종 지수 과거 일봉 저장')
    parser.add_argument('--start', type=dt.date.fromisoformat, default=dt.date(2010, 1, 4))
    parser.add_argument('--end', type=dt.date.fromisoformat, default=dt.date.today())
    parser.add_argument('--delay', type=float, default=.5)
    parser.add_argument('--recent-days', type=int, default=0,
                        help='빠른 화면 확인용 최근 일수 (0=DB 최초일 전체 갱신)')
    parser.add_argument('--full-refresh', action='store_true',
                        help='기존 지수도 DB의 첫 거래일부터 다시 수집')
    args = parser.parse_args(argv)
    if args.start > args.end or args.recent_days < 0:
        parser.error('시작일이 종료일보다 늦습니다.')
    multiplier = ls_value_multiplier(ROOT)
    has_krx_login = load_krx_credentials(ROOT)
    stock = None
    if has_krx_login:
        try:
            from pykrx import stock
        except Exception as error:
            print(f'KRX 로그인 실패 ({type(error).__name__}): pykrx 지수 조회를 건너뛰고 LS·FinanceDataReader로 진행합니다.', file=sys.stderr, flush=True)
    else:
        print('KRX 로그인 정보 없음: LS·FinanceDataReader로 지수를 갱신합니다.', flush=True)
    failures = []
    inserted = 0
    ls_client = None
    ls_sectors = {}
    try:
        ls_client = LSIndexClient(delay=args.delay)
        ls_sectors = ls_client.sectors()
        print('LS xingAPI t8424/t8429: 종합·업종 지수 우선 수집', flush=True)
    except Exception as error:
        if ls_client is not None:
            ls_client.close()
        ls_client = None
        ls_sectors = {}
        print(f'LS xingAPI 지수 사용 불가: {type(error).__name__}; 기존 지수 자료원 사용', file=sys.stderr)
    if not ls_sectors and not has_krx_login:
        print('업종 지수의 인증된 자료원이 없습니다. 종합지수만 갱신합니다.', file=sys.stderr)
    with BaseDataRepository(DataEngineSettings.from_environment(),
                            application_name='krx_index_update') as repo:
        conn = repo.conn
        ensure_schema(conn)
        for market in ('KOSPI', 'KOSDAQ'):
            # The selected end date avoids asking the source for future indices.
            composite = '1001' if market == 'KOSPI' else '2001'
            if stock is None or ls_sectors:
                codes = [composite]
            else:
                try:
                    codes = stock.get_index_ticker_list(args.end.strftime('%Y%m%d'), market=market)
                except Exception as exc:
                    print(f'{market} 업종 목록 조회 실패: {exc}; 종합지수는 보조 경로로 시도합니다.',file=sys.stderr)
                    failures.append(f'{market}: 업종 목록 조회 실패')
                    codes = list(SECTOR_CODES[market])
                allowed = {composite, *SECTOR_CODES[market]}
                codes = list(dict.fromkeys([composite, *SECTOR_CODES[market],
                                                *(c for c in codes if c in allowed)]))
            if ls_sectors:
                prefix = '0' if market == 'KOSPI' else '3'
                codes.extend('L' + code for code in ls_sectors if code[0] == prefix and code not in ('001', '301'))
            codes = list(dict.fromkeys(codes))
            if not codes:
                failures.append(f'{market}: 지수 목록이 비어 있습니다')
                continue
            consecutive_errors = 0
            for code in codes:
                try:
                    try:
                        name = ls_sectors[code[1:]] if code.startswith('L') else (
                            stock.get_index_ticker_name(code) if stock else market
                        )
                        name = name or code
                    except Exception:
                        name = market if code == composite else code
                    conn.execute('''INSERT INTO market_core.index_master(index_code,market,index_name)
                      VALUES (%s,%s,%s) ON CONFLICT(index_code) DO UPDATE SET
                      market=EXCLUDED.market,index_name=EXCLUDED.index_name,updated_at=now()''',
                      (code,market,name))
                    existing = conn.execute('''SELECT MIN(trade_date) AS first_date,MAX(trade_date) AS last_date
                      FROM market_core.index_ohlcv_daily WHERE index_code=%s''',(code,)).fetchone()
                    first_date = existing['first_date']
                    # Existing indices are refreshed from their oldest saved bar.
                    # --start only controls the initial load of a new index.
                    # Initial load is complete history; later runs append from the last
                    # saved date, including that day to allow late source corrections.
                    history_start = (first_date if args.full_refresh and first_date is not None else
                                     existing['last_date'] if existing['last_date'] is not None else args.start)
                    if args.recent_days:
                        history_start = max(history_start, args.end - dt.timedelta(days=args.recent_days))
                    spans = list(chunks(history_start, args.end))
                    print(f'{market} {name}: DB 시작일 {history_start} ~ {args.end} '
                          f'({len(spans)}개 연도 구간)', flush=True)
                    saved_for_code = 0
                    for first, final in spans:
                        try:
                            origin = 'LS_XING:t8429'
                            ls_code = ('001' if market == 'KOSPI' else '301') if code == composite else (
                                code[1:] if code.startswith('L') else None
                            )
                            frame = pd.DataFrame()
                            if ls_client is not None and ls_code is not None:
                                try:
                                    frame = ls_client.candles(ls_code, first, final)
                                except Exception as error:
                                    print(f'LS {market} {code}: {type(error).__name__}; 보조 자료원 시도', file=sys.stderr)
                            if (frame is None or frame.empty) and code == composite:
                                try:
                                    import FinanceDataReader as fdr
                                    symbol = 'KS11' if market == 'KOSPI' else 'KQ11'
                                    frame = fdr.DataReader(symbol, first.isoformat(),
                                                           (final + dt.timedelta(days=1)).isoformat())
                                    if frame is not None and not frame.empty:
                                        frame = frame.rename(columns={'Open':'시가','High':'고가',
                                                                       'Low':'저가','Close':'종가','Volume':'거래량'})
                                        origin = 'FinanceDataReader'
                                except Exception as error:
                                    print(f'FinanceDataReader {market} {code}: {type(error).__name__}; pykrx 시도', file=sys.stderr)
                                    frame = pd.DataFrame()
                            if (frame is None or frame.empty) and stock is not None and not code.startswith('L'):
                                try:
                                    frame = stock.get_index_ohlcv(first.strftime('%Y%m%d'),final.strftime('%Y%m%d'),code)
                                    if frame is not None and not frame.empty:
                                        origin = 'pykrx'
                                except Exception:
                                    frame = pd.DataFrame()
                            if frame is None or frame.empty:
                                # Empty source responses can be transient; leave checkpoint unchanged.
                                print(f'{market} {code} {first}~{final}: 빈 응답', flush=True)
                                continue
                            amount_frame = frame
                            if '거래대금' not in frame.columns and stock is not None and not code.startswith('L'):
                                try:
                                    amount_frame = stock.get_index_ohlcv(
                                        first.strftime('%Y%m%d'), final.strftime('%Y%m%d'), code)
                                except Exception:
                                    amount_frame = pd.DataFrame()
                            if '거래대금' in amount_frame.columns:
                                amount_frame = amount_frame.copy()
                                amount_frame.index = pd.to_datetime(amount_frame.index).date
                            consecutive_errors = 0
                            records = []
                            for date, row in frame.iterrows():
                                day = dt.date.fromisoformat(str(date)[:10])
                                values = [row.get(c) for c in ('시가','고가','저가','종가')]
                                if any(pd.isna(v) or float(v) <= 0 for v in values):
                                    continue
                                volume = row.get('거래량')
                                actual_amount = None
                                if origin == 'LS_XING:t8429' and pd.notna(row.get('LS거래대금원시')):
                                    raw_amount = float(row['LS거래대금원시'])
                                    if raw_amount >= 0:
                                        actual_amount = raw_amount * multiplier
                                if '거래대금' in amount_frame.columns and day in amount_frame.index:
                                    actual_amount = amount_frame.loc[day, '거래대금']
                                    if pd.isna(actual_amount) or float(actual_amount) < 0:
                                        actual_amount = None
                                records.append((code,day,
                                  *[float(v) for v in values], int(volume) if pd.notna(volume) else None,
                                  float(actual_amount) if actual_amount is not None else None,origin))
                            if records:
                                with conn.transaction():
                                    with conn.cursor() as cursor:
                                        cursor.executemany('''INSERT INTO market_core.index_ohlcv_daily
                                          (index_code,trade_date,open_price,high_price,low_price,close_price,volume,trading_value,source)
                                          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                          ON CONFLICT(index_code,trade_date) DO UPDATE SET
                                          open_price=EXCLUDED.open_price,high_price=EXCLUDED.high_price,
                                          low_price=EXCLUDED.low_price,close_price=EXCLUDED.close_price,
                                          volume=EXCLUDED.volume,
                                          trading_value=COALESCE(EXCLUDED.trading_value,index_ohlcv_daily.trading_value),
                                          source=EXCLUDED.source,retrieved_at=now()''',records)
                                inserted += len(records)
                                saved_for_code += len(records)
                            print(f'{market} {name} {first}~{final}: {len(records)}건', flush=True)
                        except Exception as exc:
                            failures.append(f'{market} {code} {first}~{final}: {exc}')
                            consecutive_errors += 1
                            if consecutive_errors >= 3:
                                print(f'{market}: 지수 조회 연속 실패, 나머지 코드는 다음 실행에 재시도',file=sys.stderr)
                                break
                        time.sleep(max(0,args.delay))
                    if consecutive_errors >= 3:
                        break
                    if not first_date and not saved_for_code:
                        failures.append(f'{market} {code}: 조회 기간에 저장할 일봉 없음')
                except Exception as exc:
                    failures.append(f'{market} {code}: {exc}')
                    consecutive_errors += 1
                    if consecutive_errors >= 3:
                        break
    if ls_client is not None:
        ls_client.close()
    print(f'지수 갱신: {inserted:,}건 저장 / 오류 {len(failures)}건')
    for error in failures[:20]:
        print('오류:',error, file=sys.stderr)
    return 2 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
