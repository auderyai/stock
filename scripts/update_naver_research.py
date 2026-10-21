"""Discover Naver Finance broker PDFs and store new revisions in research schema."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urljoin,urlparse,parse_qs

import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from import_research_pdf import main as import_pdf
from krx_research.research_documents import ResearchDocumentRepository

BASE='https://finance.naver.com'
LIST=BASE+'/research/company_list.naver'
HOSTS=('finance.naver.com','naver.com','pstatic.net','naver.net')

class Links(HTMLParser):
    def __init__(self):
        super().__init__();self.links=[];self.href=None;self.words=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()=='a':
            self.href=dict(attrs).get('href');self.words=[]
    def handle_data(self,data):
        if self.href is not None:self.words.append(data)
    def handle_endtag(self,tag):
        if tag.lower()=='a' and self.href is not None:
            self.links.append((self.href,' '.join(self.words).strip()))
            self.href=None

def allowed(url):
    parsed=urlparse(url)
    return parsed.scheme=='https' and any(parsed.hostname==host or
        parsed.hostname.endswith('.'+host) for host in HOSTS if parsed.hostname)

def get(session,url):
    if not allowed(url):raise ValueError('허용되지 않은 자료 주소')
    request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(request,timeout=18) as response:
        final_url=response.geturl()
        if not allowed(final_url):raise ValueError('자료 주소가 허용된 사이트 밖으로 이동했습니다')
        body=response.read(25_000_001)
        charset=response.headers.get_content_charset() or 'euc-kr'
        return body,charset

def listing(html):
    parser=Links();parser.feed(html)
    found={}
    for href,title in parser.links:
        url=urljoin(BASE,href)
        if urlparse(url).path!='/research/company_read.naver':continue
        nid=parse_qs(urlparse(url).query).get('nid',[''])[0]
        if nid.isdigit():found[nid]=(BASE+'/research/company_read.naver?nid='+nid,title)
    return list(found.values())

def pdf_link(html,detail):
    parser=Links();parser.feed(html)
    options=[]
    for href,label in parser.links:
        url=urljoin(detail,href)
        if re.search(r'\.pdf(?:[?#]|$)',url,re.I) and allowed(url):
            options.append(url)
    # Naver may put the PDF URL in an inline JavaScript link.
    for raw in re.findall(r'https?[^\s"\'<>]+?\.pdf(?:\?[^\s"\'<>]*)?',html,re.I):
        url=raw.replace('&amp;','&')
        if allowed(url):options.append(url)
    if not options:raise ValueError('원문 페이지에 확인 가능한 PDF 링크가 없습니다')
    return options[0]

def main(argv=None):
    p=argparse.ArgumentParser(description='네이버 금융 신규 증권사 리포트 PDF 갱신')
    p.add_argument('--pages',type=int,default=5,help='목록 페이지 수 (1~30)')
    args=p.parse_args(argv)
    if not 1<=args.pages<=30:p.error('pages=1~30')
    session=None
    discovered={}
    for page in range(1,args.pages+1):
        html,charset=get(session,LIST+'?page='+str(page))
        items=listing(html.decode(charset,errors='replace'))
        if not items:
            raise RuntimeError(f'네이버 리서치 목록 {page}쪽을 해석하지 못했습니다. 구조 변경 여부를 확인하세요.')
        for link,title in items:discovered[link]=title
    imported=0;unchanged=0;failures=[]
    with ResearchDocumentRepository() as repo:
        for detail,title in discovered.items():
            try:
                article,charset=get(session,detail)
                link=pdf_link(article.decode(charset,errors='replace'),detail)
                body,_=get(session,link)
                if len(body)>25_000_000 or not body.startswith(b'%PDF-'):
                    raise ValueError('PDF 형식이 아니거나 25 MB를 초과합니다')
                digest=hashlib.sha256(body).hexdigest()
                if repo.source_digest(detail)==digest:
                    unchanged+=1
                    continue
                with tempfile.NamedTemporaryFile(suffix='.pdf',delete=False) as f:
                    f.write(body);pdf=Path(f.name)
                try:
                    if import_pdf([str(pdf),'--source-url',detail]):
                        raise ValueError('PDF 등록 스크립트 오류')
                finally:pdf.unlink(missing_ok=True)
                repo.save_source(detail,title,link,digest)
                imported+=1
            except Exception as exc:
                failures.append((detail,str(exc)))
                repo.save_source_error(detail,title,str(exc))
    print(f'네이버 리서치 목록 {len(discovered)}건, 신규/개정 {imported}건, 동일 PDF {unchanged}건, 실패 {len(failures)}건')
    for url,error in failures[:8]:print(f'미완료: {url}: {error}',file=sys.stderr)
    return 2 if failures else 0

if __name__=='__main__':raise SystemExit(main())
