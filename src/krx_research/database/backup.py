from __future__ import annotations
import os,subprocess
from pathlib import Path
from .settings import PostgreSQLSettings

def pg_dump_backup(settings:PostgreSQLSettings,destination:str|Path)->Path:
    dest=Path(destination).expanduser().resolve();dest.parent.mkdir(parents=True,exist_ok=True)
    cmd=[settings.dump_executable,'--format=custom','--host',settings.host,'--port',str(settings.port),'--username',settings.user,'--dbname',settings.database,'--file',str(dest)]
    env=os.environ.copy();env['PGPASSWORD']=settings.password
    result=subprocess.run(cmd,env=env,capture_output=True,text=True,check=False)
    if result.returncode!=0:raise RuntimeError('pg_dump 실패: '+(result.stderr.strip() or result.stdout.strip()))
    if not dest.is_file() or dest.stat().st_size<=0:raise RuntimeError('pg_dump 백업 파일이 비어 있습니다.')
    return dest
