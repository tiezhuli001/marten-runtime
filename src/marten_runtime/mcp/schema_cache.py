from pydantic import BaseModel


class MCPSchemaCacheEntry(BaseModel):
    server_id: str
    config_snapshot_id: str
    expires_at: int
