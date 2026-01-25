import os
import random
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
        ),
        Tool(
            name="get_star_trek_joke",
            description="Get a fun Star Trek: The Next Generation joke.",
            inputSchema={
                "type": "object",
                "properties": {},
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
    elif name == "get_star_trek_joke":
        jokes = [
            "Why did Worf change his hair color? It was a good day to dye.",
            "How many ears does Captain Picard have? Three. A left ear, a right ear, and a final front ear.",
            "What does Captain Picard say when he wants to fix a hole in his pants? Make it sew!",
            "Why did the Borg cross the road? Because it was futile to resist.",
            "What do you call a Starfleet officer who can't play music? Riker without his trombone.",
            "Why are Klingons so good at cleaning? Because they fight for honor AND grime.",
            "What did Data say when he met the plugin? You complete me.",
            "Why did Geordi La Forge throw away his clock? Because he wanted to see time fly.",
            "What is a Romulan's favorite type of frog? A Kermit the Frog... wait, no. A Cloak-roak.",
            "Why don't Ferengi make good sailors? They always sell the sails."
        ]
        result = random.choice(jokes)
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
