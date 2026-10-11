import datetime as dt
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from krx_research.collectors.ls_index_membership import fetch_ls_membership

def main():
    errors=[]
    for kind in ('kospi200_daily_gainers','kosdaq150_daily_gainers'):
        try:
            m=fetch_ls_membership(kind,dt.date(2026,9,29))
            print(f'{m.index_name}: {len(m.tickers)} constituents OK',flush=True)
        except Exception as error:
            errors.append(f'{kind}: {error}')
            print(errors[-1],flush=True)
    if errors:
        p=ROOT/'logs/ls_membership_errors.txt'
        p.parent.mkdir(exist_ok=True)
        p.write_text('\n'.join(errors),encoding='utf-8')
        print('Daily bars are preserved. Incomplete index lists remain blocked. See logs/ls_membership_errors.txt')
        return 2
    return 0
if __name__=='__main__':raise SystemExit(main())
