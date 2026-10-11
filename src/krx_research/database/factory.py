"""PostgreSQL-only store factory."""
from __future__ import annotations
from .postgresql import PostgreSQLResearchStore
from .settings import DatabaseTarget,PostgreSQLSettings

def open_research_store(target:DatabaseTarget,*,read_only:bool=False)->PostgreSQLResearchStore:
    if not isinstance(target,PostgreSQLSettings):raise TypeError('Stock은 PostgreSQLSettings만 허용합니다.')
    return PostgreSQLResearchStore(target,read_only=read_only)
