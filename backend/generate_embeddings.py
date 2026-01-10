from google.cloud import bigquery
from google.cloud import aiplatform
from vertexai.language_models import TextEmbeddingModel
import argparse
import time

def generate_embeddings(project_id, location, dataset_id, table_id, mock=False):
    client = bigquery.Client(project=project_id)
    table_ref = f"{project_id}.{dataset_id}.{table_id}"
    
    # 1. Fetch rows that need embeddings (empty vibe_embedding)
    # Note: In a real scenario we'd check for NULL or empty array. 
    # For simplicity, we'll just check where array_length(vibe_embedding) = 0
    query = f"""
        SELECT id, editorial_summary 
        FROM `{table_ref}`
        WHERE ARRAY_LENGTH(vibe_embedding) = 0
        AND editorial_summary IS NOT NULL
    """
    
    query_job = client.query(query)
    rows = list(query_job.result())
    
    if not rows:
        print("No rows found needing embeddings.")
        return

    print(f"Found {len(rows)} rows to process.")

    # 2. Setup Vertex AI
    if not mock:
        aiplatform.init(project=project_id, location=location)
        model = TextEmbeddingModel.from_pretrained("text-embedding-004")
    
    # 3. Generate and Update
    for row in rows:
        track_id = row["id"]
        text = row["editorial_summary"]
        
        if mock:
            print(f"Mocking embedding for track {track_id}...")
            # Generate a random or zero vector of size 1536
            embedding_vector = [0.1] * 1536 
        else:
            print(f"Generating embedding for track {track_id}...")
            embeddings = model.get_embeddings([text])
            embedding_vector = embeddings[0].values
        
        # 4. Update BigQuery
        # In efficient prod systems we'd verify batches, but here we do row-by-row for MVP clarity
        update_query = f"""
            UPDATE `{table_ref}`
            SET vibe_embedding = {embedding_vector}
            WHERE id = '{track_id}'
        """
        client.query(update_query).result()
        
        # Rate limit precaution
        if not mock:
            time.sleep(0.1)

    print("Embedding generation complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Embeddings")
    parser.add_argument("--project", required=True, help="GCP Project ID")
    parser.add_argument("--location", default="us-central1", help="GCP Location")
    parser.add_argument("--dataset", default="cloud_crate", help="BigQuery Dataset ID")
    parser.add_argument("--table", default="library_tracks", help="BigQuery Table ID")
    parser.add_argument("--mock", action="store_true", help="Use mock embeddings instead of Vertex AI")

    args = parser.parse_args()
    generate_embeddings(args.project, args.location, args.dataset, args.table, args.mock)
