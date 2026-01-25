import os
import uvicorn
import contextlib
import anyio
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings

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

# Create security settings to disable host validation
# This is CRITICAL for Cloud Run where the host header varies
security_settings = TransportSecuritySettings(
    enable_dns_rebinding_protection=False
)

# Create the Streamable HTTP Session Manager manually
# This allows us to pass the custom security settings
manager = StreamableHTTPSessionManager(
    server,
    security_settings=security_settings,
)

# Define lifespan context to manage the session manager's lifecycle
@contextlib.asynccontextmanager
async def lifespan(app):
    # Retrieve the async generator from manager.run()
    async with manager.run():
        yield

# Health check endpoint
async def health(request):
    return JSONResponse({"status": "healthy", "service": "Hello World MCP"})

# Create Starlette app
app = Starlette(
    routes=[
        # Explicit routes first (so they aren't caught by the catch-all)
        Route("/", health),
        Route("/health", health),
        
        # Mount the session manager at root ("/") as a catch-all.
        # StreamableHTTPSessionManager treats requests path-agnostically (inspects headers/body),
        # so this handles "/sse", "/messages", or any other path the client uses.
        # This avoids 307 redirects caused by explicit path mounting.
        Mount("/", app=manager.handle_request),
    ],
    lifespan=lifespan
)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
