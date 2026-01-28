import duckdb
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import os

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
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error during interpolation: {e}")
        raise HTTPException(status_code=500, detail=str(e))
