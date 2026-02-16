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
VECTOR_SERVICE_URL = os.getenv("VECTOR_SERVICE_URL") or get_secret("VECTOR_SERVICE_URL")

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
if VECTOR_SERVICE_URL:
    echo_locate = EchoLocate(VECTOR_SERVICE_URL)
    print(f"Echo Locate initialized with URL: {VECTOR_SERVICE_URL}")
else:
    print("Warning: VECTOR_SERVICE_URL not found. Vector tools will be disabled.")


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
        name="apple_search_catalog",
        description="Search Apple Music Catalog. Returns Apple Music IDs.",
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
        name="apple_create_playlist",
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
        name="apple_search_library",
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
        name="discogs_search",
        description="Search Discogs. Returns Master IDs by default. To get a specific Release ID (required for wantlist/collection), use 'discogs_get_versions' with the Master ID returned here.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results to return"},
                "format": {"type": "string", "description": "Filter by format (e.g. 'Vinyl', 'CD')"}
            },
            "required": ["query"]
        }
    ))
    tools.append(Tool(
        name="discogs_get_versions",
        description="Get specific release versions for a Discogs Master Release. Input: Master ID. Output: Release IDs (usable for wantlist/collection).",
        inputSchema={
            "type": "object",
            "properties": {
                "master_id": {"type": "string", "description": "Discogs Master ID (from discogs_search)"},
                "page": {"type": "integer", "description": "Page number for pagination"},
                "limit": {"type": "integer", "description": "Results per page"}
            },
            "required": ["master_id"]
        }
    ))

    # --- Echo Locate Tools ---
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
                    "steer_track_id": {"type": "string", "description": "Optional track ID to steer the path toward (vibe steering)"},
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

    # --- Context Tools ---
    tools.append(Tool(
        name="apple_get_track_context",
        description="Get details for a catalog track using Apple Music ID.",
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
        name="discogs_get_release",
        description="Get detailed info for a specific Discogs release. Input: Release ID (from discogs_get_versions, wantlist, or collection). Output: Full release details.",
        inputSchema={
            "type": "object",
            "properties": {
                "release_id": {"type": "string", "description": "Discogs Release ID (NOT Master ID)"},
                "release_ids": {"type": "array", "items": {"type": "string"}, "description": "Multiple Release IDs for batch lookup"}
            }
        }
    ))
    tools.append(Tool(
        name="discogs_get_wantlist",
        description="Get user's Discogs wantlist. Output: Release IDs (not Master IDs).",
        inputSchema={
            "type": "object",
            "properties": {
                "page": {"type": "integer", "description": "Page number"},
                "limit": {"type": "integer", "description": "Results per page"}
            }
        }
    ))
    tools.append(Tool(
        name="discogs_add_to_wantlist",
        description="Add a release to the Discogs wantlist. Input: Release ID (NOT Master ID). Use 'discogs_get_versions' to convert a Master ID to Release ID first.",
        inputSchema={
            "type": "object",
            "properties": {
                "release_id": {"type": "string", "description": "Discogs Release ID (NOT Master ID - use discogs_get_versions to get Release IDs)"},
                "notes": {"type": "string", "description": "Optional notes"},
                "rating": {"type": "integer", "description": "Optional rating (1-5)"}
            },
            "required": ["release_id"]
        }
    ))
    tools.append(Tool(
        name="discogs_get_collection_folders",
        description="Get all folders in user's Discogs collection. Output: Folder IDs. Folder ID 0 is a special 'All' folder containing every release.",
        inputSchema={
            "type": "object",
            "properties": {}
        }
    ))
    tools.append(Tool(
        name="discogs_get_collection",
        description="Get releases from a Discogs collection folder. Input: Folder ID. Output: Release IDs (not Master IDs). Use folder_id=0 for all releases.",
        inputSchema={
            "type": "object",
            "properties": {
                "folder_id": {"type": "integer", "description": "Folder ID (0 for All) - get IDs from discogs_get_collection_folders"},
                "page": {"type": "integer", "description": "Page number"},
                "limit": {"type": "integer", "description": "Results per page"},
                "sort": {"type": "string", "description": "Sort by: label, artist, title, catno, format, rating, added, year"},
                "sort_order": {"type": "string", "enum": ["asc", "desc"], "description": "Sort direction"}
            }
        }
    ))
    tools.append(Tool(
        name="discogs_add_to_collection",
        description="Add a release to a Discogs collection folder. Input: Release ID (NOT Master ID) and Folder ID. Use discogs_get_versions to convert Master ID to Release ID. Cannot add to folder 0; use folder 1 (Uncategorized) or another folder.",
        inputSchema={
            "type": "object",
            "properties": {
                "release_id": {"type": "string", "description": "Discogs Release ID (NOT Master ID - use discogs_get_versions to get Release IDs)"},
                "folder_id": {"type": "integer", "description": "Target folder ID (default: 1) - get IDs from discogs_get_collection_folders"}
            },
            "required": ["release_id"]
        }
    ))
    tools.append(Tool(
        name="discogs_move_release",
        description="Move a release from one Discogs collection folder to another. Input: Release ID (NOT Master ID) and New Folder ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "release_id": {"type": "string", "description": "Discogs Release ID"},
                "new_folder_id": {"type": "integer", "description": "Destination Folder ID"}
            },
            "required": ["release_id", "new_folder_id"]
        }
    ))

    return tools

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    from mcp.types import TextContent
    
    # Apple Crate Handlers
    if name == "apple_search_catalog":
        if not apple_crate: return [TextContent(type="text", text="Apple Crate not configured")]
        try:
            res = await apple_crate.search(arguments["query"], limit=arguments.get("limit", 5))
            songs = res.get("results", {}).get("songs", {}).get("data", [])
            output = "\n".join([f"Apple ID: {s['id']} | {s['attributes']['name']} - {s['attributes']['artistName']}" for s in songs])
            return [TextContent(type="text", text=output or "No results")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    elif name == "apple_create_playlist":
        if not apple_crate or not APPLE_MUSIC_USER_TOKEN: return [TextContent(type="text", text="Auth required")]
        try:
            res = await apple_crate.create_playlist(arguments["name"], arguments.get("description", ""), arguments["track_ids"], APPLE_MUSIC_USER_TOKEN)
            # The API returns the playlist object
            playlist_data = res.get("data", [])
            if playlist_data:
                playlist_id = playlist_data[0].get("id")
                return [TextContent(type="text", text=f"Playlist Created Successfully. ID: {playlist_id}")]
            return [TextContent(type="text", text="Playlist Created Successfully (No ID returned).")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    elif name == "apple_search_library":
        if not apple_crate: return [TextContent(type="text", text="Apple Crate not configured")]
        if not APPLE_MUSIC_USER_TOKEN: return [TextContent(type="text", text="Auth required")]
        
        # 1. Determine Primary Search Query
        primary_query = None
        if arguments.get("title"):
             primary_query = arguments.get("title")
        elif arguments.get("album"):
             primary_query = arguments.get("album")
        elif arguments.get("artist"):
             primary_query = arguments.get("artist")
             
        if not primary_query:
            return [TextContent(type="text", text="Please provide at least one of: artist, album, title.")]

        limit_arg = arguments.get("limit", 5)

        # --- Pass 1: Strict Search (Query + Filters) ---
        strict_results = []
        try:
            # We paginate up to 100 to find matches that might be buried
            limit_per_req = 25
            max_total = 100
            offset = 0
            
            while len(strict_results) < max_total:
                res = await apple_crate.search_library(
                    primary_query, APPLE_MUSIC_USER_TOKEN, limit=limit_per_req, offset=offset
                )
                batch = res.get("results", {}).get("library-songs", {}).get("data", [])
                
                if not batch: break
                
                for song in batch:
                    attrs = song.get("attributes", {})
                    
                    # Apply Strict Filters
                    match = True
                    if arguments.get("artist"):
                        if arguments.get("artist").lower() not in attrs.get("artistName", "").lower():
                            match = False
                    if match and arguments.get("album"):
                         if arguments.get("album").lower() not in attrs.get("albumName", "").lower():
                            match = False
                    # For title in strict pass, we trust the primary query if it IS the title, 
                    # but if we searched by artist/album and PROVIDED a title, we check it.
                    if match and arguments.get("title") and primary_query != arguments.get("title"):
                         if arguments.get("title").lower() not in attrs.get("name", "").lower():
                            match = False
                            
                    if match:
                        strict_results.append(song)
                
                offset += len(batch)
                if len(batch) < limit_per_req: break
                
        except Exception as e:
            return [TextContent(type="text", text=f"Error in strict search: {e}")]

        # --- Pass 2: Broad Title Search (Optional) ---
        broad_results = []
        if arguments.get("title"):
             # We always perform the broad title search if a title is provided, 
             # to ensure we capture "Title Only" matches even if the filtered search 
             # (which might also use the title as the query) filtered them out due to artist/album constraints.
             # This satisfies the requirement: "search for the song title by itself if provided... in addition"
            try:
                # Just fetch a small batch for the broad title match
                # Use the provided limit for the broad search as well, or a default? 
                # User didn't specify, but usually we want "some" results.
                res = await apple_crate.search_library(
                    arguments.get("title"), APPLE_MUSIC_USER_TOKEN, limit=limit_arg
                )
                broad_results = res.get("results", {}).get("library-songs", {}).get("data", [])
            except Exception as e:
                # Don't fail the whole request
                print(f"Error in broad search: {e}")

        # --- Merge & Deduplicate ---
        # Priority: Strict results first (they matched all criteria), then Broad results
        final_songs = []
        seen_ids = set()
        
        for song in strict_results:
            if song['id'] not in seen_ids:
                final_songs.append(song)
                seen_ids.add(song['id'])
        
        for song in broad_results:
            if song['id'] not in seen_ids:
                final_songs.append(song)
                seen_ids.add(song['id'])
                
        # Limit
        final_songs = final_songs[:limit_arg]
        
        output = "\n".join([f"Apple ID: {s['id']} | {s['attributes']['name']} - {s['attributes']['artistName']}" for s in final_songs])
        return [TextContent(type="text", text=output or "No results")]
    
    elif name == "apple_get_track_context":
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
    elif name == "discogs_search":
        if not record_crate: return [TextContent(type="text", text="Record Crate not configured")]
        try:
            res = await record_crate.search(arguments["query"], limit=arguments.get("limit", 5), format=arguments.get("format"))
            results = res.get("results", [])
            output = "\n".join([f"Master ID: {r.get('id')} | {r.get('title')}" for r in results])
            return [TextContent(type="text", text=output or "No results")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    elif name == "discogs_get_versions":
        if not record_crate: return [TextContent(type="text", text="Record Crate not configured")]
        try:
            res = await record_crate.get_master_versions(arguments["master_id"], page=arguments.get("page", 1), per_page=arguments.get("limit", 10))
            vers = res.get("versions", [])
            output = "\n".join([f"Release ID: {v.get('id')} | {v.get('title')} | {v.get('format')}" for v in vers])
            return [TextContent(type="text", text=output or "No versions")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    elif name == "discogs_get_release":
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
                 
                 artists = ', '.join(a.get('name', '') for a in data.get('artists', []))
                 labels = ', '.join(f"{l.get('name', '')} ({l.get('catno', '')})" for l in data.get('labels', []))
                 formats = ', '.join(
                     f"{f.get('name', '')}" + (f" [{', '.join(f.get('descriptions', []))}]" if f.get('descriptions') else "")
                     for f in data.get('formats', [])
                 )
                 genres = ', '.join(data.get('genres', []))
                 styles = ', '.join(data.get('styles', []))
                 identifiers = '\n'.join(
                     f"  {ident.get('type', '')}: {ident.get('value', '')}"
                     for ident in data.get('identifiers', [])
                 )
                 community = data.get('community', {})
                 rating = community.get('rating', {})

                 lines = [
                     "---",
                     f"Discogs Release ID: {rid}",
                     f"Title: {data.get('title')}",
                     f"Artists: {artists}",
                     f"Year: {data.get('year')}",
                     f"Country: {data.get('country', 'Unknown')}",
                     f"Labels: {labels}",
                     f"Formats: {formats}",
                     f"Genres: {genres}",
                     f"Styles: {styles}",
                 ]
                 if identifiers:
                     lines.append(f"Identifiers:\n{identifiers}")
                 notes = data.get('notes', '')
                 if notes:
                     lines.append(f"Notes: {notes}")
                 lines += [
                     f"Community: {community.get('have', 0)} have / {community.get('want', 0)} want / Rating: {rating.get('average', 0):.1f} ({rating.get('count', 0)} votes)",
                     f"For Sale: {data.get('num_for_sale', 'N/A')} from {data.get('lowest_price', 'N/A')}",
                     f"Marketplace: {record_crate.get_marketplace_url(rid)}",
                 ]
                 final_output.append('\n'.join(lines))
             return [TextContent(type="text", text="\n".join(final_output))]
        except Exception as e:
             return [TextContent(type="text", text=f"Error: {e}")]

    elif name == "discogs_get_wantlist":
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
                  output.append(f"[Release ID: {rid}] {info.get('title')} - {', '.join([a.get('name') for a in info.get('artists', [])])}")
             return [TextContent(type="text", text="\n".join(output) or "Wantlist empty")]
        except Exception as e:
             return [TextContent(type="text", text=f"Error: {e}")]

    elif name == "discogs_add_to_wantlist":
        if not record_crate: return [TextContent(type="text", text="Record Crate not configured")]
        try:
             # Need username
             identity = await record_crate.get_identity()
             username = identity.get("username")
             if not username: return [TextContent(type="text", text="No username found")]

             release_id = arguments["release_id"]
             res = await record_crate.add_to_wantlist(
                 username,
                 release_id,
                 notes=arguments.get("notes"),
                 rating=arguments.get("rating")
             )

             title = res.get("basic_information", {}).get("title", "Unknown Title")
             return [TextContent(type="text", text=f"Added to Wantlist: {title} (ID: {release_id})")]
        except Exception as e:
             return [TextContent(type="text", text=f"Error: {e}")]

    elif name == "discogs_get_collection_folders":
        if not record_crate: return [TextContent(type="text", text="Record Crate not configured")]
        try:
            identity = await record_crate.get_identity()
            username = identity.get("username")
            if not username: return [TextContent(type="text", text="No username found")]

            data = await record_crate.get_collection_folders(username)
            folders = data.get("folders", [])
            output = "\n".join([f"[Folder ID: {f.get('id')}] {f.get('name')} ({f.get('count')} releases)" for f in folders])
            return [TextContent(type="text", text=output or "No folders found")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    elif name == "discogs_get_collection":
        if not record_crate: return [TextContent(type="text", text="Record Crate not configured")]
        try:
            identity = await record_crate.get_identity()
            username = identity.get("username")
            if not username: return [TextContent(type="text", text="No username found")]

            data = await record_crate.get_collection_releases(
                username,
                folder_id=arguments.get("folder_id", 0),
                page=arguments.get("page", 1),
                per_page=arguments.get("limit", 50),
                sort=arguments.get("sort"),
                sort_order=arguments.get("sort_order")
            )

            releases = data.get("releases", [])
            pagination = data.get("pagination", {})
            output = [f"Page {pagination.get('page', 1)} of {pagination.get('pages', 1)} ({pagination.get('items', 0)} total)\n"]

            for r in releases:
                info = r.get("basic_information", {})
                artists = ", ".join([a.get("name") for a in info.get("artists", [])])
                output.append(f"[Release ID: {info.get('id')}] {info.get('title')} - {artists} ({info.get('year', '')})")

            return [TextContent(type="text", text="\n".join(output) or "No releases")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    elif name == "discogs_add_to_collection":
        if not record_crate: return [TextContent(type="text", text="Record Crate not configured")]
        try:
            identity = await record_crate.get_identity()
            username = identity.get("username")
            if not username: return [TextContent(type="text", text="No username found")]

            release_id = arguments["release_id"]
            folder_id = arguments.get("folder_id", 1)

            if folder_id == 0:
                return [TextContent(type="text", text="Cannot add to folder 0 (All). Use folder 1 or another specific folder.")]

            result = await record_crate.add_to_collection(username, folder_id, release_id)
            instance_id = result.get("instance_id")
            return [TextContent(type="text", text=f"Added to Collection! Release ID: {release_id}, Instance ID: {instance_id}, Folder ID: {folder_id}")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    elif name == "discogs_move_release":
        if not record_crate: return [TextContent(type="text", text="Record Crate not configured")]
        try:
            identity = await record_crate.get_identity()
            username = identity.get("username")
            if not username: return [TextContent(type="text", text="No username found")]

            release_id = arguments["release_id"]
            new_folder_id = arguments["new_folder_id"]

            # Find the instance
            info = await record_crate.get_instance_info(username, release_id)
            if not info:
                return [TextContent(type="text", text=f"Release {release_id} not found in collection (checked first 1000 items).")]
            
            instance_id = info["instance_id"]
            current_folder_id = info["folder_id"]

            if current_folder_id == new_folder_id:
                return [TextContent(type="text", text=f"Release {release_id} is already in folder {new_folder_id}.")]

            await record_crate.move_release_instance(username, current_folder_id, release_id, instance_id, new_folder_id)
            return [TextContent(type="text", text=f"Moved release {release_id} from folder {current_folder_id} to {new_folder_id}.")]

        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    # Echo Locate Handlers
    elif name.startswith("echolocate_"):
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
                    steer_track_id=arguments.get("steer_track_id"),
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
                        enhanced_text = f"🤖 Enhanced Query: '{res.get('enhanced_query')}'\n\n"
                
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
