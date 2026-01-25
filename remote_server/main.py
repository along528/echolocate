import os
import uvicorn
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

# Create FastMCP server
mcp = FastMCP("Hello World MCP")

@mcp.tool()
def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}! This is coming from Cloud Run."

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

@mcp.tool()
def echo(message: str) -> str:
    """Echo back the given message."""
    return f"You said: {message}"

# Create FastAPI app and mount MCP SSE endpoint
app = FastAPI(title="Hello World MCP Server")

# Health check endpoint for Cloud Run
@app.get("/")
def health():
    return {"status": "healthy", "service": "Hello World MCP"}

# Mount MCP SSE app at /sse
app.mount("/sse", mcp.sse_app())

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)


