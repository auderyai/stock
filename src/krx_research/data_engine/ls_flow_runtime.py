"""Compute verified LS t1702 cash flow on demand from four raw matrices."""
from __future__ import annotations
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import pandas as pd

CODES = {
    'tjj0000':'PRIVATE_FUND','tjj0001':'FINANCIAL_INVESTMENT',
    'tjj0002':'INSURANCE','tjj0003':'INVESTMENT_TRUST',
    'tjj0004':'BANK','tjj0005':'OTHER_FINANCE',
    # LS 기금(tjj0006) is not asserted to equal KRX 연기금.
    'tjj0007':'OTHER_CORPORATION','tjj0008':'INDIVIDUAL',
    'tjj0009':'FOREIGN','tjj0010':'OTHER_FOREIGN',
}
COLUMNS=['stock_code','trade_date','investor_type','buy_volume','sell_volume',
         'buy_value','sell_value','source']

def integer(raw):
    value=str(raw).strip().replace(',','')
    try:
        parsed=Decimal(value)
        if not parsed.is_finite() or parsed<0 or parsed!=parsed.to_integral_value():
            raise ValueError
        return int(parsed)
    except (InvalidOperation,ValueError):
        raise ValueError(f'LS 수급 원본 숫자 형식 오류: {raw!r}') from None

def side_integer(raw, side):
    """LS sell matrices are signed negative; stored sell facts are magnitudes."""
    if side == '1':
        return integer(raw)
    value=str(raw).strip().replace(',','')
    try:
        parsed=Decimal(value)
        if not parsed.is_finite() or parsed!=parsed.to_integral_value():
            raise ValueError
        return abs(int(parsed))
    except (InvalidOperation,ValueError):
        raise ValueError(f'LS 매도 원본 숫자 형식 오류: {raw!r}') from None

def derive_ls_flow(raw_rows, prices):
    """Infer only a unit multiplier from total turnover; never use closing price."""
    result=pd.DataFrame(columns=COLUMNS)
    result.attrs.update({'source':'LS:T1702','source_label':'LS 원본 매수·매도금액 (기관: LS 기금 제외)' ,
                         'estimated_value':False})
    if not raw_rows or prices is None or prices.empty:return result
    if 'trade_date' not in prices.columns and prices.index.name=='trade_date':
        prices=prices.reset_index()
    required={'stock_code','trade_date','amount'}
    if not required.issubset(prices.columns):
        raise ValueError(f'LS 수급 금액 검증에 필요한 DB 일봉 열 누락: {required-set(prices.columns)}')
    totals={}
    for row in prices.to_dict('records'):
        try:
            key=(str(row['stock_code']).zfill(6),pd.Timestamp(row['trade_date']).date())
            value=integer(row['amount'])
            if value>0:totals[key]=value
        except (ValueError,TypeError):continue
    matrices=defaultdict(dict)
    for row in raw_rows:
        metric=str(row.get('metric_code')).strip()
        side=str(row.get('side_code')).strip()
        if metric not in ('0','1') or side not in ('1','2'):continue
        key=(str(row['stock_code']).zfill(6),pd.Timestamp(row['trade_date']).date())
        if key in totals:matrices[key][metric,side]=row['source_fields']
    output=[];rejected=0
    for (code,day),matrix in matrices.items():
        if len(matrix)!=4 or not all(isinstance(x,dict) for x in matrix.values()):
            rejected+=1;continue
        buy_amount,sell_amount=matrix['0','1'],matrix['0','2']
        buy_volume,sell_volume=matrix['1','1'],matrix['1','2']
        try:
            # LS publishes daily total turnover in the same amount response.
            reported=integer(buy_amount['value'])
            opposite=integer(sell_amount['value'])
            if reported<=0 or abs(reported-opposite)>max(1,reported*.005):
                rejected+=1;continue
            # DB OHLCV stores transaction amount in KRW. The candidate must be
            # identified for this very stock and date before any amounts display.
            options=[factor for factor in (1,1000,1000000)
                     if abs(reported*factor-totals[code,day])/totals[code,day]<=.02]
            if len(options)!=1:rejected+=1;continue
            factor=options[0]
            day_rows=[]
            for field,kind in CODES.items():
                b=side_integer(buy_amount[field],'1');s=side_integer(sell_amount[field],'2')
                bv=side_integer(buy_volume[field],'1');sv=side_integer(sell_volume[field],'2')
                day_rows.append({'stock_code':code,'trade_date':day,'investor_type':kind,
                                 'buy_volume':bv,'sell_volume':sv,
                                 'buy_value':b*factor,'sell_value':s*factor,
                                 'source':'LS:T1702'})
            output.extend(day_rows)
        except (KeyError,ValueError,TypeError):
            rejected+=1
    frame=pd.DataFrame(output,columns=COLUMNS)
    frame.attrs.update(result.attrs)
    if rejected:
        frame.attrs['source_warning']=f'{rejected}종목·일은 LS 원본 금액과 DB 거래대금 단위 검증 실패로 제외'
        if frame.empty:frame.attrs['source_error']=frame.attrs['source_warning']
    return frame
