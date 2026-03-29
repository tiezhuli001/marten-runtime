from pydantic import BaseModel


class MCPClientSession(BaseModel):
    server_id: str
    session_mode: str = "shared_worker"
    session_key: str
