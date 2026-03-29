from pydantic import BaseModel


class MCPAvailability(BaseModel):
    server_id: str
    state: str = "healthy"
    reason: str = ""
