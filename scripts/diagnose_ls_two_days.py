import datetime as dt,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from krx_research.data_engine.config import DataEngineSettings
from krx_research.data_engine.postgresql import BaseDataRepository
import pandas as pd
DAYS=(dt.date(2026,9,28),dt.date(2026,9,29))

def write_report(repo):
    exists=repo.conn.execute("SELECT to_regclass('market_core.ls_investor_t1702_raw') AS t").fetchone()
    report={'dates':[],'note':'DB-only diagnostics. No credentials, tokens or API calls. Amounts are not estimated.'}
    if not exists['t']:
        report['error']='LS raw table missing'
    else:
        for day in DAYS:
            prices=repo.get_market_ohlcv(day,day)
            amounts={str(r['stock_code']):str(r.get('amount')) for r in prices.to_dict('records')}
            count=repo.conn.execute("SELECT count(*) AS rows,count(DISTINCT stock_code) AS stocks FROM market_core.ls_investor_t1702_raw WHERE trade_date=%s AND exchange_code='K'",(day,)).fetchone()
            sample=repo.conn.execute("SELECT stock_code,trade_date,metric_code,side_code,source_fields FROM market_core.ls_investor_t1702_raw WHERE trade_date=%s AND exchange_code='K' AND stock_code IN (SELECT DISTINCT stock_code FROM market_core.ls_investor_t1702_raw WHERE trade_date=%s AND exchange_code='K' ORDER BY stock_code LIMIT 5) ORDER BY stock_code,metric_code,side_code",(day,day)).fetchall()
            entry={'date':str(day),'raw_rows':count['rows'],'raw_stocks':count['stocks'],'daily_price_stocks':len(amounts),'samples':[]}
            try:
                flow=repo.get_ls_investor_flow(trade_date=day)
                entry['displayable_stocks']=int(flow['stock_code'].nunique()) if not flow.empty else 0
                entry['display_attrs']=dict(flow.attrs)
            except Exception as e:entry['display_error']=str(e)
            for row in sample:
                fields=row['source_fields']
                entry['samples'].append({'stock_code':row['stock_code'],'metric_code':row['metric_code'],'side_code':row['side_code'],'db_turnover_krw':amounts.get(row['stock_code']),'ls_fields':fields})
            report['dates'].append(entry)
    path=ROOT/'logs/ls_two_days_diagnostic.json';path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print('DB diagnostic saved:',path,flush=True)
    for entry in report['dates']:print(entry['date'],'raw stocks',entry['raw_stocks'],'displayable',entry.get('displayable_stocks','ERROR'),flush=True)
    return path
if __name__=='__main__':
    with BaseDataRepository(DataEngineSettings.from_environment(),application_name='ls_two_days_diagnostic') as repo:write_report(repo)
