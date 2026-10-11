"""Read-only comparison of LS t1702 and KRX investor amount units for one stock/day."""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from krx_research.collectors.ls_index_api import LSIndexClient


def fetch(client, ticker: str, day: dt.date, metric: str, side: str) -> dict:
    stamp = day.strftime('%Y%m%d')
    response = client._call('t1702', '/stock/frgr-itt', {
        'fromdt': stamp, 'shcode': ticker, 'todt': stamp,
        'volvalgb': metric, 'msmdgb': side, 'gubun': '0', 'exchgubun': 'K',
    })
    rows = response.get('t1702OutBlock1')
    if not isinstance(rows, list):
        raise ValueError('LS t1702: 응답에 일자별 항목이 없습니다')
    exact = [row for row in rows if isinstance(row, dict) and row.get('date') == stamp]
    if len(exact) != 1:
        raise ValueError(f'LS t1702: {stamp} 데이터가 정확히 한 건이 아닙니다 (조회 {len(exact)}건)')
    return exact[0]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='LS 수급 단위·투자자 분류 확인 (DB 변경 없음)')
    parser.add_argument('--date', required=True, type=dt.date.fromisoformat, help='DB에 있는 거래일 YYYY-MM-DD')
    parser.add_argument('--ticker', default='005930', help='상장 종목코드 6자리')
    args = parser.parse_args(argv)
    if len(args.ticker) != 6 or not args.ticker.isdigit():
        parser.error('종목코드는 숫자 6자리여야 합니다')
    samples = {}
    with LSIndexClient() as client:
        for metric in ('0', '1'):
            for side in ('1', '2'):
                samples[metric, side] = fetch(client, args.ticker, args.date, metric, side)
    names = {'tjj0000':'사모', 'tjj0001':'금융투자(LS 증권)',
             'tjj0002':'보험', 'tjj0003':'투신', 'tjj0004':'은행',
             'tjj0006':'LS 기금', 'tjj0007':'기타법인',
             'tjj0008':'개인', 'tjj0016':'LS 외인계'}
    print(f'LS t1702 원본, KRX 거래소(K), {args.ticker}, {args.date}; 금액 단위 검증 전')
    for field, label in names.items():
        cells = []
        for metric, side in (('0','1'),('0','2'),('1','1'),('1','2')):
            value = samples[metric,side].get(field)
            cells.append(str(value) if value not in (None,'') else '없음')
        print(f'{label}: 금액 매수={cells[0]} 매도={cells[1]} / 수량 매수={cells[2]} 매도={cells[3]}')
    print('※ LS 기금과 KRX 연기금은 같은 투자자 분류인지 아직 검증되지 않았습니다.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
