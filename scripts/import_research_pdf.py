"""Index a locally supplied broker PDF in PostgreSQL with page and table provenance."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import re
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from krx_research.research_documents import ResearchDocumentRepository

def split_sections(page, text):
    """Conservative page classification: never promote a mixed page to narrative."""
    markers=('손익계산서','재무상태표','현금흐름표')
    has_statements=all(marker in text for marker in markers)
    if has_statements and ('[ 재무제표 ]' in text or '재무제표' in text[:200]):
        return [('FINANCIAL',text)]
    if re.search(r'(?m)^\s*(?:\[\s*)?(?:컨센서스|Consensus)(?:\s*\])?\s*$',text):
        return [('CONSENSUS',text)]
    if ('Compliance Notice' in text or '투자의견 변동 내역' in text
            or '투자등급 부여 비중' in text):
        return [('OTHER',text)]
    tables=page.find_tables()
    if not tables:
        return [('MIXED' if any(word in text for word in ('재무정보','실적 테이블'))
                 else 'NARRATIVE',text)]
    def inside_table(word):
        mid_x=(word['x0']+word['x1'])/2
        mid_y=(word['top']+word['bottom'])/2
        return any(x0<=mid_x<=x1 and y0<=mid_y<=y1 for x0,y0,x1,y1 in
                   (table.bbox for table in tables))
    words=[word for word in page.extract_words() if not inside_table(word)]
    remaining=' '.join(word['text'] for word in words)
    # Ambiguous pages retain their full text in research.page for human review.
    kind=('MIXED' if any(word in text for word in ('재무정보','실적 테이블'))
          else 'NARRATIVE')
    return [(kind,remaining)]

def parse_header(text):
    code=re.search(r'([가-힣A-Za-z][^\n()]{0,35})\s*\((\d{6})\)',text)
    date=re.search(r'(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일',text)
    broker=re.search(r'\[([^\]\n]{2,35}리서치)\]',text)
    analyst=re.search(r'(?:▶\s*)?Analyst\s+([^\s\n]+)',text,re.IGNORECASE)
    lines=[s.strip() for s in text.splitlines() if s.strip()]
    position=next((i for i,line in enumerate(lines) if re.search(r'\(\d{6}\)',line)),0)
    title=lines[position+1] if position+1<len(lines) else (lines[0] if lines else '')
    parsed_date=None
    if date:
        try: parsed_date=dt.date(*map(int,date.groups()))
        except ValueError: pass
    return dict(stock_code=code.group(2) if code else None, report_date=parsed_date,
                broker=broker.group(1) if broker else None,
                analyst=analyst.group(1) if analyst else None,title=title[:250])

def main(argv=None):
    p=argparse.ArgumentParser(description='증권사 PDF를 PostgreSQL research 스키마에 등록')
    p.add_argument('pdf',type=Path)
    p.add_argument('--source-url',help='네이버 리서치 원문 페이지 URL (있을 때만 입력)')
    args=p.parse_args(argv)
    if not args.pdf.is_file() or args.pdf.suffix.lower()!='.pdf':
        p.error('PDF 파일 경로가 필요합니다')
    import pdfplumber
    raw=args.pdf.read_bytes()
    checksum=hashlib.sha256(raw).hexdigest()
    pages=[]
    with pdfplumber.open(args.pdf) as pdf:
        for index,page in enumerate(pdf.pages,1):
            text=page.extract_text(layout=False) or ''
            tables=page.extract_tables() or []
            sections=split_sections(page,text)
            pages.append((index,text,tables,sections))
    if not pages or not any(text.strip() for _,text,_,_ in pages):
        raise ValueError('텍스트를 추출할 수 없습니다. 스캔 PDF는 OCR 후 다시 입력하세요.')
    header=parse_header('\n'.join(text for _,text,_,_ in pages[:2]))
    with ResearchDocumentRepository() as repository:
        report_id=repository.save_report(checksum,header,args.source_url,args.pdf.name,raw,pages)
    print(f'등록 완료: 보고서 {report_id}, 종목 {header["stock_code"] or "미확인"}, '
          f'{len(pages)}쪽, SHA256 {checksum[:12]}')
    print('본문·재무표·컨센서스 후보를 구분했습니다. 수치 팩트는 검증 후 VERIFIED로 승격해야 조회 뷰에 나타납니다.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
