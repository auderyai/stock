"""Fill only missing canonical daily candles from LS; preserve saved facts."""
from __future__ import annotations
import argparse
import datetime as dt
import os
from pathlib import Path
import sys
import time
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from krx_research.collectors.ls_index_api import LSIndexClient
from krx_research.collectors.ls_index_membership import fetch_ls_membership
from krx_research.collectors.xing_t8451 import XingT8451Client
from krx_research.data_engine.config import DataEngineSettings
from krx_research.data_engine.postgresql import BaseDataRepository
from krx_research.data_engine.screen_coverage import expected_market_counts

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--date',type=dt.date.fromisoformat,default=dt.date(2026,9,29))
    args=parser.parse_args(argv)
    os.chdir(ROOT)
    day=args.date;start=day-dt.timedelta(days=14)
    settings=DataEngineSettings.from_environment()
    with BaseDataRepository(settings,application_name='ls_screen_missing_day_repair') as repository:
        repository.initialize_schema()
        with LSIndexClient(project_root=ROOT) as client, XingT8451Client.from_environment(ROOT) as price_client:
            print('LS 전체 종목 목록 확인...',flush=True)
            doc=client._call('t8436','/stock/etc',{'gubun':'0'})
            listing=doc.get('t8436OutBlock')
            if not isinstance(listing,list):raise ValueError('LS t8436 종목 목록이 없습니다.')
            masters=[]
            for item in listing:
                code=str(item.get('shcode','')).strip()
                group=str(item.get('gubun','')).strip()
                etf=str(item.get('etfgubun','0')).strip()
                name=str(item.get('hname','')).strip()
                if not(len(code)==6 and code.isascii() and code.isalnum() and group in ('1','2')):continue
                if etf not in ('','0') or '스팩' in name or 'SPAC' in name.upper():continue
                masters.append({'stock_code':code,'stock_name':name,
                                'market':'KOSPI' if group=='1' else 'KOSDAQ','source':'LS:t8436'})
            if len(masters)<500:raise ValueError(f'LS 전체 종목 목록이 {len(masters)}개로 불완전합니다.')
            master=pd.DataFrame(masters).drop_duplicates('stock_code')
            repository.upsert_security_master(master)
            raw=repository.get_market_ohlcv(start,day)
            existing=set()
            if not raw.empty:
                existing={(str(row.stock_code).zfill(6),pd.Timestamp(row.trade_date).date())
                          for row in raw.itertuples(index=False)}
            # A prior close is required for day-on-day return, even when today's bar exists.
            previous_codes={code for code,stamp in existing if stamp<day}
            pending=[code for code in master['stock_code'] if (code,day) not in existing
                     or code not in previous_codes]
            print(f'{day} 누락 또는 전일 자료 부족 {len(pending)}종목; 이미 저장된 일봉은 건너뜁니다.',flush=True)
            started=time.monotonic();failed=[];stored=0;consecutive=0
            for position,code in enumerate(pending,1):
                began=time.monotonic()
                try:
                    frame=price_client.fetch(code,start,day,'KRX')
                    if frame.empty or not pd.to_datetime(frame['trade_date']).dt.date.eq(day).any():
                        failed.append(code)
                        print(f'[{position}/{len(pending)}] {code}: 기준일 LS 일봉 없음',flush=True)
                    else:
                        mask=[(str(row.stock_code).zfill(6),pd.Timestamp(row.trade_date).date()) not in existing
                              for row in frame.itertuples(index=False)]
                        frame=frame.loc[mask].copy()
                        stored+=repository.upsert_ohlcv(frame)
                        consecutive=0
                except Exception as error:
                    failed.append(code);consecutive+=1
                    print(f'{code}: {type(error).__name__}: {error}',flush=True)
                    if consecutive>=3:raise RuntimeError('연속 3개 LS 요청 실패로 중단합니다. 저장된 자료는 보존하며 재실행하면 이어받습니다.') from error
                elapsed=time.monotonic()-started
                if position==1 or position%10==0 or position==len(pending):
                    remaining=int(elapsed/position*(len(pending)-position))
                    print(f'[{position}/{len(pending)}] 저장 {stored}행 / 남은시간 추정 {remaining//60}분 {remaining%60}초',flush=True)
                wait=.65-(time.monotonic()-began)
                if wait>0:time.sleep(wait)
        counts=expected_market_counts(repository,day)
        for market,(actual,expected) in counts.items():
            print(f'{day} {market}: DB {actual}종목 / 이전 자료 기준 {expected}종목',flush=True)
        membership_errors=[]
        for kind in ('kospi200_daily_gainers','kosdaq150_daily_gainers'):
            try:
                membership=fetch_ls_membership(kind,day)
                print(f'{membership.index_name}: LS 구성종목 {len(membership.tickers)}개 저장',flush=True)
            except Exception as error:
                membership_errors.append(f'{kind}: {error}')
                print(f'지수 조회 미완료 (일봉 저장 유지): {kind}: {error}',flush=True)
        if membership_errors:
            log=ROOT/'logs/ls_membership_errors.txt'
            log.parent.mkdir(parents=True,exist_ok=True)
            log.write_text('\n'.join(membership_errors),encoding='utf-8')
        if any(actual<max(100,int(expected*.9)) for actual,expected in counts.values()):
            print('일봉 누락이 남았습니다. 완료로 처리하지 않습니다. 같은 파일을 재실행하면 누락만 조회합니다.',flush=True)
            return 2
        print('일봉 복구 완료. 지수 조회 실패가 있으면 RETRY_INDEX.cmd로 구성종목만 재시도하십시오.',flush=True)
        return 0

if __name__=='__main__':raise SystemExit(main())
