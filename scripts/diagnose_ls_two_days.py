import datetime as dt,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from krx_research.data_engine.config import DataEngineSettings
from krx_research.database.administrative_repository import AdministrativeRepository
import pandas as pd
DAYS=(dt.date(2026,9,28),dt.date(2026,9,29))

def write_report(repo):
    report={'dates':[],'note':'DB-only diagnostics. No credentials, tokens or API calls. Amounts are not estimated.'}
    for day in DAYS:
        data=repo.ls_day(day)
        if data is None:
            report['error']='LS raw table missing';break
        amounts={str(r['stock_code']):str(r.get('amount')) for r in data['prices'].to_dict('records')}
        count=data['count'];flow=data['flow']
        entry={'date':str(day),'raw_rows':count['rows'],'raw_stocks':count['stocks'],'daily_price_stocks':len(amounts),'samples':[],
               'displayable_stocks':int(flow['stock_code'].nunique()) if not flow.empty else 0,'display_attrs':dict(flow.attrs)}
        for row in data['samples']:
            entry['samples'].append({'stock_code':row['stock_code'],'metric_code':row['metric_code'],'side_code':row['side_code'],'db_turnover_krw':amounts.get(row['stock_code']),'ls_fields':row['source_fields']})
        report['dates'].append(entry)
    path=ROOT/'logs/ls_two_days_diagnostic.json';path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print('DB diagnostic saved:',path,flush=True)
    for entry in report['dates']:print(entry['date'],'raw stocks',entry['raw_stocks'],'displayable',entry.get('displayable_stocks','ERROR'),flush=True)
    return path
if __name__=='__main__':
    with AdministrativeRepository(DataEngineSettings.from_environment(),application_name='ls_two_days_diagnostic') as repo:write_report(repo)
