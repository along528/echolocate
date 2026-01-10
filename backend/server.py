from mcp.server.fastmcp import FastMCP
from google.cloud import bigquery
from vertexai.language_models import TextEmbeddingModel
import vertexai

# Initialize FastMCP
mcp = FastMCP("Cloud Crate")

# Configuration (In a real app, load from env)
PROJECT_ID = "cloud-crate-demo" # Replace with actual
LOCATION = "us-central1"
DATASET_ID = "cloud_crate"
TABLE_ID = "library_tracks"

# Global clients (lazy init recommended in prod, but simple here)
bq_client = bigquery.Client(project=PROJECT_ID)
try:
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    embedding_model = TextEmbeddingModel.from_pretrained("text-embedding-004")
except Exception as e:
    print(f"Warning: Vertex AI init failed (expected in local dev without creds): {e}")
    embedding_model = None

def get_query_embedding(text: str) -> list[float]:
    if not embedding_model:
        # Return mock embedding if model not available
        return [0.1] * 1536
    embeddings = embedding_model.get_embeddings([text])
    return embeddings[0].values

@mcp.tool()
def search_library(query: str, limit: int = 5) -> str:
    """
    Search the music library semantically using a natural language query.
    Args:
        query: The natural language search query (e.g. "80s ambient with synths")
        limit: Number of results to return
    """
    query_vector = get_query_embedding(query)
    
    # BigQuery Vector Search Syntax (Cosine Distance)
    # Using 'ML.DISTANCE' or standard cosine similarity implementation
    # Query assumes table has 'vibe_embedding' column
    
    sql = f"""
        SELECT 
            id, title, artist_name, editorial_summary,
            (1 - COSIM(vibe_embedding, {query_vector})) as similarity
        FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
        ORDER BY similarity DESC
        LIMIT {limit}
    """
    
    # Note: COSIM might not be standard BQ function without enabling specific plugins or UDFs. 
    # Standard way often involves `ML.DISTANCE(vibe_embedding, query_vector, 'COSINE')`
    # Let's use the ML.DISTANCE version for correctness in BQ Vector Search context.
    
    sql = f"""
        SELECT 
            id, title, artist_name, editorial_summary
        FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
        ORDER BY ML.DISTANCE(vibe_embedding, {query_vector}, 'COSINE') ASC
        LIMIT {limit}
    """

    try:
        query_job = bq_client.query(sql)
        results = []
        for row in query_job:
            results.append(f"- {row['title']} by {row['artist_name']}: {row['editorial_summary']}")
        
        return "\n".join(results) if results else "No matches found."
    except Exception as e:
        return f"Error executing search: {str(e)}"

@mcp.tool()
def get_track_context(track_id: str) -> str:
    """
    Get full metadata for a specific track by its ID.
    Args:
        track_id: The Apple Music Catalog ID
    """
    sql = f"""
        SELECT *
        FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
        WHERE id = '{track_id}'
    """
    try:
        query_job = bq_client.query(sql)
        row = next(iter(query_job), None)
        if row:
            return f"""
Title: {row['title']}
Artist: {row['artist_name']}
Play Count: {row['play_count']}
Last Played: {row['last_played_at']}
Summary: {row['editorial_summary']}
            """
        else:
            return "Track not found."
    except Exception as e:
        return f"Error fetching track: {str(e)}"

@mcp.tool()
def get_rotation(category: str) -> str:
    """
    Get tracks based on rotation category.
    Args:
        category: One of 'Heavy', 'Gold', 'Unplayed'
    """
    limit = 10
    if category.lower() == 'heavy':
        order_clause = "test ORDER BY play_count DESC" # Filtering for heavy rotation
        filter_clause = "play_count > 20"
    elif category.lower() == 'gold':
         # logic for gold usually implies classics, maybe high play count but not recently played?
         # Simplification: Random top rated
         filter_clause = "play_count > 50"
    elif category.lower() == 'unplayed':
        filter_clause = "play_count = 0"
    else:
        return "Unknown category. Use 'Heavy', 'Gold', or 'Unplayed'."

    sql = f"""
        SELECT title, artist_name, play_count
        FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
        WHERE {filter_clause}
        LIMIT {limit}
    """
    
    try:
        query_job = bq_client.query(sql)
        results = [f"- {row['title']} by {row['artist_name']} ({row['play_count']} plays)" for row in query_job]
        return "\n".join(results) if results else "No tracks found in this rotation."
    except Exception as e:
        return f"Error fetching rotation: {str(e)}"

if __name__ == "__main__":
    mcp.run()
