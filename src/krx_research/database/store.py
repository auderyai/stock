"""PostgreSQL compatibility store symbols for new_stock."""
from krx_research.data_engine.compat import ResearchStore, PostgresResearchStore
SCHEMA_VERSION='32'
StoreError=RuntimeError
class ArtifactView(dict):
    pass
__all__=['ArtifactView','PostgresResearchStore','ResearchStore','SCHEMA_VERSION','StoreError']
