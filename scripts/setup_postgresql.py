"""C:\\stock PostgreSQL setup: use the project-local .env and verify connectivity."""
from __future__ import annotations
import shutil
from pathlib import Path
from krx_research.database import resolve_database_target,database_label
from krx_research.database.administrative_repository import AdministrativeRepository
from krx_research.data_engine.config import settings_from_database_target
def main():
    root=Path(__file__).resolve().parents[1];local=root/'.env';shared=local
    if not local.exists() and shared.is_file():shutil.copy2(shared,local);print(f'.env copied from {shared}')
    target=resolve_database_target(root,read_only=True)
    with AdministrativeRepository(settings_from_database_target(target),application_name='setup_check') as repository:
        row=repository.server_identity()
    print('PostgreSQL OK:',database_label(target));print(row);return 0
if __name__=='__main__':raise SystemExit(main())
