import duckdb
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Literal
from datetime import timedelta
import os
import uvicorn
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig
import numpy as np
import math
import torch
from transformers import AutoProcessor, ClapModel
from google.cloud import storage

# GCS Configuration for audio streaming
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "cloud-crate-vector-db")
GCS_AUDIO_PREFIX = os.getenv("GCS_AUDIO_PREFIX", "fma/fma_full/fma_full")

# SLERP Utility
def slerp(v0, v1, t=0.5):
    """
    Spherical Linear Interpolation.
    v0, v1: Lists or arrays of floats (the vectors)
    t: float, interpolation factor (0.0 to 1.0). Default 0.5 for midpoint.
    """
    v0 = np.array(v0)
    v1 = np.array(v1)
    
    # Normalize vectors to unit length to ensure they are on the hypersphere
    v0_norm = v0 / np.linalg.norm(v0)
    v1_norm = v1 / np.linalg.norm(v1)
    
    dot = np.dot(v0_norm, v1_norm)
    
    # Clamp dot product to [-1, 1] to avoid floating point errors with arccos
    dot = np.clip(dot, -1.0, 1.0)
    
    # If vectors are too close (dot ~ 1) or opposite (dot ~ -1), fall back to linear
    # to avoid division by zero in sin()
    if dot > 0.9995:
        return (v0 + v1) / 2.0
        
    theta_0 = np.arccos(dot)
    sin_theta_0 = np.sin(theta_0)
    
    theta_t = theta_0 * t
    sin_theta_t = np.sin(theta_t)
    
    s0 = np.sin(theta_0 - theta_t) / sin_theta_0
    s1 = sin_theta_t / sin_theta_0
    
    return (s0 * v0 + s1 * v1).tolist()

def quadratic_bezier_slerp(v0, v1, v2, t):
    """
    Computes a point on a Quadratic Bezier curve on the hypersphere.
    v0: Start Vector
    v1: Control Vector (The Steering Track)
    v2: End Vector
    t: 0.0 to 1.0
    """
    # Step 1: Interpolate between Start and Control
    q0 = slerp(v0, v1, t)
    
    # Step 2: Interpolate between Control and End
    q1 = slerp(v1, v2, t)
    
    # Step 3: Interpolate between the two intermediate points
    return slerp(q0, q1, t)

def get_midpoint(vec_a, vec_b, method="slerp"):
    if method == "linear":
        # Old method: simple average
        return [(a + b) / 2.0 for a, b in zip(vec_a, vec_b)]
    else:
        # New default: SLERP
        return slerp(vec_a, vec_b, 0.5)


app = FastAPI()

# CORS middleware - allow frontend to call API from different origin
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
DB_PATH = os.getenv("DB_PATH", "cloudcrate.duckdb")
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
LOCATION = os.getenv("GCP_LOCATION", "us-central1")

# Global models
gemini_model = None

# Pydantic Models
class SearchRequest(BaseModel):
    vector: List[float]
    limit: Optional[int] = 10
    source: Optional[Literal["library", "fma", "all"]] = "library"

class SearchResult(BaseModel):
    id: str
    source: Optional[str] = None
    title: str
    artist: str
    album: str
    relative_path: str
    similarity: float
    track_url: Optional[str] = None
    album_url: Optional[str] = None
    artist_url: Optional[str] = None

class TrackResponse(BaseModel):
    id: str
    source: Optional[str] = None
    title: str
    artist: str
    album: str
    relative_path: str
    track_url: Optional[str] = None
    album_url: Optional[str] = None
    artist_url: Optional[str] = None

class InterpolationRequest(BaseModel):
    track_id_1: str
    track_id_2: str
    limit: Optional[int] = 10
    method: Optional[Literal["slerp", "linear", "greedy_walk"]] = "greedy_walk"

class SemanticSearchRequest(BaseModel):
    query: str
    limit: Optional[int] = 10
    source: Optional[Literal["library", "fma", "all"]] = "library"
    enhance: Optional[bool] = False  # Toggle for the agent

# Wrapper for the full response
class SemanticSearchResponse(BaseModel):
    results: List[SearchResult]
    enhanced_query: Optional[str] = None
    original_query: str

# CLAP Model (lazy-loaded on first semantic search request)
clap_model = None
clap_processor = None
CLAP_MODEL_NAME = "laion/clap-htsat-unfused"

def run_agent_enhancement(raw_query: str) -> str:
    """Runs the Gemini Agent to expand the query."""
    if not gemini_model:
        return raw_query

    try:
        # We don't need to send the system prompt here; it's baked into the model init
        response = gemini_model.generate_content(
            f"Input: '{raw_query}'",
            generation_config=GenerationConfig(
                temperature=0.3, # Low temp = more consistent/technical results
                max_output_tokens=60,
                candidate_count=1
            )
        )
        expanded = response.text.strip()
        print(f"🤖 Agent: '{raw_query}' -> '{expanded}'")
        return expanded
    except Exception as e:
        print(f"❌ Agent Error: {e}")
        return raw_query

def get_clap_model():
    """
    Lazy-load the CLAP model on first use.
    This avoids blocking startup and exceeding Cloud Run's timeout.
    Uses local_files_only=True since model is pre-cached in Docker image.
    """
    global clap_model, clap_processor
    
    if clap_model is None:
        print(f"Loading CLAP model: {CLAP_MODEL_NAME}...")
        clap_model = ClapModel.from_pretrained(CLAP_MODEL_NAME, local_files_only=True)
        clap_processor = AutoProcessor.from_pretrained(CLAP_MODEL_NAME, local_files_only=True)
        clap_model.eval()
        print("CLAP model loaded successfully.")
    
    return clap_model, clap_processor

@app.on_event("startup")
async def startup_event():
    # 1. Initialize Vertex AI (The Agent)
    global gemini_model
    if PROJECT_ID:
        try:
            vertexai.init(project=PROJECT_ID, location=LOCATION)
            
            # Define the Agent's Persona here
            system_instruction = """You are an expert audio engineer. Convert short user queries into detailed audio captions for a LAION-CLAP model. 
            Describe instrumentation, mood, and texture in a single technical sentence under 30 words. Output ONLY the caption."""
            
            gemini_model = GenerativeModel(
                "gemini-2.0-flash-001",
                system_instruction=[system_instruction]
            )
            print(f"✅ Vertex AI Agent initialized: {PROJECT_ID}")
        except Exception as e:
            print(f"⚠️ Vertex AI failed to initialize: {e}")
    else:
        print("ℹ️ GCP_PROJECT_ID not set. Enhanced search disabled.")

    # 2. Verify DB
    if not os.path.exists(DB_PATH):
        print(f"⚠️ WARNING: Database file not found at {DB_PATH}")
    else:
        print(f"Database found at {DB_PATH}")
    
    print("CLAP model will be loaded on first semantic search request.")

def get_db_connection():
    # Connect in Read-Only mode to allow concurrency/cloud run compatibility
    # Note: We need to load vss every time for the connection
    con = duckdb.connect(DB_PATH, read_only=True)
    con.execute("INSTALL vss; LOAD vss;") 
    return con

@app.get("/")
def health_check():
    """API health check."""
    return {"status": "ok", "service": "cloudcrate-vector"}

@app.get("/stream/{track_id}")
def stream_audio(track_id: str):
    """
    Stream audio from GCS by proxying the bytes.
    Maps track_id (e.g., 'fma_50833') to GCS path.
    """
    try:
        # Extract numeric ID: fma_50833 -> 50833
        num_id = track_id.replace("fma_", "")
        padded = num_id.zfill(6)
        prefix = padded[:3]
        
        # Build GCS path: fma/fma_full/fma_full/050/050833.mp3
        blob_path = f"{GCS_AUDIO_PREFIX}/{prefix}/{padded}.mp3"
        
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(blob_path)
        
        if not blob.exists():
            raise HTTPException(status_code=404, detail=f"Audio file not found: {blob_path}")
        
        # Reload metadata to get file size for Content-Length header
        blob.reload()
        
        def stream_blob():
            with blob.open("rb") as f:
                while chunk := f.read(8192):
                    yield chunk
        
        return StreamingResponse(
            stream_blob(),
            media_type="audio/mpeg",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(blob.size),
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error streaming audio for {track_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tracks", response_model=List[TrackResponse])
def list_tracks(limit: int = 50, offset: int = 0, random: bool = True, source: Literal["library", "fma", "all"] = "library"):
    try:
        con = get_db_connection()
        source_filter = "" if source == "all" else f"WHERE source = '{source}'"
        
        if random:
            query = f"SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url FROM tracks {source_filter} ORDER BY RANDOM() LIMIT ?"
            results = con.execute(query, [limit]).fetchall()
        else:
            where_or_and = "WHERE" if source == "all" else "AND"
            query = f"SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url FROM tracks {source_filter} ORDER BY id LIMIT ? OFFSET ?"
            results = con.execute(query, [limit, offset]).fetchall()
        con.close()
        
        response = []
        for row in results:
            response.append(TrackResponse(
                id=row[0],
                source=row[1],
                title=row[2],
                artist=row[3],
                album=row[4],
                relative_path=row[5],
                track_url=row[6],
                album_url=row[7],
                artist_url=row[8]
            ))
        return response
    except Exception as e:
        print(f"Error listing tracks: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tracks/{track_id}/similar", response_model=List[SearchResult])
def find_similar(track_id: str, limit: int = 10, source: Literal["library", "fma", "all"] = "library"):
    try:
        con = get_db_connection()
        
        # 1. Get the vector for the target track
        vector_query = "SELECT v_mid, source FROM tracks WHERE id = ?"
        vector_result = con.execute(vector_query, [track_id]).fetchone()
        
        if not vector_result:
            con.close()
            raise HTTPException(status_code=404, detail="Track not found")
            
        target_vector = vector_result[0]
        
        # 2. Search for similar tracks, excluding the track itself
        source_filter = "" if source == "all" else f"AND source = '{source}'"
        query = f"""
            SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url,
                   array_cosine_similarity(v_mid, ?::FLOAT[768]) as similarity
            FROM tracks
            WHERE id != ? {source_filter}
            ORDER BY similarity DESC
            LIMIT ?
        """
        
        results = con.execute(query, [target_vector, track_id, limit]).fetchall()
        con.close()
        
        response = []
        for row in results:
            response.append(SearchResult(
                id=row[0],
                source=row[1],
                title=row[2],
                artist=row[3],
                album=row[4],
                relative_path=row[5],
                track_url=row[6],
                album_url=row[7],
                artist_url=row[8],
                similarity=row[9]
            ))
            
        return response
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error finding similar tracks: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tracks/{track_id}/dissimilar", response_model=List[SearchResult])
def find_dissimilar(track_id: str, limit: int = 10, source: Literal["library", "fma", "all"] = "library"):
    try:
        con = get_db_connection()
        
        # 1. Get the vector for the target track
        vector_query = "SELECT v_mid, source FROM tracks WHERE id = ?"
        vector_result = con.execute(vector_query, [track_id]).fetchone()
        
        if not vector_result:
            con.close()
            raise HTTPException(status_code=404, detail="Track not found")
            
        target_vector = vector_result[0]
        
        # 2. Search for DISSIMILAR tracks, excluding the track itself
        # We use ORDER BY similarity ASC to find the ones with lowest cosine similarity
        source_filter = "" if source == "all" else f"AND source = '{source}'"
        query = f"""
            SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url,
                   array_cosine_similarity(v_mid, ?::FLOAT[768]) as similarity
            FROM tracks
            WHERE id != ? {source_filter}
            ORDER BY similarity ASC
            LIMIT ?
        """
        
        results = con.execute(query, [target_vector, track_id, limit]).fetchall()
        con.close()
        
        response = []
        for row in results:
            response.append(SearchResult(
                id=row[0],
                source=row[1],
                title=row[2],
                artist=row[3],
                album=row[4],
                relative_path=row[5],
                track_url=row[6],
                album_url=row[7],
                artist_url=row[8],
                similarity=row[9]
            ))
            
        return response
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error finding dissimilar tracks: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/search", response_model=List[TrackResponse])
def search_tracks_text(
    query: Optional[str] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    title: Optional[str] = None,
    limit: int = 20,
    source: Literal["library", "fma", "all"] = "library"
):
    """Text-based search by artist, album, or title."""
    try:
        con = get_db_connection()
        
        # Build WHERE clause dynamically
        conditions = []
        params = []
        
        # Add source filter first
        if source != "all":
            conditions.append("source = ?")
            params.append(source)
        
        if query:
            conditions.append("(title ILIKE ? OR artist ILIKE ? OR album ILIKE ?)")
            search_term = f"%{query}%"
            params.extend([search_term, search_term, search_term])
        if artist:
            conditions.append("artist ILIKE ?")
            params.append(f"%{artist}%")
        if album:
            conditions.append("album ILIKE ?")
            params.append(f"%{album}%")
        if title:
            conditions.append("title ILIKE ?")
            params.append(f"%{title}%")
        
        # Need at least one search term (besides source)
        search_conditions = len([c for c in [query, artist, album, title] if c])
        if search_conditions == 0:
            con.close()
            raise HTTPException(status_code=400, detail="At least one search parameter required: query, artist, album, or title")
        
        where_clause = " AND ".join(conditions)
        sql = f"SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url FROM tracks WHERE {where_clause} LIMIT ?"
        params.append(limit)
        
        results = con.execute(sql, params).fetchall()
        con.close()
        
        response = []
        for row in results:
            response.append(TrackResponse(
                id=row[0],
                source=row[1],
                title=row[2],
                artist=row[3],
                album=row[4],
                relative_path=row[5],
                track_url=row[6],
                album_url=row[7],
                artist_url=row[8]
            ))
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error during text search: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/vector-search", response_model=List[SearchResult])
def vector_search_tracks(request: SearchRequest):
    try:
        con = get_db_connection()
        
        if len(request.vector) != 768:
            raise HTTPException(status_code=400, detail=f"Vector must be 768 dimensions, got {len(request.vector)}")

        source_filter = "" if request.source == "all" else f"WHERE source = '{request.source}'"
        
        query = f"""
            SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url,
                   array_cosine_similarity(v_mid, ?::FLOAT[768]) as similarity
            FROM tracks
            {source_filter}
            ORDER BY similarity DESC
            LIMIT ?
        """
        
        results = con.execute(query, [request.vector, request.limit]).fetchall()
        con.close()
        
        response = []
        for row in results:
            response.append(SearchResult(
                id=row[0],
                source=row[1],
                title=row[2],
                artist=row[3],
                album=row[4],
                relative_path=row[5],
                track_url=row[6],
                album_url=row[7],
                artist_url=row[8],
                similarity=row[9]
            ))
            
        return response

    except Exception as e:
        print(f"Error during search: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/semantic-search", response_model=SemanticSearchResponse)
def semantic_search(request: SemanticSearchRequest):
    try:
        # 1. Agent Layer (Query Expansion)
        final_search_text = request.query
        enhanced_query_text = None

        if request.enhance:
            enhanced_query_text = run_agent_enhancement(request.query)
            final_search_text = enhanced_query_text

        # 2. Vectorization Layer (CLAP)
        model, processor = get_clap_model()
        
        # Tokenize
        text_inputs = processor(text=[final_search_text], padding=True, return_tensors="pt")
        
        # Embed & Normalize
        with torch.no_grad():
            text_features = model.get_text_features(**text_inputs)
            text_features = text_features / text_features.norm(dim=-1, keepdim=True)
        
        query_vector = text_features.squeeze(0).cpu().numpy().tolist()
        
        # 3. Retrieval Layer (DuckDB)
        con = get_db_connection()
        source_filter = "AND source = '" + request.source + "'" if request.source != "all" else ""
        
        # Ensure dimensions match your DB (likely 512 for HTSAT-unfused)
        query_sql = f"""
            SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url,
                   array_cosine_similarity(v_clap, ?::FLOAT[512]) as similarity
            FROM tracks
            WHERE v_clap IS NOT NULL {source_filter}
            ORDER BY similarity DESC
            LIMIT ?
        """
        
        results = con.execute(query_sql, [query_vector, request.limit]).fetchall()
        con.close()
        
        # 4. Response Construction
        track_results = []
        for row in results:
            track_results.append(SearchResult(
                id=row[0], source=row[1], title=row[2], artist=row[3],
                album=row[4], relative_path=row[5], track_url=row[6],
                album_url=row[7], artist_url=row[8], similarity=row[9]
            ))
        
        return SemanticSearchResponse(
            results=track_results,
            original_query=request.query,
            enhanced_query=enhanced_query_text # Returns the agent's "thought"
        )
    
    except Exception as e:
        print(f"Error during semantic search: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/interpolate", response_model=List[SearchResult])
def interpolate_tracks(request: InterpolationRequest):
    try:
        con = get_db_connection()
        
        # 1. Get vectors for both tracks
        query_vectors = "SELECT id, v_mid FROM tracks WHERE id IN (?, ?)"
        results = con.execute(query_vectors, [request.track_id_1, request.track_id_2]).fetchall()
        
        if len(results) != 2:
            con.close()
            found_ids = [r[0] for r in results]
            missing = set([request.track_id_1, request.track_id_2]) - set(found_ids)
            raise HTTPException(status_code=404, detail=f"Could not find tracks: {missing}")

        vec1 = results[0][1]
        vec2 = results[1][1]
        
        # 2. Compute midpoint (v1 + v2) / 2
        # Note: Since we are doing Cosine distance, the magnitude doesn't strictly matter for the 'direction',
        # but averaging them is the standard 'midpoint' in vector space.
        # We can implement vector addition in Python easily since they are lists/arrays.
        
        # 2. Compute midpoint
        print(f"Interpolating with method: {request.method}")
        midpoint_vector = get_midpoint(vec1, vec2, request.method)
        print(f"Midpoint vector first 3 dim: {midpoint_vector[:3]}")
        
        # 3. Search for nearest neighbors to the midpoint
        # We exclude the two input tracks from the results
        query = """
            SELECT id, title, artist, album, relative_path, array_cosine_similarity(v_mid, ?::FLOAT[768]) as similarity
            FROM tracks
            WHERE id NOT IN (?, ?)
            ORDER BY similarity DESC
            LIMIT ?
        """
        
        search_results = con.execute(query, [midpoint_vector, request.track_id_1, request.track_id_2, request.limit]).fetchall()
        con.close()
        
        response = []
        for row in search_results:
            response.append(SearchResult(
                id=row[0],
                title=row[1],
                artist=row[2],
                album=row[3],
                relative_path=row[4],
                similarity=row[5]
            ))
            
        return response
        
    except Exception as e:
        print(f"Error during interpolation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class InterpolationPlaylistRequest(BaseModel):
    track_id_1: str
    track_id_2: str
    limit: Optional[int] = 10
    method: Optional[Literal["slerp", "linear", "greedy_walk"]] = "greedy_walk"
    steer_track_id: Optional[str] = None # New optional field
    source: Optional[Literal["library", "fma", "all"]] = "all"


def bezier_interpolation(con, vec_start, vec_control, vec_end, exclude_ids, limit=10):
    path = []
    
    # We want 'limit' items total (excluding start/end).
    # We generate equidistant time steps along the curve.
    steps = limit + 1 
    
    for i in range(1, steps):
        t = i / steps
        
        # Calculate the theoretical point on the curve
        target_vector = quadratic_bezier_slerp(vec_start, vec_control, vec_end, t)
        
        # Find the nearest REAL song to this theoretical point
        query = """
            SELECT id, title, artist, album, relative_path, v_mid, array_cosine_similarity(v_mid, ?::FLOAT[768]) as similarity
            FROM tracks
            ORDER BY similarity DESC
            LIMIT 20
        """
        
        candidates = con.execute(query, [target_vector]).fetchall()
        
        best_match = None
        for cand in candidates:
            # Simple exclusion of visited IDs
            if cand[0] not in exclude_ids:
                best_match = cand
                break
        
        if best_match:
            exclude_ids.add(best_match[0])
            path.append(SearchResult(
                id=best_match[0], title=best_match[1], artist=best_match[2], 
                album=best_match[3], relative_path=best_match[4], similarity=best_match[6]
            ))
            
    return path

def greedy_walk_interpolation(con, start_vec, end_vec, start_id, end_id, start_artist, end_artist, limit=10, source="all"):
    current_vec = start_vec
    path = []
    
    # Track visited IDs and Artists to prevent loops and ensure diversity
    visited_ids = {start_id, end_id}
    visited_artists = {start_artist, end_artist}
    
    # Pre-calculate source filter clause
    source_filter = ""
    source_param = []
    if source != "all":
        source_filter = "AND source = ?"
        source_param = [source]

    # We loop up to 'limit' times to generate intermediate tracks
    for _ in range(limit):
        
        # 1. Efficient Two-Step Query
        # Inner Query: Find the "Neighborhood" (top 50 closest to CURRENT track)
        # Outer Query: specific the best step towards the TARGET track
        # We can't easily filter artists inside the subquery efficiently without blowing up the result set size checking,
        # so we fetch candidates and filter in Python or use a WHERE clause if list is small.
        # Passing string lists to UNNEST in DuckDB python client can sometimes be finicky with quoting, 
        # so let's try fetch-and-filter for robustness + simplicity given the small N (limit 50).
        
        query = f"""
            WITH neighborhood AS (
                SELECT id, title, artist, album, relative_path, v_mid, source, track_url, album_url, artist_url,
                       array_cosine_similarity(v_mid, ?::FLOAT[768]) as sim_to_current
                FROM tracks
                WHERE 1=1 {source_filter}
                ORDER BY sim_to_current DESC
                LIMIT 50
            )
            SELECT id, title, artist, album, relative_path, v_mid, source, track_url, album_url, artist_url,
                   array_cosine_similarity(v_mid, ?::FLOAT[768]) as sim_to_target
            FROM neighborhood
            WHERE id NOT IN (SELECT UNNEST(?)) 
            ORDER BY sim_to_target DESC
        """
        
        # Convert set to list for DuckDB binding
        visited_list = list(visited_ids)
        
        # Execute query: [current_pos, source_param(if any), target_pos, exclude_list]
        params = [current_vec] + source_param + [end_vec, visited_list]
        candidates = con.execute(query, params).fetchall()
        
        best_next = None
        for cand in candidates:
            cand_id = cand[0]
            cand_artist = cand[2]
            
            # Check artist uniqueness
            if cand_artist in visited_artists:
                continue
                
            best_next = cand
            break
        
        # If we hit a dead end (no valid neighbors), stop
        if not best_next:
            break
            
        # Parse result
        next_track = SearchResult(
            id=best_next[0], 
            title=best_next[1], 
            artist=best_next[2], 
            album=best_next[3], 
            relative_path=best_next[4],
            source=best_next[6],
            track_url=best_next[7],
            album_url=best_next[8],
            artist_url=best_next[9],
            similarity=best_next[10] # Similarity to TARGET
        )
        
        path.append(next_track)
        visited_ids.add(best_next[0])
        visited_artists.add(best_next[2])
        current_vec = best_next[5] # Move our position to this new song
        
        # Optimization: Early exit if we are extremely close to the target
        if best_next[10] > 0.98:
            break
            
    return path

def recursive_interpolation(con, vec_a, vec_b, exclude_ids, exclude_artists, depth_limit, method="slerp"):
    if depth_limit <= 0:
        return []

    # Calculate midpoint using the requested method
    midpoint_vector = get_midpoint(vec_a, vec_b, method)

    # Find nearest neighbor to midpoint (excluding current chain)
    # We query for top 1 that is NOT in exclude_ids
    # Note: We need to pass exclude_ids as a parameter to the query or filter in code
    # DuckDB list support in prepared statements can be tricky, so we might need to format the string 
    # if the list is long, but for playlist generation (small set), passing as parameters or filtering is fine.
    # To be safe and simple with DuckDB python client:
    
    query = """
        SELECT id, title, artist, album, relative_path, v_mid, array_cosine_similarity(v_mid, ?::FLOAT[768]) as similarity
        FROM tracks
        ORDER BY similarity DESC
        LIMIT 20
    """
    # Fetch a few candidates to filter out exclude_ids manually since passing a dynamic list to NOT IN is hard 
    # with this specific driver/binding setup sometimes. 
    
    candidates = con.execute(query, [midpoint_vector]).fetchall()
    
    best_match = None
    best_match = None
    for cand in candidates:
        cand_id = cand[0]
        cand_artist = cand[2]
        
        if cand_id not in exclude_ids and cand_artist not in exclude_artists:
            best_match = cand
            break
    
    if not best_match:
        return []

    # Found a recursive step
    match_id = best_match[0]
    match_vec = best_match[5]
    match_obj = SearchResult(
        id=match_id,
        title=best_match[1],
        artist=best_match[2],
        album=best_match[3],
        relative_path=best_match[4],
        similarity=best_match[6]
    )
    
    exclude_ids.add(match_id)
    exclude_artists.add(best_match[2])
    
    # Recurse left (start -> match)
    left_path = recursive_interpolation(con, vec_a, match_vec, exclude_ids, exclude_artists, depth_limit - 1, method)
    
    # Recurse right (match -> end)
    right_path = recursive_interpolation(con, match_vec, vec_b, exclude_ids, exclude_artists, depth_limit - 1, method)
    
    return left_path + [match_obj] + right_path

@app.post("/interpolate/playlist", response_model=List[SearchResult])
def interpolate_playlist(request: InterpolationPlaylistRequest):
    try:
        con = get_db_connection()
        
        # 1. Get start and end vectors
        query_vectors = "SELECT id, v_mid, title, artist, album, relative_path, source, track_url, album_url, artist_url FROM tracks WHERE id IN (?, ?)"
        results = con.execute(query_vectors, [request.track_id_1, request.track_id_2]).fetchall()
        
        if len(results) != 2:
            con.close()
            raise HTTPException(status_code=404, detail="Could not find both start and end tracks")

        # Identify which is which (results order is not guaranteed)
        if results[0][0] == request.track_id_1:
            start_row = results[0]
            end_row = results[1]
        else:
            start_row = results[1]
            end_row = results[0]

        vec_start = start_row[1]
        vec_end = end_row[1]

        # 1.5 Fetch Steering Vector if requested
        vec_steer = None
        steer_row = None
        if request.steer_track_id:
            query_steer = "SELECT id, v_mid, title, artist, album, relative_path, source, track_url, album_url, artist_url FROM tracks WHERE id = ?"
            steer_row = con.execute(query_steer, [request.steer_track_id]).fetchone()
            if not steer_row:
                 # If steer track not found, fail or ignore? Let's fail for clarity.
                 con.close()
                 raise HTTPException(status_code=404, detail="Steering track not found")
            vec_steer = steer_row[1]
        
        # 2. Generate Path
        
        # --- STRATEGY A: GREEDY WALK (Graph Traversal) ---
        if request.method == "greedy_walk":
            
            if vec_steer:
                # Multi-stage walk: Start -> Steer -> End
                # Split limit roughly in half
                limit_a = math.ceil(request.limit / 2)
                limit_b = request.limit - limit_a
                
                # Part 1: Start -> Steer
                path_a = greedy_walk_interpolation(
                    con, vec_start, vec_steer, 
                    start_row[0], steer_row[0], 
                    start_row[2], steer_row[2], limit=limit_a,
                    source=request.source
                )
                
                # Part 2: Steer -> End
                path_b = greedy_walk_interpolation(
                    con, vec_steer, vec_end, 
                    steer_row[0], end_row[0], 
                    steer_row[2], end_row[2], limit=limit_b,
                    source=request.source
                )
                
                # Construct: Start + Path A + [Steer] + Path B + End
                steer_obj = SearchResult(
                    id=steer_row[0], title=steer_row[2], artist=steer_row[3], 
                    album=steer_row[4], relative_path=steer_row[5], 
                    source=steer_row[6], track_url=steer_row[7], 
                    album_url=steer_row[8], artist_url=steer_row[9],
                    similarity=1.0
                )
                
                # Note: path_a excludes start/end of its segment. 
                # So we manually insert the Steer object in the middle.
                path = path_a + [steer_obj] + path_b
                
            else:
                # Standard A -> B walk
                walk_limit = max(1, (request.limit or 10) - 2)
                path = greedy_walk_interpolation(
                    con, vec_start, vec_end, 
                    start_row[0], end_row[0], 
                    start_row[2], end_row[2], limit=walk_limit,
                    source=request.source
                )

        # --- STRATEGY B: GEOMETRIC (SLERP/Linear) ---
        else:
            exclude_ids = {request.track_id_1, request.track_id_2}
            
            if vec_steer:
                # Bezier Curve Interpolation
                exclude_ids.add(request.steer_track_id)
                
                # The limit is the number of intermediates
                # If we want the steer track to be INCLUDED in the list, 
                # Bezier math doesn't guarantee hitting the exact point P1, 
                # it just curves towards it.
                # If you want to explicitly include it, reduce limit and insert it? 
                # For now, let's just do the pure curve generation.
                
                path = bezier_interpolation(
                    con, vec_start, vec_steer, vec_end, exclude_ids, 
                    limit=max(1, (request.limit or 10) - 2)
                )
                
            else:
                # Standard Recursive Bisection
                exclude_artists = {start_row[2], end_row[2]}
                if request.limit and request.limit >= 3:
                    depth_limit = int(math.log2(request.limit - 1))
                else:
                    depth_limit = 0
                depth_limit = min(depth_limit, 6)

                path = recursive_interpolation(
                    con, vec_start, vec_end, exclude_ids, exclude_artists,
                    depth_limit=depth_limit, method=request.method
                )
        
        con.close()
        
        start_obj = SearchResult(
            id=start_row[0], title=start_row[2], artist=start_row[3], 
            album=start_row[4], relative_path=start_row[5], 
            source=start_row[6], track_url=start_row[7],
            album_url=start_row[8], artist_url=start_row[9],
            similarity=1.0
        )
        end_obj = SearchResult(
            id=end_row[0], title=end_row[2], artist=end_row[3], 
            album=end_row[4], relative_path=end_row[5], 
            source=end_row[6], track_url=end_row[7],
            album_url=end_row[8], artist_url=end_row[9],
            similarity=1.0
        )
        
        return [start_obj] + path + [end_obj]

    except Exception as e:
        print(f"Error generating playlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port)
