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
from apple_music import AppleMusicClient
from discogs import DiscogsClient
import httpx

# --- Secret Configuration ---

def get_secret(secret_name, default=None, force_gsm=False):
    """
    Attempts to fetch a secret from Google Secret Manager.
    Falls back to environment variable if:
    1. GOOGLE_CLOUD_PROJECT is not set (local dev).
    2. Secret Manager API call fails (permissions/disabled).
    3. force_gsm is False and Env Var is present.
    """
    # 1. Check Env Var first (unless forced to ignore)
    if not force_gsm:
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
            # If forced, we return default (or None) if GSM fails.
            pass

    return default

# Load Secrets
# Names here match the Env Var names AND the Secret Manager secret names
MCP_AUTH_SECRET = get_secret("MCP_AUTH_SECRET")
MCP_JWT_SECRET = get_secret("MCP_JWT_SECRET")
MCP_CLIENT_ID = get_secret("MCP_CLIENT_ID")
MCP_CLIENT_SECRET = get_secret("MCP_CLIENT_SECRET")

# Apple Music Secrets
APPLE_TEAM_ID = get_secret("APPLE_TEAM_ID")
APPLE_KEY_ID = get_secret("APPLE_KEY_ID")
APPLE_PRIVATE_KEY = get_secret("APPLE_PRIVATE_KEY")

# Discogs Secrets
DISCOGS_TOKEN = get_secret("DISCOGS_TOKEN")

# Store the User Token in memory for this simple implementation
# In production, this should be stored in a database linked to the authenticated user
# or in a session cookie. For now, we'll just store the last one logged in since this is single-user.
# We FORCE GSM check here because Cloud Run injects the *image build* (or revision) time env var,
# which might be stale if the secret was updated in GSM after deployment.
APPLE_MUSIC_USER_TOKEN = get_secret("APPLE_MUSIC_USER_TOKEN", force_gsm=True)

apple_client = None
if APPLE_TEAM_ID and APPLE_KEY_ID and APPLE_PRIVATE_KEY:
    try:
        apple_client = AppleMusicClient(APPLE_TEAM_ID, APPLE_KEY_ID, APPLE_PRIVATE_KEY)
        print("Apple Music Client initialized.")
    except Exception as e:
        print(f"Failed to initialize Apple Music Client: {e}")
else:
    print("Warning: Apple Music credentials not found. Music tools will be disabled.")

discogs_client = None
if DISCOGS_TOKEN:
    try:
        discogs_client = DiscogsClient(DISCOGS_TOKEN)
        print("Discogs Client initialized.")
    except Exception as e:
        print(f"Failed to initialize Discogs Client: {e}")
else:
    print("Warning: DISCOGS_TOKEN not found. Discogs tools will be disabled.")

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

# --- Admin Auth (Cookie-based) ---

async def login_page(request: Request):
    """
    Renders login page for browser access (e.g. Apple Auth).
    """
    next_url = request.query_params.get("next", "/apple-auth")
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Server Login</title>
        <style>
            body {{ font-family: system-ui; display: flex; justify-content: center; align-items: center; height: 100vh; background: #111; color: #eee; }}
            form {{ display: flex; flex-direction: column; gap: 1rem; width: 300px; }}
            input {{ padding: 10px; border-radius: 4px; border: 1px solid #333; background: #222; color: #fff; }}
            button {{ padding: 10px; background: #007aff; color: white; border: none; border-radius: 4px; cursor: pointer; }}
        </style>
    </head>
    <body>
        <form method="POST" action="/login">
            <h2>Admin Login</h2>
            <input type="hidden" name="next" value="{next_url}">
            <input type="password" name="password" placeholder="Server Password" required autofocus>
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
         
    # Issue Cookie Token
    now = time.time()
    payload = {
        "sub": "admin",
        "iat": now,
        "exp": now + (60 * 60 * 24), # 24 hours
        "type": "access"
    }
    token = jwt.encode(payload, MCP_JWT_SECRET, algorithm=ALGORITHM)
    
    response = RedirectResponse(next_url, status_code=303)
    response.set_cookie("access_token", token, httponly=True, secure=True)
    return response
    response = RedirectResponse(next_url, status_code=303)
    response.set_cookie("access_token", token, httponly=True, secure=True)
    return response

async def client_log(request: Request):
    """
    Receives logs from the client-side JS for debugging.
    """
    try:
        data = await request.json()
        print(f"CLIENT LOG: {data}")
    except Exception as e:
        print(f"Error receiving client log: {e}")
    return JSONResponse({"status": "ok"})


async def apple_login_page(request: Request):
    """
    Renders the Apple Music login page using MusicKit JS.
    """
    if not apple_client:
        return HTMLResponse("Apple Music Client not configured.", status_code=500)
        
    dev_token = apple_client.get_developer_token()
    
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Link Apple Music</title>
        <script src="https://js-cdn.music.apple.com/musickit/v3/musickit.js"></script>
        <style>
            body { font-family: system-ui; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; background: #000; color: #fff; }
            button { padding: 15px 30px; font-size: 18px; border-radius: 8px; border: none; background: #fa243c; color: white; cursor: pointer; }
        </style>
    </head>
    <body>
        <h1>Link Apple Music</h1>
        <button id="login-btn">Log In with Apple Music</button>
        <p id="status"></p>
        
        <script>
            async function logError(msg, details) {
                console.error(msg, details);
                try {
                    await fetch('/client-log', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ error: msg, details: details ? String(details) : '' })
                    });
                } catch (e) {
                    console.error("Failed to send log", e);
                }
            }

            document.addEventListener('musickitloaded', async function() {
                console.log("MusicKit loaded");
                try {
                    const music = await MusicKit.configure({
                        developerToken: '{{dev_token}}',
                        app: {
                            name: 'Cloud Crate',
                            build: '1.0.0'
                        }
                    });
                    console.log("MusicKit configured");
                    document.getElementById('status').innerText = "Ready to authorize.";
                    
                    document.getElementById('login-btn').addEventListener('click', async () => {
                        console.log("Login button clicked");
                        document.getElementById('status').innerText = "Authorizing... please check for popups.";
                        try {
                            const res = await music.authorize();
                            await logError("Authorize success", res); // Log success too for debugging
                            
                            const userToken = music.musicUserToken;
                            console.log("User Token:", userToken);
                            
                            if (!userToken) {
                                throw new Error("No user token returned");
                            }

                            document.getElementById('status').innerText = "Authorized! Saving token...";
                            
                            // Send token to backend
                            const fetchRes = await fetch('/apple-auth/callback', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ token: userToken })
                            });
                            
                            if (fetchRes.ok) {
                                document.getElementById('status').innerText = "Success! You can close this window.";
                                alert("Success! You are logged in.");
                            } else {
                                const errText = await fetchRes.text();
                                await logError("Error saving token", errText);
                                document.getElementById('status').innerText = "Error saving token: " + errText;
                                alert("Error saving token: " + errText);
                            }
                        } catch (err) {
                            await logError("Auth error during interaction", err);
                            document.getElementById('status').innerText = "Authorization failed: " + err;
                            alert("Authorization failed: " + err);
                        }
                    });
                } catch (err) {
                    await logError("Config error", err);
                    document.getElementById('status').innerText = "Config Error: " + err;
                    alert("Config error: " + err);
                }
            });
        </script>
    </body>
    </html>
    """
    # Replace the f-string formatting for dev_token since we used {{ for js
    html = html.replace('{{dev_token}}', dev_token)
    return HTMLResponse(html)

async def apple_callback(request: Request):
    """
    Receives the User Token from the frontend.
    """
    global APPLE_MUSIC_USER_TOKEN
    data = await request.json()
    token = data.get("token")
    if token:
        APPLE_MUSIC_USER_TOKEN = token
        # In a real app, save this to permanent storage (Secret Manager)
        # Here we just print it or store in memory for the session
        print(f"Received Apple Music User Token: {token[:10]}...")
        
        # Optional: Attempt to persist to GSM if running in Cloud
        # This is a bit "magical" but helpful for single-user setup
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        if project_id:
             try:
                from google.cloud import secretmanager
                client = secretmanager.SecretManagerServiceClient()
                parent = f"projects/{project_id}"
                # Create secret if not exists?
                parent_secret = f"{parent}/secrets/APPLE_MUSIC_USER_TOKEN"
                
                # Check if secret exists, if not create it
                try:
                    client.get_secret(request={"name": parent_secret})
                except Exception:
                    print(f"Secret {parent_secret} not found. Creating it...")
                    client.create_secret(
                        request={
                            "parent": parent,
                            "secret_id": "APPLE_MUSIC_USER_TOKEN",
                            "secret": {"replication": {"automatic": {}}},
                        }
                    )

                # Add new version
                payload = token.encode("UTF-8")
                client.add_secret_version(request={"parent": parent_secret, "payload": {"data": payload}})
                print("Updated APPLE_MUSIC_USER_TOKEN in Secret Manager.")
             except Exception as e:
                 print(f"Could not update secret in GSM: {e}")
        
        return JSONResponse({"status": "success"})
    return JSONResponse({"error": "missing_token"}, status_code=400)

# --- Middleware ---

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Public endpoints
        if request.url.path in ["/", "/health", "/authorize", "/token", "/login"]:
            return await call_next(request)
        
        # 1. Check Header (MCP Client)
        auth_header = request.headers.get("Authorization")
        token = None
        
        if auth_header and auth_header.startswith("Bearer "):
             token = auth_header.split(" ")[1]
             
        # 2. Check Cookie (Browser Admin)
        if not token:
            token = request.cookies.get("access_token")
        
        if not token:
             # Redirect browser requests to login
             if request.url.path.startswith("/apple-auth"):
                 # If it's the callback POST or an API call (AJAX), return 401 instead of redirecting HTML
                 # This prevents "406 Not Acceptable" if the client expects JSON or follows the redirect to HTML
                 accept = request.headers.get("accept", "")
                 is_xhr = request.headers.get("x-requested-with") == "XMLHttpRequest"
                 if request.url.path.endswith("/callback") or request.url.path.endswith("/client-log") or "application/json" in accept or is_xhr:
                     return JSONResponse({"error": "Unauthorized"}, status_code=401)
                     
                 return RedirectResponse(f"/login?next={request.url.path}")
                 
             return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        try:
            # Verify JWT
            payload = jwt.decode(token, MCP_JWT_SECRET, algorithms=[ALGORITHM])
            # if payload.get("type") != "access":
            #      raise ValueError("Invalid token type")
            request.state.user = payload
        except Exception as e:
            if request.url.path.startswith("/apple-auth"):
                 accept = request.headers.get("accept", "")
                 is_xhr = request.headers.get("x-requested-with") == "XMLHttpRequest"
                 if request.url.path.endswith("/callback") or request.url.path.endswith("/client-log") or "application/json" in accept or is_xhr:
                     return JSONResponse({"error": "Unauthorized"}, status_code=401)
                     
                 return RedirectResponse(f"/login?next={request.url.path}")
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
        ),
        Tool(
            name="search_apple_music",
            description="Search for songs in the Apple Music Catalog.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term"},
                    "limit": {"type": "integer", "description": "Max results (default 5)"}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="create_playlist",
            description="Create a new playlist in Apple Music.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Playlist name"},
                    "description": {"type": "string", "description": "Playlist description"},
                    "track_ids": {"type": "array", "items": {"type": "string"}, "description": "List of track IDs"}
                },
                "required": ["name", "track_ids"]
            }
        ),
        Tool(
            name="get_track_context",
            description="Get details for a catalog track.",
            inputSchema={
                "type": "object",
                "properties": {
                    "track_id": {"type": "string", "description": "Catalog Track ID"}
                },
                "required": ["track_id"]
            }
        ),
        Tool(
            name="search_discogs",
            description="Search for albums (master releases) on Discogs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term (album name, artist, etc.)"},
                    "limit": {"type": "integer", "description": "Max results (default 5)"}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_discogs_versions",
            description="Get all versions of a master release from Discogs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "master_id": {"type": "string", "description": "Master Release ID"},
                    "page": {"type": "integer", "description": "Page number (default 1)"},
                    "limit": {"type": "integer", "description": "Results per page (default 10)"}
                },
                "required": ["master_id"]
            }
        ),
        Tool(
            name="get_discogs_release",
            description="Get details of a specific Discogs release.",
            inputSchema={
                "type": "object",
                "properties": {
                    "release_id": {"type": "string", "description": "Release ID"}
                },
                "required": ["release_id"]
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
    elif name == "search_apple_music":
        if not apple_client:
            return [TextContent(type="text", text="Apple Music is not configured on this server.")]
        
        query = arguments.get("query")
        limit = arguments.get("limit", 5)
        try:
            # Search
            data = await apple_client.search(query, limit=limit)
            results = data.get("results", {}).get("songs", {}).get("data", [])
            
            if not results:
                result = "No results found."
            else:
                formatted = []
                for item in results:
                    attrs = item.get("attributes", {})
                    formatted.append(f"""
---
Track ID: catalog:{item['id']}
Title: {attrs.get('name')}
Artist: {attrs.get('artistName')}
Album: {attrs.get('albumName')}
""")
                result = "".join(formatted)
        except Exception as e:
            result = f"Error searching Apple Music: {e}"

    elif name == "create_playlist":
        if not apple_client:
             return [TextContent(type="text", text="Apple Music is not configured on this server.")]
        if not APPLE_MUSIC_USER_TOKEN:
             return [TextContent(type="text", text="User is not logged in to Apple Music. Please visit /apple-auth to log in.")]
             
        playlist_name = arguments.get("name")
        description = arguments.get("description", "Created via Cloud Crate Remote")
        track_ids = arguments.get("track_ids", [])
        
        try:
            data = await apple_client.create_playlist(playlist_name, description, track_ids, APPLE_MUSIC_USER_TOKEN)
            # Inspect result
            # API returns the created resource
            if data and "data" in data and len(data["data"]) > 0:
                new_id = data["data"][0]["id"]
                result = f"Successfully created playlist '{playlist_name}' (ID: {new_id})."
            else:
                result = "Playlist created but no ID returned?"
        except Exception as e:
            result = f"Error creating playlist: {e}"

    elif name == "get_track_context":
        if not apple_client:
             return [TextContent(type="text", text="Apple Music is not configured on this server.")]
             
        track_id = arguments.get("track_id")
        if track_id.startswith("catalog:"):
            track_id = track_id.split(":", 1)[1]
            
        try:
            data = await apple_client.get_resource(track_id, "songs")
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
        except Exception as e:
            result = f"Error fetching track: {e}"

    elif name == "search_discogs":
        if not discogs_client:
            return [TextContent(type="text", text="Discogs is not configured on this server.")]
        
        query = arguments.get("query")
        limit = arguments.get("limit", 5)
        try:
            data = await discogs_client.search(query, type="master", limit=limit)
            results = data.get("results", [])
            if not results:
                result = "No results found."
            else:
                formatted = []
                for item in results:
                    formatted.append(f"""
---
Master ID: {item.get('id')}
Title: {item.get('title')}
Year: {item.get('year', 'Unknown')}
Format: {', '.join(item.get('format', []))}
Thumb: {item.get('thumb', '')}
""")
                result = "".join(formatted)
        except Exception as e:
             result = f"Error searching Discogs: {e}"

    elif name == "get_discogs_versions":
        if not discogs_client:
             return [TextContent(type="text", text="Discogs is not configured on this server.")]
        
        master_id = arguments.get("master_id")
        page = arguments.get("page", 1)
        limit = arguments.get("limit", 10) # default to 10 for readability
        
        try:
            data = await discogs_client.get_master_versions(master_id, page=page, per_page=limit)
            versions = data.get("versions", [])
            pagination = data.get("pagination", {})
            
            if not versions:
                 result = "No versions found."
            else:
                 formatted = [f"Found {pagination.get('items', 0)} versions (Page {page}/{pagination.get('pages', 0)}):"]
                 for v in versions:
                     # Construct marketplace URL
                     mkt_url = discogs_client.get_marketplace_url(v.get('id'))
                     formatted.append(f"""
---
Release ID: {v.get('id')}
Title: {v.get('title')}
Format: {v.get('format', 'Unknown')}
Label: {v.get('label', 'Unknown')}
Country: {v.get('country', 'Unknown')}
Year: {v.get('released', 'Unknown')}
Marketplace: {mkt_url}
""")
                 result = "".join(formatted)
        except Exception as e:
             result = f"Error fetching versions: {e}"

    elif name == "get_discogs_release":
        if not discogs_client:
             return [TextContent(type="text", text="Discogs is not configured on this server.")]
        
        release_id = arguments.get("release_id")
        try:
            data = await discogs_client.get_release(release_id)
            # Basic basic details
            result = f"""
Title: {data.get('title')}
Artists: {', '.join([a.get('name') for a in data.get('artists', [])])}
Year: {data.get('year')}
Country: {data.get('country')}
Notes: {data.get('notes', 'None')}
Marketplace URL: {discogs_client.get_marketplace_url(release_id)}
Tracklist:
"""
            for track in data.get('tracklist', []):
                 result += f"- {track.get('position')}: {track.get('title')} ({track.get('duration')})\n"
                 
        except Exception as e:
             result = f"Error fetching release: {e}"

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
        
        # Apple Music Auth
        Route("/apple-auth", apple_login_page, methods=["GET"]),
        Route("/apple-auth", apple_login_page, methods=["GET"]),
        Route("/apple-auth/callback", apple_callback, methods=["POST"]),
        Route("/client-log", client_log, methods=["POST"]),
        
        # Admin Login
        Route("/login", login_page, methods=["GET"]),
        Route("/login", login_submit, methods=["POST"]),
        
        # Mount the session manager at root ("/") as a catch-all.
        Mount("/", app=manager.handle_request),
    ],
    middleware=[Middleware(AuthMiddleware)],
    lifespan=lifespan
)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
