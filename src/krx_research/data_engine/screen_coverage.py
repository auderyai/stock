"""Read-only cross-section coverage checks shared by GUI and daily updater."""
from __future__ import annotations
import datetime as dt
import math
import pandas as pd

def expected_market_counts(repository, day):
    master=repository.get_security_master_frame().copy()
    master['stock_code']=master['stock_code'].astype(str).str.zfill(6)
    master['market']=master['market'].astype(str).str.strip().str.upper()
    master=master.loc[master['market'].isin(('KOSPI','KOSDAQ'))]
    if 'stock_name' in master:
        master=master.loc[~master['stock_name'].fillna('').astype(str).str.contains('스팩|SPAC|기업인수목적',case=False)]
    raw=repository.get_market_ohlcv(day-dt.timedelta(days=35),day)
    if raw.empty:return {m:(0,int(master['market'].eq(m).sum())) for m in ('KOSPI','KOSDAQ')}
    raw=raw.copy();raw['stock_code']=raw['stock_code'].astype(str).str.zfill(6)
    raw['trade_date']=pd.to_datetime(raw['trade_date']).dt.date
    raw=raw.merge(master[['stock_code','market']].drop_duplicates('stock_code'),on='stock_code',how='inner')
    result={}
    for market in ('KOSPI','KOSDAQ'):
        group=raw.loc[raw['market'].eq(market)]
        actual=group.loc[group['trade_date'].eq(day),'stock_code'].nunique()
        prior=group.loc[group['trade_date'].lt(day)].groupby('trade_date')['stock_code'].nunique()
        expected=int(prior.tail(20).max()) if len(prior) else int(master['market'].eq(market).sum())
        result[market]=(int(actual),expected)
    return result

def validate_screen_coverage(repository, day, rows, markets, membership=None, minimum=50):
    counts=expected_market_counts(repository,day)
    for market in markets:
        actual,expected=counts[market]
        needed=max(minimum,math.ceil(expected*.9))
        if actual<needed:
            raise ValueError(f'{day} {market} 일봉 부분 저장: {actual}/{expected}종목. '
                             'LS 일봉 누락 복구를 완료한 뒤 다시 조회하십시오.')
    eligible=rows.loc[rows['market'].astype(str).str.strip().str.upper().isin(markets)]
    if membership is not None:
        codes={str(c).zfill(6) for c in membership.tickers}
        found=set(eligible['ticker'].astype(str).str.zfill(6)) & codes
        if len(found)<max(minimum,math.ceil(len(codes)*.9)):
            raise ValueError(f'{day} 지수 구성종목의 일봉 부분 저장: {len(found)}/{len(codes)}종목. LS 일봉 누락 복구가 필요합니다.')
    if len(eligible)<minimum:
        raise ValueError(f'{day} 계산 가능한 종목이 {len(eligible)}개로 Top {minimum} 자료가 부족합니다.')
