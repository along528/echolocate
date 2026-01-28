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
    similarity: float

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

@app.post("/search", response_model=List[SearchResult])
def search_tracks(request: SearchRequest):
    try:
        con = get_db_connection()
        
        # Ensure vector is correct dimension (optional check, but DB will throw if wrong)
        if len(request.vector) != 768:
            raise HTTPException(status_code=400, detail=f"Vector must be 768 dimensions, got {len(request.vector)}")

        # Perform Query
        # We use array_cosine_similarity (or distance)
        # array_cosine_similarity returns -1 to 1. Higher is better. 
        # User requested metric='cosine' in index, which usually optimizes for distance, 
        # but let's return similarity for easier consumption.
        
        query = """
            SELECT id, title, artist, album, array_cosine_similarity(embedding, ?::FLOAT[768]) as similarity
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
                similarity=row[4]
            ))
            
        return response

    except Exception as e:
        print(f"Error during search: {e}")
        raise HTTPException(status_code=500, detail=str(e))
