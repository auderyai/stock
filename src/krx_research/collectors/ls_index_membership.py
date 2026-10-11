"""Compatibility facade: workstation membership reads PostgreSQL only."""
from __future__ import annotations
import datetime as dt
from pathlib import Path
from krx_research.database.settings import resolve_database_target


def fetch_ls_membership(screen_type,as_of_date):
    from krx_research.data_engine.index_membership_store import PostgreSQLIndexMembershipStore
    root=Path(__file__).resolve().parents[3]
    target=resolve_database_target(root,read_only=True)
    settings=__import__("krx_research.data_engine.config",fromlist=["DataEngineSettings"]).DataEngineSettings.from_environment()
    day=as_of_date if isinstance(as_of_date,dt.date) else dt.date.fromisoformat(str(as_of_date)[:10])
    return PostgreSQLIndexMembershipStore(settings).load(screen_type,day)
