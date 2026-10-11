"""Create a PostgreSQL pg_dump backup under C:\\stock\\POSTGRESQL_BACKUP."""
from __future__ import annotations
import argparse,datetime as dt,json
from pathlib import Path
from zoneinfo import ZoneInfo
from krx_research.archive import ArchiveLayout
from krx_research.database import database_label,resolve_database_target
from krx_research.database.backup import pg_dump_backup
KST=ZoneInfo('Asia/Seoul')
def parse_args():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--destination',type=Path);return p.parse_args()
def main():
    a=parse_args();root=Path(__file__).resolve().parents[1];layout=ArchiveLayout(root);layout.ensure();target=resolve_database_target(root);stamp=dt.datetime.now(tz=KST).strftime('%Y%m%d_%H%M%S');dest=a.destination or layout.backup_root/f'krx_research_{stamp}.dump';path=pg_dump_backup(target,dest);print(json.dumps({'source_database':database_label(target),'backup_path':str(path),'backup_size_bytes':path.stat().st_size},ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
