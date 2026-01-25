import os
import random
import uvicorn
import contextlib
import base64
import json
import time
from typing import Optional
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse, HTMLResponse, RedirectResponse
from starlette.requests import Request
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.datastructures import Secret

from jose import jwt, JWSError
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings

# --- Secret Configuration ---

def get_secret(secret_name, default=None):
    """
    Attempts to fetch a secret from Google Secret Manager.
    Falls back to environment variable if:
    1. GOOGLE_CLOUD_PROJECT is not set (local dev).
    2. Secret Manager API call fails (permissions/disabled).
    """
    # 1. Check Env Var first (to allow overriding in dev or if simple env vars used)
    env_val = os.getenv(secret_name)
    if env_val:
        return env_val

    # 2. Try Secret Manager
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    if project_id:
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
            response = client.access_secret_version(request={"name": name})
            return response.payload.data.decode("UTF-8")
        except Exception as e:
            # print(f"Warning: Could not fetch secret {secret_name} from GSM: {e}")
            # Fallthrough to default
            pass

    return default

# Load Secrets
# Names here match the Env Var names AND the Secret Manager secret names
MCP_AUTH_SECRET = get_secret("MCP_AUTH_SECRET")
MCP_JWT_SECRET = get_secret("MCP_JWT_SECRET")
MCP_CLIENT_ID = get_secret("MCP_CLIENT_ID")
MCP_CLIENT_SECRET = get_secret("MCP_CLIENT_SECRET")

if not all([MCP_AUTH_SECRET, MCP_JWT_SECRET]):
    print("WARNING: MCP_AUTH_SECRET and MCP_JWT_SECRET must be set for authentication to work.")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30  # 30 days

# --- OAuth Endpoints ---

async def authorize_page(request: Request):
    """
    Renders the simple password login page.
    Captures OAuth params to pass through to the post-login redirect.
    """
    client_id = request.query_params.get("client_id")
    redirect_uri = request.query_params.get("redirect_uri")
    state = request.query_params.get("state")
    code_challenge = request.query_params.get("code_challenge")
    code_challenge_method = request.query_params.get("code_challenge_method")

    # Basic Client ID check (if configured)
    if MCP_CLIENT_ID and client_id and client_id != MCP_CLIENT_ID:
         return HTMLResponse(f"Invalid Client ID: {client_id}", status_code=400)

    # Simple HTML form with hidden inputs for state preservation
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Connect to Cloud Crate</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; background-color: #f0f2f5; margin: 0; }}
            .card {{ background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); width: 100%; max-width: 350px; text-align: center; }}
            h1 {{ font-size: 1.5rem; margin-bottom: 1.5rem; color: #1a1a1a; }}
            input[type="password"] {{ width: 100%; padding: 0.75rem; margin-bottom: 1rem; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; font-size: 1rem; }}
            button {{ background-color: #da552f; color: white; border: none; padding: 0.75rem; width: 100%; border-radius: 4px; font-size: 1rem; cursor: pointer; font-weight: 500; transition: opacity 0.2s; }}
            button:hover {{ opacity: 0.9; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Cloud Crate Login</h1>
            <form method="POST" action="/authorize">
                <input type="hidden" name="client_id" value="{client_id or ''}">
                <input type="hidden" name="redirect_uri" value="{redirect_uri or ''}">
                <input type="hidden" name="state" value="{state or ''}">
                <input type="hidden" name="code_challenge" value="{code_challenge or ''}">
                <input type="hidden" name="code_challenge_method" value="{code_challenge_method or ''}">
                <input type="password" name="password" placeholder="Enter Secret Password" required autofocus>
                <button type="submit">Authorize</button>
            </form>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(html)

async def authorize_submit(request: Request):
    """
    Validates the password and redirects with a temporary auth code.
    """
    form = await request.form()
    password = form.get("password")
    redirect_uri = form.get("redirect_uri")
    state = form.get("state")
    # In a real app, we'd store code_challenge to verify verifier in /token
    # For this simple "personal server", we skip PKCE verification for simplicity
    # or we can implement it if needed. The password check is the main gate.

    if password != MCP_AUTH_SECRET:
         return HTMLResponse("Invalid Password", status_code=401)

    if not redirect_uri:
        return HTMLResponse("Missing redirect_uri", status_code=400)

    # Generate a temporary auth code
    # For a stateless server, we can sign the code itself or just grant immediately?
    # Actually, the standard flow requires exchanging code for token.
    # We'll generate a short-lived JWT as the "code" to avoid database state.
    # This "code" verifies that the user passed the password check.
    code_payload = {
        "sub": "auth_code",
        "exp": time.time() + 300, # 5 minutes
        "type": "code"
    }
    code = jwt.encode(code_payload, MCP_JWT_SECRET, algorithm=ALGORITHM)

    # Redirect back to Claude
    url = f"{redirect_uri}?code={code}"
    if state:
        url += f"&state={state}"
    
    return RedirectResponse(url, status_code=303)

async def token_endpoint(request: Request):
    """
    Exchanges the auth code for an access token.
    """
    form = await request.form()
    grant_type = form.get("grant_type")
    code = form.get("code")
    redirect_uri = form.get("redirect_uri")
    client_id = form.get("client_id")
    client_secret = form.get("client_secret")

    # Validate Client Credentials
    if MCP_CLIENT_ID and client_id != MCP_CLIENT_ID:
         return JSONResponse({"error": "invalid_client"}, status_code=401)
    
    # Check Client Secret if provided/configured
    if MCP_CLIENT_SECRET and client_secret != MCP_CLIENT_SECRET:
         return JSONResponse({"error": "invalid_client"}, status_code=401)

    if grant_type != "authorization_code":
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    # Validate Code (which is a signed JWT in our stateless hack)
    try:
        payload = jwt.decode(code, MCP_JWT_SECRET, algorithms=[ALGORITHM])
        if payload.get("type") != "code":
             raise ValueError("Invalid token type")
    except Exception:
         return JSONResponse({"error": "invalid_grant"}, status_code=400)

    # Issue Access Token
    now = time.time()
    access_token_payload = {
        "sub": "claude_user",
        "iat": now,
        "exp": now + (ACCESS_TOKEN_EXPIRE_MINUTES * 60),
        "type": "access",
        "scope": "mcp"
    }
    access_token = jwt.encode(access_token_payload, MCP_JWT_SECRET, algorithm=ALGORITHM)

    return JSONResponse({
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "scope": "mcp"
    })

# --- Middleware ---

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Public endpoints
        if request.url.path in ["/", "/health", "/authorize", "/token"]:
            return await call_next(request)
        
        # Check Authorization Header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
             return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        token = auth_header.split(" ")[1]
        
        try:
            # Verify JWT
            payload = jwt.decode(token, MCP_JWT_SECRET, algorithms=[ALGORITHM])
            if payload.get("type") != "access":
                 raise ValueError("Invalid token type")
            request.state.user = payload
        except Exception as e:
            return JSONResponse({"error": "Invalid Token"}, status_code=401)

        return await call_next(request)


# --- MCP Server Logic ---
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
        Route("/authorize", authorize_page, methods=["GET"]),
        Route("/authorize", authorize_submit, methods=["POST"]),
        Route("/token", token_endpoint, methods=["POST"]),
        
        # Explicit routes first (so they aren't caught by the catch-all)
        Route("/", health),
        Route("/health", health),
        
        # Mount the session manager at root ("/") as a catch-all.
        Mount("/", app=manager.handle_request),
    ],
    middleware=[Middleware(AuthMiddleware)],
    lifespan=lifespan
)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
