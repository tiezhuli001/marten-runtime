from mcp.server.fastmcp import FastMCP


mcp = FastMCP("stdio-test-server", log_level="ERROR")


@mcp.tool()
def echo(query: str) -> str:
    return f"stdio:{query}"


if __name__ == "__main__":
    mcp.run("stdio")
