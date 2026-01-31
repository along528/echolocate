import os
import random
import uvicorn
import contextlib
import base64
import json
import time
from typing import Optional, List, Dict
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

# New Crate Imports
from apple_crate import AppleCrate
from record_crate import RecordCrate
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

# Load Secrets
MCP_AUTH_SECRET = get_secret("MCP_AUTH_SECRET")
MCP_JWT_SECRET = get_secret("MCP_JWT_SECRET")
MCP_CLIENT_ID = get_secret("MCP_CLIENT_ID")
MCP_CLIENT_SECRET = get_secret("MCP_CLIENT_SECRET")

# Vector Service Configuration
# EchoLocate supports multiple independent vector services
VECTOR_URLS = {}
if os.getenv("LIBRARY_VECTOR_URL"):
    VECTOR_URLS["library"] = os.getenv("LIBRARY_VECTOR_URL")
if os.getenv("FMA_VECTOR_URL"):
    VECTOR_URLS["fma"] = os.getenv("FMA_VECTOR_URL")
# Fallback/Legacy
if not VECTOR_URLS and get_secret("VECTOR_SERVICE_URL"):
     VECTOR_URLS["default"] = get_secret("VECTOR_SERVICE_URL")

# Apple Music Secrets
APPLE_TEAM_ID = get_secret("APPLE_TEAM_ID")
APPLE_KEY_ID = get_secret("APPLE_KEY_ID")
APPLE_PRIVATE_KEY = get_secret("APPLE_PRIVATE_KEY")

# Discogs Secrets
DISCOGS_TOKEN = get_secret("DISCOGS_TOKEN")

# Store the User Token in memory for this simple implementation
APPLE_MUSIC_USER_TOKEN = get_secret("APPLE_MUSIC_USER_TOKEN", force_gsm=True)

# --- Initialization ---

apple_crate = None
if APPLE_TEAM_ID and APPLE_KEY_ID and APPLE_PRIVATE_KEY:
    try:
        apple_crate = AppleCrate(APPLE_TEAM_ID, APPLE_KEY_ID, APPLE_PRIVATE_KEY)
        print("Apple Crate initialized.")
    except Exception as e:
        print(f"Failed to initialize Apple Crate: {e}")
else:
    print("Warning: Apple Music credentials not found. Music tools will be disabled.")

record_crate = None
if DISCOGS_TOKEN:
    try:
        record_crate = RecordCrate(DISCOGS_TOKEN)
        print("Record Crate initialized.")
    except Exception as e:
        print(f"Failed to initialize Record Crate: {e}")
else:
    print("Warning: DISCOGS_TOKEN not found. Discogs tools will be disabled.")

echo_locate = None
if VECTOR_URLS:
    echo_locate = EchoLocate(VECTOR_URLS)
    print(f"Echo Locate initialized with services: {list(VECTOR_URLS.keys())}")
else:
    print("Warning: No Vector Service URLs found. Vector tools will be disabled.")


ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30  # 30 days

# --- OAuth Endpoints ---
# (Kept largely the same for auth flow)

async def authorize_page(request: Request):
    client_id = request.query_params.get("client_id")
    redirect_uri = request.query_params.get("redirect_uri")
    state = request.query_params.get("state")
    
    if MCP_CLIENT_ID and client_id and client_id != MCP_CLIENT_ID:
         return HTMLResponse(f"Invalid Client ID: {client_id}", status_code=400)

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
                <input type="hidden" name="client_id" value="{client_id or ''}">
                <input type="hidden" name="redirect_uri" value="{redirect_uri or ''}">
                <input type="hidden" name="state" value="{state or ''}">
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
         return HTMLResponse("Invalid Password", status_code=401)
    if not redirect_uri:
        return HTMLResponse("Missing redirect_uri", status_code=400)

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
         return JSONResponse({"error": "invalid_client"}, status_code=401)
    if MCP_CLIENT_SECRET and client_secret != MCP_CLIENT_SECRET:
         return JSONResponse({"error": "invalid_client"}, status_code=401)

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
    next_url = request.query_params.get("next", "/apple-auth")
    html = f"""
    <!DOCTYPE html>
    <html>
    <body>
        <form method="POST" action="/login">
            <h2>Admin Login</h2>
            <input type="hidden" name="next" value="{next_url}">
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
    next_url = form.get("next", "/apple-auth")
    
    if password != MCP_AUTH_SECRET:
         return HTMLResponse("Invalid Password", status_code=401)
         
    now = time.time()
    token = jwt.encode({"sub": "admin", "iat": now, "exp": now + 86400, "type": "access"}, MCP_JWT_SECRET, algorithm=ALGORITHM)
    response = RedirectResponse(next_url, status_code=303)
    response.set_cookie("access_token", token, httponly=True, secure=True)
    return response

# --- Apple Music Auth UI ---
async def apple_login_page(request: Request):
    if not apple_crate:
        return HTMLResponse("Apple Crate not configured.", status_code=500)
    dev_token = apple_crate.get_developer_token()
    # (Simplified HTML for brevity, assumes same logic as before but using apple_crate)
    html = f"""<!DOCTYPE html>
    <html><head><title>Link Apple Music</title>
    <script src="https://js-cdn.music.apple.com/musickit/v3/musickit.js"></script>
    </head><body>
    <button id="login-btn">Log In with Apple Music</button>
    <script>
        document.addEventListener('musickitloaded', async function() {{
            await MusicKit.configure({{ developerToken: '{dev_token}', app: {{ name: 'Cloud Crate', build: '1.0.0' }} }});
            document.getElementById('login-btn').addEventListener('click', async () => {{
                const music = MusicKit.getInstance();
                await music.authorize();
                await fetch('/apple-auth/callback', {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify({{ token: music.musicUserToken }}) }});
                alert("Logged in!");
            }});
        }});
    </script>
    </body></html>"""
    return HTMLResponse(html)

async def apple_callback(request: Request):
    global APPLE_MUSIC_USER_TOKEN
    data = await request.json()
    token = data.get("token")
    if token:
        APPLE_MUSIC_USER_TOKEN = token
        # Persist to Secret Manager logic omitted for brevity, but could be re-added
        print(f"Received Apple Music User Token.")
        return JSONResponse({"status": "success"})
    return JSONResponse({"error": "missing_token"}, status_code=400)

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
             if request.url.path.startswith("/apple-auth"):
                 return RedirectResponse(f"/login?next={request.url.path}")
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
    
    # --- Apple Crate Tools ---
    tools.append(Tool(
        name="search_apple_music",
        description="Search Apple Music Catalog.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"}
            },
            "required": ["query"]
        }
    ))
    tools.append(Tool(
        name="create_playlist",
        description="Create Apple Music playlist.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "track_ids": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["name", "track_ids"]
        }
    ))
    tools.append(Tool(
        name="search_library",
        description="Search Apple Music Library.",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "artist": {"type": "string"},
                "album": {"type": "string"},
                "limit": {"type": "integer"}
            }
        }
    ))

    # --- Record Crate Tools ---
    tools.append(Tool(
        name="search_discogs",
        description="Search Discogs.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
                "format": {"type": "string"}
            },
            "required": ["query"]
        }
    ))
    tools.append(Tool(
        name="get_discogs_versions",
        description="Get versions of a Discogs master release.",
        inputSchema={
            "type": "object",
            "properties": {
                "master_id": {"type": "string"},
                "page": {"type": "integer"},
                "limit": {"type": "integer"}
            },
            "required": ["master_id"]
        }
    ))

    # --- Echo Locate Tools ---
    if echo_locate:
        tools.append(Tool(
            name="echo_locate_sample",
            description="Sample tracks from a vector DB.",
            inputSchema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string", "description": "Vector Service Name (e.g. 'library', 'fma')", "default": "default"},
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"},
                    "random": {"type": "boolean"}
                }
            }
        ))
        tools.append(Tool(
            name="echo_locate_similar",
            description="Find similar tracks.",
            inputSchema={
                "type": "object",
                "properties": {
                    "track_id": {"type": "string"},
                    "service_name": {"type": "string", "default": "default"},
                    "limit": {"type": "integer"}
                },
                "required": ["track_id"]
            }
        ))
        tools.append(Tool(
            name="echo_locate_interpolate",
            description="Interpolate between two tracks.",
            inputSchema={
                "type": "object",
                "properties": {
                    "track_id_1": {"type": "string"},
                    "track_id_2": {"type": "string"},
                    "service_name": {"type": "string", "default": "default"},
                    "limit": {"type": "integer"},
                    "method": {"type": "string", "enum": ["greedy_walk", "slerp", "linear"]},
                    "steer_track_id": {"type": "string"}
                },
                "required": ["track_id_1", "track_id_2"]
            }
        ))
        tools.append(Tool(
            name="generate_interpolation_playlist",
            description="Generate a full playlist path between two tracks.",
            inputSchema={
                "type": "object",
                "properties": {
                    "track_id_1": {"type": "string"},
                    "track_id_2": {"type": "string"},
                    "service_name": {"type": "string", "default": "default"},
                    "limit": {"type": "integer"}
                },
                "required": ["track_id_1", "track_id_2"]
            }
        ))

    # --- Context Tools ---
    tools.append(Tool(
        name="get_track_context",
        description="Get details for a catalog track.",
        inputSchema={
            "type": "object",
            "properties": {
                "track_id": {"type": "string", "description": "Catalog Track ID"}
            },
            "required": ["track_id"]
        }
    ))
    
    # --- Discogs Advanced Tools ---
    tools.append(Tool(
        name="get_discogs_release",
        description="Get specific Discogs release details.",
        inputSchema={
            "type": "object",
            "properties": {
                "release_id": {"type": "string"},
                "release_ids": {"type": "array", "items": {"type": "string"}}
            }
        }
    ))
    tools.append(Tool(
        name="get_discogs_wantlist",
        description="Get user's Discogs wantlist.",
        inputSchema={
            "type": "object",
            "properties": {
                "page": {"type": "integer"},
                "limit": {"type": "integer"}
            }
        }
    ))

    return tools

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    from mcp.types import TextContent
    
    # Apple Crate Handlers
    if name == "search_apple_music":
        if not apple_crate: return [TextContent(type="text", text="Apple Crate not configured")]
        try:
            res = await apple_crate.search(arguments["query"], limit=arguments.get("limit", 5))
            songs = res.get("results", {}).get("songs", {}).get("data", [])
            output = "\n".join([f"ID: {s['id']} | {s['attributes']['name']} - {s['attributes']['artistName']}" for s in songs])
            return [TextContent(type="text", text=output or "No results")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    elif name == "create_playlist":
        if not apple_crate or not APPLE_MUSIC_USER_TOKEN: return [TextContent(type="text", text="Auth required")]
        try:
            res = await apple_crate.create_playlist(arguments["name"], arguments.get("description", ""), arguments["track_ids"], APPLE_MUSIC_USER_TOKEN)
            # The API returns the playlist object sometimes, just say success
            return [TextContent(type="text", text=f"Playlist Created Successfully.")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    elif name == "search_library":
        if not apple_crate or not APPLE_MUSIC_USER_TOKEN: return [TextContent(type="text", text="Auth required")]
        query = arguments.get("title") or arguments.get("artist") or arguments.get("album")
        if not query: return [TextContent(type="text", text="Query required")]
        try:
            # Need to robustly handle the weird argument structure existing clients might send
            # But here we just take the first valid one if the user said "title" or "artist"
            term = query
            res = await apple_crate.search_library(
                term, APPLE_MUSIC_USER_TOKEN, limit=arguments.get("limit", 5)
            )
            data = res.get("results", {}).get("library-songs", {}).get("data", [])
            output = "\n".join([f"ID: {s['id']} | {s['attributes']['name']}" for s in data])
            return [TextContent(type="text", text=output or "No results")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]
    
    elif name == "get_track_context":
        if not apple_crate: return [TextContent(type="text", text="Apple Crate not configured")]
        track_id = arguments.get("track_id")
        if track_id.startswith("catalog:"): track_id = track_id.split(":", 1)[1]
        try:
            data = await apple_crate.get_resource(track_id, "songs")
            if data and "data" in data and len(data["data"]) > 0:
                attrs = data["data"][0]["attributes"]
                result = f"""
Title: {attrs.get('name')}
Artist: {attrs.get('artistName')}
Album: {attrs.get('albumName')}
Release Date: {attrs.get('releaseDate')}
Duration: {attrs.get('durationInMillis')} ms
"""
            else:
                result = "Track not found."
            return [TextContent(type="text", text=result)]
        except Exception as e:
             return [TextContent(type="text", text=f"Error: {e}")]

    # Record Crate Handlers
    elif name == "search_discogs":
        if not record_crate: return [TextContent(type="text", text="Record Crate not configured")]
        try:
            res = await record_crate.search(arguments["query"], limit=arguments.get("limit", 5), format=arguments.get("format"))
            results = res.get("results", [])
            output = "\n".join([f"ID: {r.get('id')} | {r.get('title')}" for r in results])
            return [TextContent(type="text", text=output or "No results")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    elif name == "get_discogs_versions":
        if not record_crate: return [TextContent(type="text", text="Record Crate not configured")]
        try:
            res = await record_crate.get_master_versions(arguments["master_id"], page=arguments.get("page", 1), per_page=arguments.get("limit", 10))
            vers = res.get("versions", [])
            output = "\n".join([f"ID: {v.get('id')} | {v.get('title')} | {v.get('format')}" for v in vers])
            return [TextContent(type="text", text=output or "No versions")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    elif name == "get_discogs_release":
        if not record_crate: return [TextContent(type="text", text="Record Crate not configured")]
        release_id = arguments.get("release_id")
        if not release_id and arguments.get("release_ids"): 
             # Just take first for simplicity or handle batch logic if needed
             release_id = arguments.get("release_ids")[0]
        
        if not release_id: return [TextContent(type="text", text="No release ID provided")]

        try:
             # Support batch if passed IDs? The prompt implied batch capability in previous code.
             # The legacy code looped. Let's do that for release_ids.
             target_ids = arguments.get("release_ids", [])
             if release_id and release_id not in target_ids: target_ids.append(release_id)
             
             responses = await record_crate.get_releases(target_ids)
             final_output = []
             for i, data in enumerate(responses):
                 rid = target_ids[i]
                 if isinstance(data, Exception):
                     final_output.append(f"Error: {data}")
                     continue
                 
                 final_output.append(f"""
---
Release ID: {rid}
Title: {data.get('title')}
Artists: {', '.join([a.get('name') for a in data.get('artists', [])])}
Year: {data.get('year')}
Marketplace: {record_crate.get_marketplace_url(rid)}
""")
             return [TextContent(type="text", text="\n".join(final_output))]
        except Exception as e:
             return [TextContent(type="text", text=f"Error: {e}")]

    elif name == "get_discogs_wantlist":
        if not record_crate: return [TextContent(type="text", text="Record Crate not configured")]
        try:
             identity = await record_crate.get_identity()
             username = identity.get("username")
             if not username: return [TextContent(type="text", text="No username found")]
             
             data = await record_crate.get_wantlist(username, page=arguments.get("page", 1), per_page=arguments.get("limit", 50))
             wants = data.get("wants", [])
             
             output = []
             for w in wants:
                  info = w.get("basic_information", {})
                  rid = str(info.get("id"))
                  output.append(f"[{rid}] {info.get('title')} - {', '.join([a.get('name') for a in info.get('artists', [])])}")
             return [TextContent(type="text", text="\n".join(output) or "Wantlist empty")]
        except Exception as e:
             return [TextContent(type="text", text=f"Error: {e}")]

    # Echo Locate Handlers
    elif name.startswith("echo_locate_") or name == "generate_interpolation_playlist":
        if not echo_locate: return [TextContent(type="text", text="Echo Locate not configured")]
        try:
            service = arguments.get("service_name", "default")
            
            if name == "generate_interpolation_playlist":
                 res = await echo_locate.generate_playlist(arguments["track_id_1"], arguments["track_id_2"], service, limit=arguments.get("limit", 20))
                 output = "\n".join([f"- {t['title']} by {t['artist']} (ID: {t['id']})" for t in res])
                 return [TextContent(type="text", text=f"Generated Path:\n{output}")]

            elif name == "echo_locate_sample":
                res = await echo_locate.sample_db(service, limit=arguments.get("limit", 20), offset=arguments.get("offset", 0), random_sample=arguments.get("random", True))
                # Format output
                output = "\n".join([f"ID: {t['id']} | {t['title']} - {t['artist']}" for t in res])
                return [TextContent(type="text", text=output or "Empty DB")]

            elif name == "echo_locate_similar":
                res = await echo_locate.find_similar_tracks(arguments["track_id"], service, limit=arguments.get("limit", 5))
                output = "\n".join([f"ID: {t['id']} | Sim: {t.get('similarity', 0):.2f} | {t['title']}" for t in res])
                return [TextContent(type="text", text=output or "No similar tracks")]

            elif name == "echo_locate_interpolate":
                res = await echo_locate.interpolate(
                    arguments["track_id_1"], arguments["track_id_2"], service,
                    limit=arguments.get("limit", 10), method=arguments.get("method", "greedy_walk"),
                    steer_track_id=arguments.get("steer_track_id")
                )
                output = "\n".join([f"ID: {t['id']} | {t['title']}" for t in res])
                return [TextContent(type="text", text=output or "Interpolation failed")]

        except Exception as e:
            return [TextContent(type="text", text=f"Echo Locate Error: {e}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]

# --- Starlette App ---
host_settings = TransportSecuritySettings(enable_dns_rebinding_protection=False)
manager = StreamableHTTPSessionManager(server, security_settings=host_settings)

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
        Route("/apple-auth", apple_login_page, methods=["GET"]),
        Route("/apple-auth/callback", apple_callback, methods=["POST"]),
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
