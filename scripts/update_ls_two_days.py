from __future__ import annotations
import argparse,datetime as dt,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from krx_research.collectors.ls_index_api import LSIndexClient
from krx_research.data_engine.config import DataEngineSettings
from krx_research.data_engine.postgresql import BaseDataRepository
from ls_two_day_source import DDL,collect
from ls_two_day_rate import RateLimitedClient
from diagnose_ls_two_days import write_report
DAYS=(dt.date(2026,9,28),dt.date(2026,9,29))

def plans(prices,master):
    master=master.copy()
    master['market']=master['market'].astype(str).str.upper().str.strip()
    master=master.loc[master['market'].isin(('KOSPI','KOSDAQ'))]
    master=master.loc[~master['stock_name'].fillna('').astype(str).str.contains('스팩|SPAC|기업인수목적',case=False)]
    allowed=set(master['stock_code'].astype(str))
    result={}
    for row in prices.to_dict('records'):
        code=str(row['stock_code']).strip().upper()
        day=dt.date.fromisoformat(str(row['trade_date'])[:10])
        if code in allowed and day in DAYS and len(code)==6 and code.isascii() and code.isalnum():
            result.setdefault(code,set()).add(day)
    return {code:sorted(days) for code,days in sorted(result.items())}

def main():
    os.chdir(ROOT)
    p=argparse.ArgumentParser()
    p.add_argument('--ticker',help='Optional single numeric/alphanumeric stock code')
    p.add_argument('--refresh',action='store_true',help='Refetch only these two days, including completed rows')
    args=p.parse_args()
    began=time.monotonic()
    with BaseDataRepository(DataEngineSettings.from_environment(),application_name='ls_two_days') as repo:
        with repo.conn.transaction():repo.conn.execute(DDL)
        if not repo.conn.execute('SELECT pg_try_advisory_lock(76340928029) AS acquired').fetchone()['acquired']:
            raise RuntimeError('Another two-day investor collector is running. Do not start a duplicate.')
        write_report(repo)
        prices=repo.get_market_ohlcv(DAYS[0],DAYS[-1])
        todo=plans(prices,repo.get_security_master_frame())
        if args.ticker:
            code=args.ticker.strip().upper()
            if code not in todo:raise ValueError('Selected stock has no saved candle for these dates.')
            todo={code:todo[code]}
        # Verify four raw source matrices rather than trusting a stale checkpoint.
        done={}
        for row in repo.conn.execute("SELECT stock_code,trade_date FROM market_core.ls_investor_t1702_raw WHERE exchange_code='K' AND trade_date IN (%s,%s) GROUP BY stock_code,trade_date HAVING count(DISTINCT (metric_code,side_code))=4",DAYS).fetchall():
            done.setdefault(row['stock_code'],set()).add(row['trade_date'])
        with repo.conn.transaction():
            for code,days in done.items():
                for day in days:
                    repo.conn.execute("INSERT INTO market_core.ls_investor_t1702_checkpoint(stock_code,trade_date,exchange_code) VALUES (%s,%s,'K') ON CONFLICT DO NOTHING",(code,day))
        skipped=0
        if not args.refresh:
            for code in list(todo):
                pending=[d for d in todo[code] if d not in done.get(code,set())]
                skipped+=len(todo[code])-len(pending)
                todo[code]=pending
                if not pending:del todo[code]
        print(f'LS ONLY / KRX venue / 2026-09-28,29 / pending {len(todo)} stocks / completed skipped {skipped} stock-days',flush=True)
        print('Saved dates/matrices skipped; adaptive pacing recovers after successful requests.',flush=True)
        if not todo:
            print('No missing stock-days. Read the existing screening display.');return 0
        saved=missing=0
        with LSIndexClient() as transport:
            client=RateLimitedClient(transport)
            for pos,(code,days) in enumerate(todo.items(),1):
                print(f'[{pos}/{len(todo)}] {code}: request two-day range',flush=True)
                try:
                    keys={(r['trade_date'],r['metric_code'],r['side_code']) for r in repo.conn.execute("SELECT trade_date,metric_code,side_code FROM market_core.ls_investor_t1702_raw WHERE stock_code=%s AND exchange_code='K' AND trade_date IN (%s,%s)",(code,*DAYS)).fetchall()} if not args.refresh else set()
                    found,complete=collect(client,code,days,keys)
                    with repo.conn.transaction():
                        for (day,metric,side),fields in found.items():
                            repo.conn.execute("INSERT INTO market_core.ls_investor_t1702_raw (stock_code,trade_date,metric_code,side_code,exchange_code,source_fields) VALUES (%s,%s,%s,%s,'K',%s::jsonb) ON CONFLICT(stock_code,trade_date,metric_code,side_code,exchange_code) DO UPDATE SET source_fields=EXCLUDED.source_fields,collected_at=now()",(code,day,metric,side,json.dumps(fields,ensure_ascii=False)))
                        for day in complete:
                            repo.conn.execute("INSERT INTO market_core.ls_investor_t1702_checkpoint(stock_code,trade_date,exchange_code) VALUES (%s,%s,'K') ON CONFLICT DO NOTHING",(code,day))
                    saved+=len(complete);missing+=len(days)-len(complete)
                    if len(days)!=len(complete):print(f'{code}: missing {len(days)-len(complete)} days; NOT marked complete',flush=True)
                except Exception as error:
                    print(f'ERROR {code}: {type(error).__name__}: {error}. Saved rows preserved; rerun resumes.',flush=True)
                    write_report(repo)
                    return 2
                elapsed=time.monotonic()-began
                eta=elapsed/pos*(len(todo)-pos)
                print(f'[{pos}/{len(todo)}] saved {saved} stock-days / missing {missing} / ETA {eta/60:.1f} min',flush=True)
        write_report(repo)
        print(f'DONE: saved {saved}, skipped {skipped}, missing {missing}. Refresh the display.')
        return 2 if missing else 0
if __name__=='__main__':raise SystemExit(main())
