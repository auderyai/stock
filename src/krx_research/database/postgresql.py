"""PostgreSQL-only ResearchStore adapter used by new_stock."""
from __future__ import annotations
from krx_research.data_engine.compat import ResearchStore as _ResearchStore
from krx_research.data_engine.config import DataEngineSettings
from .settings import PostgreSQLSettings

class PostgreSQLDependencyError(RuntimeError): pass

def _conninfo(settings:PostgreSQLSettings)->str:
    parts=[f'host={settings.host}',f'port={settings.port}',f'dbname={settings.database}',f'user={settings.user}',f'password={settings.password}',f'connect_timeout={settings.connect_timeout}',f'sslmode={settings.ssl_mode}']
    if settings.ssl_root_cert:parts.append(f'sslrootcert={settings.ssl_root_cert}')
    return '\n'.join(parts)

class PostgreSQLResearchStore(_ResearchStore):
    def __init__(self,settings:PostgreSQLSettings,*,read_only:bool=False):
        self.settings_record=settings; self.read_only=read_only
        data_settings=DataEngineSettings(conninfo=_conninfo(settings))
        super().__init__(settings=data_settings)
        if read_only:
            try:self.conn.execute('SET default_transaction_read_only TO on')
            except Exception:pass
    @property
    def label(self):return self.settings_record.label

PostgreSQLConnectionAdapter=object

def translate_postgresql_sql(sql:str)->str:return sql
