"""C:\\stock PostgreSQL setup: use the project-local .env and verify connectivity."""
from __future__ import annotations
import shutil
from pathlib import Path
from krx_research.database import open_research_store,resolve_database_target,database_label
def main():
    root=Path(__file__).resolve().parents[1];local=root/'.env';shared=local
    if not local.exists() and shared.is_file():shutil.copy2(shared,local);print(f'.env copied from {shared}')
    target=resolve_database_target(root,read_only=True)
    with open_research_store(target,read_only=True) as store:
        row=store.conn.execute('SELECT current_database() AS db, current_user AS user, version() AS version').fetchone()
    print('PostgreSQL OK:',database_label(target));print(dict(row));return 0
if __name__=='__main__':raise SystemExit(main())
