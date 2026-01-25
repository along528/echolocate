import os
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse

from mcp.server import Server
from mcp.server.sse import SseServerTransport, TransportSecuritySettings

# Create MCP server with tools
server = Server("Hello World MCP")

@server.list_tools()
async def list_tools():
    from mcp.types import Tool
    return [
        Tool(
            name="greet",
            description="Greet someone by name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The name to greet"}
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="add",
            description="Add two numbers.",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {"type": "integer", "description": "First number"},
                    "b": {"type": "integer", "description": "Second number"}
                },
                "required": ["a", "b"]
            }
        ),
        Tool(
            name="echo",
            description="Echo back the given message.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Message to echo"}
                },
                "required": ["message"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    from mcp.types import TextContent
    if name == "greet":
        result = f"Hello, {arguments['name']}! This is coming from Cloud Run."
    elif name == "add":
        result = str(arguments['a'] + arguments['b'])
    elif name == "echo":
        result = f"You said: {arguments['message']}"
    else:
        result = f"Unknown tool: {name}"
    return [TextContent(type="text", text=result)]

# Create SSE transport with security settings that disable DNS rebinding protection
# Cloud Run handles security at the load balancer level
security_settings = TransportSecuritySettings(
    enable_dns_rebinding_protection=False  # Disable host validation for Cloud Run
)

sse_transport = SseServerTransport(
    "/messages/",  # Path for POST messages
    security_settings=security_settings
)

# SSE endpoint handler as ASGI app
async def handle_sse(scope, receive, send):
    """Handle SSE connection as raw ASGI - no response wrapper needed"""
    from starlette.requests import Request
    request = Request(scope, receive, send)
    async with sse_transport.connect_sse(
        scope, receive, send
    ) as streams:
        await server.run(
            streams[0],  # read stream
            streams[1],  # write stream
            server.create_initialization_options()
        )

# Health check endpoint
async def health(request):
    return JSONResponse({"status": "healthy", "service": "Hello World MCP"})

# Create Starlette app with routes
# Use Mount for the ASGI apps (SSE and messages) so they handle their own responses
app = Starlette(
    routes=[
        Route("/", health),
        Route("/health", health),
        # Mount SSE endpoint as raw ASGI
        Mount("/sse", app=handle_sse),
        # Mount messages endpoint as raw ASGI
        Mount("/messages/", app=sse_transport.handle_post_message),
    ]
)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
