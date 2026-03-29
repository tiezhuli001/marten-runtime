import os

from mcp.server.fastmcp import FastMCP


port = int(os.environ["MCP_TEST_PORT"])
mcp = FastMCP(
    "http-test-server",
    host="127.0.0.1",
    port=port,
    log_level="ERROR",
    stateless_http=True,
)


@mcp.tool()
def echo(query: str) -> str:
    return f"http:{query}"


if __name__ == "__main__":
    mcp.run("streamable-http")
