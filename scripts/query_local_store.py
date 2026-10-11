"""Run one read-only PostgreSQL query against new_stock."""
from __future__ import annotations
import argparse,json,re
from pathlib import Path
from krx_research.database import database_label,open_research_store,resolve_database_target
READ_ONLY_SQL=re.compile(r'^\s*(SELECT|WITH|EXPLAIN)\b',re.I)
def parse_args():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True);g.add_argument('--sql');g.add_argument('--sql-file',type=Path);p.add_argument('--limit',type=int,default=200);return p.parse_args()
def execute_read_only_query(target,statement,*,limit=200):
    if not READ_ONLY_SQL.match(statement):raise ValueError('SELECT, WITH, EXPLAIN만 허용합니다.')
    if not 1<=limit<=10000:raise ValueError('limit은 1~10000 범위여야 합니다.')
    with open_research_store(target,read_only=True) as store:
        cur=store.conn.execute(statement);rows=cur.fetchmany(limit+1);cols=[getattr(d,'name',d[0]) for d in cur.description] if cur.description else []
    return {'database_path':database_label(target),'columns':cols,'rows':[dict(r) for r in rows[:limit]],'row_count':min(len(rows),limit),'truncated':len(rows)>limit}
def main():
    a=parse_args();root=Path(__file__).resolve().parents[1];target=resolve_database_target(root,read_only=True);statement=a.sql_file.read_text(encoding='utf-8') if a.sql_file else a.sql;print(json.dumps(execute_read_only_query(target,statement,limit=a.limit),ensure_ascii=False,indent=2,default=str));return 0
if __name__=='__main__':raise SystemExit(main())
