"""Shared column-alignment rules for Qt table models."""
import re
from decimal import Decimal,InvalidOperation
CENTER={'date','asof','asofdate','as_of','as_of_date','trade_date','reference_date','기준일','rank','ranking','순위','code','stock_code','ticker','symbol','종목코드','종목(코드)','index_code','지수코드'}
TEXT={'name','stock_name','종목명','industry','업종','market','시장','title','제목','description','설명','reason','사유','broker','증권사','status','상태','investor','투자자','period','기간','metric','지표'}
NUMERIC=re.compile(r'종가|시가|고가|저가|거래량|거래대금|시가총액|등락|변동률|수익률|금액|순매수|순매도|매수액|매도액|목표가|목표값|예상가|횟수|비율|배수|close|open|high|low|volume|turnover|amount|price|pct|percent|return|count|ratio|value|ema|rsi|macd|stoch',re.I)
def alignment(column,heading='',values=()):
    names=[str(x).strip() for x in (column,heading)]; lower=[x.lower() for x in names]
    if any(x in CENTER or x.replace(' ','') in CENTER for x in lower) or any(re.search(r'순위$|날짜|일$',x) for x in names):return 'center'
    if any(x in TEXT for x in lower) or any(re.search(r'명$|이름$|내용|설명|사유|상태|업종|증권사',x) for x in names):return 'left'
    if any(NUMERIC.search(x) for x in names):return 'right'
    present=[str(x).strip() for x in values if str(x).strip() not in ('','None','nan','NaN','-','—')]
    if not present:return 'left'
    for value in present:
        try:
            number=Decimal(value.replace(',','').rstrip('%').replace('−','-'))
            if not number.is_finite():return 'left'
        except InvalidOperation:return 'left'
    return 'right'
def install():
    """Compatibility no-op: Qt models apply alignment directly."""
    return None
