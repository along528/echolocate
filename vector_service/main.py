import duckdb
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import os
import math

app = FastAPI()

# Configuration
DB_PATH = os.getenv("DB_PATH", "cloudcrate.duckdb")

# Pydantic Models
class SearchRequest(BaseModel):
    vector: List[float]
    limit: Optional[int] = 10

class SearchResult(BaseModel):
    id: str
    title: str
    artist: str
    album: str
    relative_path: str
    similarity: float

class TrackResponse(BaseModel):
    id: str
    title: str
    artist: str
    album: str
    relative_path: str

class InterpolationRequest(BaseModel):
    track_id_1: str
    track_id_2: str
    limit: Optional[int] = 10

@app.on_event("startup")
async def startup_event():
    # Verify DB exists
    if not os.path.exists(DB_PATH):
        print(f"WARNING: Database file not found at {DB_PATH}")
    else:
        print(f"Database found at {DB_PATH}")

def get_db_connection():
    # Connect in Read-Only mode to allow concurrency/cloud run compatibility
    # Note: We need to load vss every time for the connection
    con = duckdb.connect(DB_PATH, read_only=True)
    con.execute("INSTALL vss; LOAD vss;") 
    return con

@app.get("/")
def health_check():
    return {"status": "ok", "service": "cloudcrate-vector"}

@app.get("/tracks", response_model=List[TrackResponse])
def list_tracks(limit: int = 50, offset: int = 0):
    try:
        con = get_db_connection()
        query = "SELECT id, title, artist, album, relative_path FROM tracks LIMIT ? OFFSET ?"
        results = con.execute(query, [limit, offset]).fetchall()
        con.close()
        
        response = []
        for row in results:
            response.append(TrackResponse(
                id=row[0],
                title=row[1],
                artist=row[2],
                album=row[3],
                relative_path=row[4]
            ))
        return response
    except Exception as e:
        print(f"Error listing tracks: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tracks/{track_id}/similar", response_model=List[SearchResult])
def find_similar(track_id: str, limit: int = 10):
    try:
        con = get_db_connection()
        
        # 1. Get the vector for the target track
        # We use v_mid as the default representation
        vector_query = "SELECT v_mid FROM tracks WHERE id = ?"
        vector_result = con.execute(vector_query, [track_id]).fetchone()
        
        if not vector_result:
            con.close()
            raise HTTPException(status_code=404, detail="Track not found")
            
        target_vector = vector_result[0]
        
        # 2. Search for similar tracks, excluding the track itself
        query = """
            SELECT id, title, artist, album, relative_path, array_cosine_similarity(v_mid, ?::FLOAT[768]) as similarity
            FROM tracks
            WHERE id != ?
            ORDER BY similarity DESC
            LIMIT ?
        """
        
        results = con.execute(query, [target_vector, track_id, limit]).fetchall()
        con.close()
        
        response = []
        for row in results:
            response.append(SearchResult(
                id=row[0],
                title=row[1],
                artist=row[2],
                album=row[3],
                relative_path=row[4],
                similarity=row[5]
            ))
            
        return response
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error finding similar tracks: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search", response_model=List[SearchResult])
def search_tracks(request: SearchRequest):
    try:
        con = get_db_connection()
        
        # Ensure vector is correct dimension (optional check, but DB will throw if wrong)
        if len(request.vector) != 768:
            raise HTTPException(status_code=400, detail=f"Vector must be 768 dimensions, got {len(request.vector)}")

        # Perform Query
        # Using v_mid as the default representation for search
        
        query = """
            SELECT id, title, artist, album, relative_path, array_cosine_similarity(v_mid, ?::FLOAT[768]) as similarity
            FROM tracks
            ORDER BY similarity DESC
            LIMIT ?
        """
        
        results = con.execute(query, [request.vector, request.limit]).fetchall()
        
        con.close()
        
        # Format results
        response = []
        for row in results:
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
        print(f"Error during search: {e}")
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
        
        midpoint_vector = [(a + b) / 2.0 for a, b in zip(vec1, vec2)]
        
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

def recursive_interpolation(con, vec_a, vec_b, exclude_ids, depth_limit):
    if depth_limit <= 0:
        return []

    # Calculate midpoint
    midpoint_vector = [(a + b) / 2.0 for a, b in zip(vec_a, vec_b)]

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
    for cand in candidates:
        cand_id = cand[0]
        if cand_id not in exclude_ids:
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
    
    # Recurse left (start -> match)
    left_path = recursive_interpolation(con, vec_a, match_vec, exclude_ids, depth_limit - 1)
    
    # Recurse right (match -> end)
    right_path = recursive_interpolation(con, match_vec, vec_b, exclude_ids, depth_limit - 1)
    
    return left_path + [match_obj] + right_path

@app.post("/interpolate/playlist", response_model=List[SearchResult])
def interpolate_playlist(request: InterpolationPlaylistRequest):
    try:
        con = get_db_connection()
        
        # 1. Get start and end vectors
        query_vectors = "SELECT id, v_mid, title, artist, album, relative_path FROM tracks WHERE id IN (?, ?)"
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
        
        # Initialize exclusion set with start and end tracks to avoid selecting them as intermediates
        exclude_ids = {request.track_id_1, request.track_id_2}
        
        # 2. Generate Path
        # The algorithm produces 2^depth + 1 songs.
        # We calculate the max depth that fits within the requested limit.
        # 2^depth + 1 <= limit  =>  2^depth <= limit - 1  =>  depth <= log2(limit - 1)
        
        if request.limit and request.limit >= 3:
            depth_limit = int(math.log2(request.limit - 1))
        else:
            depth_limit = 0 # Just start and end
            
        # Hard cap depth to avoid performance issues (e.g. depth 5 = 33 songs, depth 6 = 65)
        # Let's allow up to depth 6 (65 songs) if they really want it.
        depth_limit = min(depth_limit, 6)

        path = recursive_interpolation(con, vec_start, vec_end, exclude_ids, depth_limit=depth_limit)
        
        con.close()
        
        # Construct full response: [Start] + Path + [End]
        # Or just the path? The request says "Return the playlist ordered by the connected segments"
        # Usually a playlist between A and B includes A and B.
        
        start_obj = SearchResult(
            id=start_row[0], title=start_row[2], artist=start_row[3], album=start_row[4], relative_path=start_row[5], similarity=1.0
        )
        end_obj = SearchResult(
            id=end_row[0], title=end_row[2], artist=end_row[3], album=end_row[4], relative_path=end_row[5], similarity=1.0
        )
        
        # Filter path if it exceeds limit (though our depth limit helps, we can allow user to cut it short?)
        # Standardize: Return Start -> ... -> End
        final_playlist = [start_obj] + path + [end_obj]
        
        # If user provided a specific numerical limit, we might want to respect that?
        # But this algorithm produces 2^N - 1 intermediates.
        # We will stick to the generated path.
        
        return final_playlist

    except Exception as e:
        print(f"Error generating playlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))
