import os
import logging
import uvicorn
import contextlib
import time
from html import escape as html_escape
from urllib.parse import urlparse
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse, HTMLResponse, RedirectResponse
from starlette.requests import Request
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("echolocate.security")

from jose import jwt, JWSError
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from echo_locate import EchoLocate

# --- Secret Configuration ---

def get_secret(secret_name, default=None, force_gsm=False):
    """
    Attempts to fetch a secret from Google Secret Manager.
    """
    if not force_gsm:
        env_val = os.getenv(secret_name)
        if env_val:
            return env_val

    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    if project_id:
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
            response = client.access_secret_version(request={"name": name})
            return response.payload.data.decode("UTF-8")
        except Exception as e:
            pass

    return default

# Load Secrets — fail fast if required secrets are absent
MCP_AUTH_SECRET = get_secret("MCP_AUTH_SECRET")
MCP_JWT_SECRET = get_secret("MCP_JWT_SECRET")
MCP_CLIENT_ID = get_secret("MCP_CLIENT_ID")
MCP_CLIENT_SECRET = get_secret("MCP_CLIENT_SECRET")

if not MCP_AUTH_SECRET:
    raise RuntimeError("Required secret MCP_AUTH_SECRET is not configured")
if not MCP_JWT_SECRET:
    raise RuntimeError("Required secret MCP_JWT_SECRET is not configured")

# Vector Service Configuration
VECTOR_SERVICE_URL = os.getenv("VECTOR_SERVICE_URL") or get_secret("VECTOR_SERVICE_URL")

# --- Initialization ---

echo_locate = None
if VECTOR_SERVICE_URL:
    echo_locate = EchoLocate(VECTOR_SERVICE_URL)
    print(f"Echo Locate initialized with URL: {VECTOR_SERVICE_URL}")
else:
    print("Warning: VECTOR_SERVICE_URL not found. Vector tools will be disabled.")


ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours


def _is_safe_redirect_uri(uri: str) -> bool:
    """Reject redirect URIs that could be used for open-redirect phishing."""
    if not uri:
        return False
    try:
        parsed = urlparse(uri)
        if parsed.scheme not in ("http", "https"):
            return False
        # Reject URIs with embedded credentials (user@host tricks)
        if "@" in (parsed.netloc or ""):
            return False
        return True
    except Exception:
        return False


def _is_safe_next_url(url: str) -> bool:
    """Allow only relative paths for the post-login redirect."""
    if not url:
        return False
    # Must start with / but not // (protocol-relative)
    return url.startswith("/") and not url.startswith("//")

# --- OAuth Endpoints ---

async def authorize_page(request: Request):
    client_id = request.query_params.get("client_id")
    redirect_uri = request.query_params.get("redirect_uri")
    state = request.query_params.get("state")

    if MCP_CLIENT_ID and client_id and client_id != MCP_CLIENT_ID:
        logger.warning("authorize_page: invalid client_id=%r", client_id)
        return HTMLResponse("Invalid Client ID", status_code=400)

    safe_client_id = html_escape(client_id or "")
    safe_redirect_uri = html_escape(redirect_uri or "")
    safe_state = html_escape(state or "")

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Connect to Cloud Crate</title>
        <style>
            body {{ font-family: -apple-system, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; background-color: #f0f2f5; margin: 0; }}
            .card {{ background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); width: 100%; max-width: 350px; text-align: center; }}
            h1 {{ font-size: 1.5rem; margin-bottom: 1.5rem; }}
            input {{ width: 100%; padding: 0.75rem; margin-bottom: 1rem; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }}
            button {{ background-color: #da552f; color: white; border: none; padding: 0.75rem; width: 100%; border-radius: 4px; cursor: pointer; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Cloud Crate Login</h1>
            <form method="POST" action="/authorize">
                <input type="hidden" name="client_id" value="{safe_client_id}">
                <input type="hidden" name="redirect_uri" value="{safe_redirect_uri}">
                <input type="hidden" name="state" value="{safe_state}">
                <input type="password" name="password" placeholder="Enter Secret Password" required autofocus>
                <button type="submit">Authorize</button>
            </form>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(html)

async def authorize_submit(request: Request):
    form = await request.form()
    password = form.get("password")
    redirect_uri = form.get("redirect_uri")
    state = form.get("state")

    if password != MCP_AUTH_SECRET:
        logger.warning("authorize_submit: failed auth attempt")
        return HTMLResponse("Invalid Password", status_code=401)
    if not redirect_uri or not _is_safe_redirect_uri(redirect_uri):
        logger.warning("authorize_submit: unsafe redirect_uri=%r", redirect_uri)
        return HTMLResponse("Invalid or missing redirect_uri", status_code=400)

    code_payload = {"sub": "auth_code", "exp": time.time() + 300, "type": "code"}
    code = jwt.encode(code_payload, MCP_JWT_SECRET, algorithm=ALGORITHM)

    url = f"{redirect_uri}?code={code}"
    if state:
        url += f"&state={state}"
    return RedirectResponse(url, status_code=303)

async def token_endpoint(request: Request):
    form = await request.form()
    grant_type = form.get("grant_type")
    code = form.get("code")
    client_id = form.get("client_id")
    client_secret = form.get("client_secret")

    if MCP_CLIENT_ID and client_id != MCP_CLIENT_ID:
        logger.warning("token_endpoint: invalid client_id")
        return JSONResponse({"error": "invalid_client"}, status_code=401)
    if MCP_CLIENT_SECRET and client_secret != MCP_CLIENT_SECRET:
        logger.warning("token_endpoint: invalid client_secret")
        return JSONResponse({"error": "invalid_client"}, status_code=401)
    elif not MCP_CLIENT_SECRET:
        logger.warning("token_endpoint: MCP_CLIENT_SECRET not configured, skipping client secret check")

    try:
        payload = jwt.decode(code, MCP_JWT_SECRET, algorithms=[ALGORITHM])
        if payload.get("type") != "code": raise ValueError
    except Exception:
         return JSONResponse({"error": "invalid_grant"}, status_code=400)

    now = time.time()
    access_token = jwt.encode({
        "sub": "claude_user", "iat": now, "exp": now + (ACCESS_TOKEN_EXPIRE_MINUTES * 60), "type": "access", "scope": "mcp"
    }, MCP_JWT_SECRET, algorithm=ALGORITHM)

    return JSONResponse({"access_token": access_token, "token_type": "bearer", "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60, "scope": "mcp"})

# --- Admin Auth ---
async def login_page(request: Request):
    next_url = request.query_params.get("next", "/")
    safe_next = html_escape(next_url if _is_safe_next_url(next_url) else "/")
    html = f"""
    <!DOCTYPE html>
    <html>
    <body>
        <form method="POST" action="/login">
            <h2>Admin Login</h2>
            <input type="hidden" name="next" value="{safe_next}">
            <input type="password" name="password" placeholder="Password" required autofocus>
            <button type="submit">Log In</button>
        </form>
    </body>
    </html>
    """
    return HTMLResponse(html)

async def login_submit(request: Request):
    form = await request.form()
    password = form.get("password")
    next_url = form.get("next", "/")

    if password != MCP_AUTH_SECRET:
        logger.warning("login_submit: failed auth attempt")
        return HTMLResponse("Invalid Password", status_code=401)

    safe_next = next_url if _is_safe_next_url(next_url) else "/"
    now = time.time()
    token = jwt.encode({"sub": "admin", "iat": now, "exp": now + 86400, "type": "access"}, MCP_JWT_SECRET, algorithm=ALGORITHM)
    response = RedirectResponse(safe_next, status_code=303)
    response.set_cookie("access_token", token, httponly=True, secure=True, samesite="Strict")
    return response

async def client_log(request: Request):
    return JSONResponse({"status": "ok"})


# --- Middleware ---
class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in ["/", "/health", "/authorize", "/token", "/login"]:
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        token = None
        if auth_header and auth_header.startswith("Bearer "):
             token = auth_header.split(" ")[1]
        if not token:
            token = request.cookies.get("access_token")

        if not token:
             return JSONResponse({"error": "Unauthorized"}, status_code=401)

        try:
            jwt.decode(token, MCP_JWT_SECRET, algorithms=[ALGORITHM])
        except Exception:
            return JSONResponse({"error": "Invalid Token"}, status_code=401)

        return await call_next(request)

# --- MCP Server Logic ---
server = Server("Cloud Crate MCP")

@server.list_tools()
async def list_tools():
    from mcp.types import Tool
    tools = []

    if echo_locate:
        tools.append(Tool(
            name="echolocate_sample",
            description="Sample tracks from the vector database. Use source='library' (default) for personal library, 'fma' for Free Music Archive, or 'all' for both.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "enum": ["library", "fma", "all"],
                        "description": "Which tracks to sample: 'library' = personal Apple Music library, 'fma' = Free Music Archive, 'all' = both sources",
                        "default": "library"
                    },
                    "limit": {"type": "integer", "description": "Max tracks to return", "default": 20},
                    "offset": {"type": "integer", "description": "Offset for pagination"},
                    "random": {"type": "boolean", "description": "Return random tracks", "default": True}
                }
            }
        ))
        tools.append(Tool(
            name="echolocate_similar",
            description="Find tracks with similar audio characteristics to a given track. Use 'source' to filter results: 'library', 'fma', or 'all'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "track_id": {"type": "string", "description": "Vector ID of the reference track"},
                    "source": {
                        "type": "string",
                        "enum": ["library", "fma", "all"],
                        "description": "Which tracks to search: 'library' = personal library, 'fma' = Free Music Archive, 'all' = both",
                        "default": "library"
                    },
                    "limit": {"type": "integer", "description": "Max similar tracks to return", "default": 5}
                },
                "required": ["track_id"]
            }
        ))
        tools.append(Tool(
            name="echolocate_interpolate",
            description="Find tracks that sonically bridge between two tracks. Returns Vector IDs. When creating Apple Music playlists, search for these tracks in the library first (apple_search_library).",
            inputSchema={
                "type": "object",
                "properties": {
                    "track_id_1": {"type": "string", "description": "Vector ID of starting track"},
                    "track_id_2": {"type": "string", "description": "Vector ID of ending track"},
                    "limit": {"type": "integer", "description": "Number of intermediate tracks", "default": 10},
                    "method": {"type": "string", "enum": ["greedy_walk", "slerp", "linear"], "description": "Interpolation method", "default": "greedy_walk"},
                    "steer_track_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional list of track IDs for multi-point vibe steering"}
                },
                "required": ["track_id_1", "track_id_2"]
            }
        ))
        tools.append(Tool(
            name="echolocate_generate_playlist",
            description="Generate a complete playlist path between two tracks. Returns Vector IDs. When adding to Apple Music, search for these tracks in the library first (apple_search_library).",
            inputSchema={
                "type": "object",
                "properties": {
                    "track_id_1": {"type": "string", "description": "Vector ID of starting track"},
                    "track_id_2": {"type": "string", "description": "Vector ID of ending track"},
                    "limit": {"type": "integer", "description": "Total tracks in playlist", "default": 20},
                    "steer_track_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional list of track IDs for multi-point vibe steering"}
                },
                "required": ["track_id_1", "track_id_2"]
            }
        ))
        tools.append(Tool(
            name="echolocate_text_search",
            description="Search tracks by metadata: artist, album, or title. Use 'source' to filter: 'library', 'fma', or 'all'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "General search term"},
                    "artist": {"type": "string", "description": "Search by artist name"},
                    "album": {"type": "string", "description": "Search by album name"},
                    "title": {"type": "string", "description": "Search by track title"},
                    "source": {
                        "type": "string",
                        "enum": ["library", "fma", "all"],
                        "description": "Which tracks to search: 'library' = personal library, 'fma' = Free Music Archive, 'all' = both",
                        "default": "library"
                    },
                    "limit": {"type": "integer", "description": "Max results", "default": 20}
                }
            }
        ))
        tools.append(Tool(
            name="echolocate_semantic_search",
            description="Search for music by 'vibe' or acoustic description using CLAP AI. Use 'source' to filter: 'library', 'fma', or 'all'. Expand user queries into descriptive acoustic captions for best results. Examples: 'warm analog synths', 'aggressive drums with distorted guitar', 'calm piano with rain sounds'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language description of desired sound"},
                    "source": {
                        "type": "string",
                        "enum": ["library", "fma", "all"],
                        "description": "Which tracks to search: 'library' = personal library, 'fma' = Free Music Archive, 'all' = both",
                        "default": "library"
                    },
                    "limit": {"type": "integer", "description": "Max results", "default": 10},
                    "enhance": {"type": "boolean", "description": "Use AI agent to expand query", "default": True}
                },
                "required": ["query"]
            }
        ))

    return tools

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    from mcp.types import TextContent

    if name.startswith("echolocate_"):
        if not echo_locate: return [TextContent(type="text", text="Echo Locate not configured")]
        try:
            if name == "echolocate_generate_playlist":
                 res = await echo_locate.generate_playlist(
                     arguments["track_id_1"],
                     arguments["track_id_2"],
                     limit=arguments.get("limit", 20),
                     steer_track_ids=arguments.get("steer_track_ids")
                 )
                 output = "\n".join([f"- {t['title']} by {t['artist']} (Vector ID: {t['id']})" for t in res])
                 return [TextContent(type="text", text=f"Generated Path:\n{output}")]

            elif name == "echolocate_sample":
                res = await echo_locate.sample_db(
                    limit=arguments.get("limit", 20),
                    offset=arguments.get("offset", 0),
                    random_sample=arguments.get("random", True),
                    source=arguments.get("source", "library")
                )
                lines = []
                for t in res:
                    line = f"Vector ID: {t['id']} | {t['title']} - {t['artist']}"
                    if t.get('track_url'):
                        line += f" | {t['track_url']}"
                    lines.append(line)
                return [TextContent(type="text", text="\n".join(lines) or "Empty DB")]

            elif name == "echolocate_similar":
                res = await echo_locate.find_similar_tracks(
                    arguments["track_id"],
                    limit=arguments.get("limit", 5),
                    source=arguments.get("source", "library")
                )
                lines = []
                for t in res:
                    line = f"Vector ID: {t['id']} | Sim: {t.get('similarity', 0):.2f} | {t['title']}"
                    if t.get('track_url'):
                        line += f" | {t['track_url']}"
                    lines.append(line)
                return [TextContent(type="text", text="\n".join(lines) or "No similar tracks")]

            elif name == "echolocate_interpolate":
                res = await echo_locate.interpolate(
                    arguments["track_id_1"],
                    arguments["track_id_2"],
                    limit=arguments.get("limit", 10),
                    method=arguments.get("method", "greedy_walk"),
                    steer_track_ids=arguments.get("steer_track_ids")
                )
                output = "\n".join([f"Vector ID: {t['id']} | {t['title']}" for t in res])
                return [TextContent(type="text", text=output or "Interpolation failed")]

            elif name == "echolocate_text_search":
                res = await echo_locate.text_search(
                    query=arguments.get("query"),
                    artist=arguments.get("artist"),
                    album=arguments.get("album"),
                    title=arguments.get("title"),
                    limit=arguments.get("limit", 20),
                    source=arguments.get("source", "library")
                )
                lines = []
                for t in res:
                    line = f"Vector ID: {t['id']} | {t['title']} - {t['artist']}"
                    if t.get('track_url'):
                        line += f" | {t['track_url']}"
                    lines.append(line)
                return [TextContent(type="text", text="\n".join(lines) or "No results")]

            elif name == "echolocate_semantic_search":
                res = await echo_locate.semantic_search(
                    query=arguments["query"],
                    limit=arguments.get("limit", 10),
                    source=arguments.get("source", "library"),
                    enhance=arguments.get("enhance", True)
                )

                # Handle new response format (dict vs list)
                results_list = res
                enhanced_text = ""

                if isinstance(res, dict):
                    results_list = res.get("results", [])
                    if res.get("enhanced_query"):
                        enhanced_text = f"Enhanced Query: '{res.get('enhanced_query')}'\n\n"

                lines = []
                for t in results_list:
                    line = f"Vector ID: {t['id']} | Sim: {t.get('similarity', 0):.3f} | {t['title']} - {t['artist']}"
                    if t.get('track_url'):
                        line += f" | {t['track_url']}"
                    lines.append(line)

                output = enhanced_text + ("\n".join(lines) or "No semantic matches found")
                return [TextContent(type="text", text=output)]

        except Exception as e:
            return [TextContent(type="text", text=f"Echo Locate Error: {e}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]

# --- Starlette App ---
manager = StreamableHTTPSessionManager(server)

@contextlib.asynccontextmanager
async def lifespan(app):
    async with manager.run():
        yield

async def health(request):
    return JSONResponse({"status": "healthy", "service": "Cloud Crate MCP"})

app = Starlette(
    routes=[
        Route("/authorize", authorize_page, methods=["GET"]),
        Route("/authorize", authorize_submit, methods=["POST"]),
        Route("/token", token_endpoint, methods=["POST"]),
        Route("/health", health),
        Route("/", health),
        Route("/client-log", client_log, methods=["POST"]),
        Route("/login", login_page, methods=["GET"]),
        Route("/login", login_submit, methods=["POST"]),
        Mount("/", app=manager.handle_request),
    ],
    middleware=[Middleware(AuthMiddleware)],
    lifespan=lifespan
)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
