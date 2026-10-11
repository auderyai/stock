import datetime as dt
DDL = '''
CREATE SCHEMA IF NOT EXISTS market_core;
CREATE TABLE IF NOT EXISTS market_core.ls_investor_t1702_raw (
 stock_code varchar(6) NOT NULL,
 trade_date date NOT NULL,
 metric_code char(1) NOT NULL CHECK (metric_code IN ('0','1')),
 side_code char(1) NOT NULL CHECK (side_code IN ('1','2')),
 exchange_code char(1) NOT NULL DEFAULT 'K',
 source_fields jsonb NOT NULL,
 collected_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(stock_code,trade_date,metric_code,side_code,exchange_code)
);
CREATE TABLE IF NOT EXISTS market_core.ls_investor_t1702_checkpoint (
 stock_code varchar(6) NOT NULL,
 trade_date date NOT NULL,
 exchange_code char(1) NOT NULL,
 completed_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(stock_code,trade_date,exchange_code)
);
'''

def collect(client, code, days, saved_keys=()):
    first,last = days[0],days[-1]
    expected=set(days)
    found={}
    saved=set(saved_keys)
    for metric in ('0','1'):
        for side in ('1','2'):
            if all((day,metric,side) in saved for day in days):continue
            block={'fromdt':first.strftime('%Y%m%d'), 'shcode':code,
                   'todt':last.strftime('%Y%m%d'), 'volvalgb':metric,
                   'msmdgb':side, 'gubun':'0', 'exchgubun':'K'}
            response=client._call('t1702','/stock/frgr-itt',block)
            rows=response.get('t1702OutBlock1')
            if not isinstance(rows,list):
                raise ValueError(f'{code}: t1702OutBlock1 없음')
            for row in rows:
                if not isinstance(row,dict):
                    continue
                stamp=str(row.get('date') or '').strip()
                try:
                    day=dt.datetime.strptime(stamp,'%Y%m%d').date()
                except ValueError:
                    continue
                if day in expected and any(str(row.get(k) or '').strip() for k in row if k.startswith('tjj')):
                    found[(day,metric,side)] = row
    # Never claim a complete day if any of the four source matrices is missing.
    complete=[day for day in days if all((day,m,s) in found or (day,m,s) in saved for m in ('0','1') for s in ('1','2'))]
    return found,complete
