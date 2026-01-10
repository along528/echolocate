from google.cloud import bigquery
import argparse

def setup_bq(project_id, dataset_id, table_id):
    client = bigquery.Client(project=project_id)
    
    # Create Dataset if not exists
    dataset_ref = client.dataset(dataset_id)
    try:
        client.get_dataset(dataset_ref)
        print(f"Dataset {dataset_id} already exists.")
    except Exception:
        print(f"Creating dataset {dataset_id}...")
        client.create_dataset(bigquery.Dataset(dataset_ref))

    # Define Schema
    schema = [
        bigquery.SchemaField("id", "STRING", mode="REQUIRED", description="Apple Music Catalog ID"),
        bigquery.SchemaField("title", "STRING", mode="REQUIRED", description="Track Title"),
        bigquery.SchemaField("artist_name", "STRING", mode="REQUIRED", description="Artist Name"),
        bigquery.SchemaField("play_count", "INTEGER", mode="NULLABLE", description="User play history"),
        bigquery.SchemaField("last_played_at", "TIMESTAMP", mode="NULLABLE", description="Last play date"),
        bigquery.SchemaField("editorial_summary", "STRING", mode="NULLABLE", description="LLM-generated WXYC-style description"),
        # Note: Vector fields are created slightly differently or updated later, 
        # but for standard BQ table creation we can placeholder it or rely on specific vector index DDL later.
        # For this script we will add a float array field which is typical for vector storage before index creation,
        # OR we leave it for the process/embedding step to schema-evolve.
        # Let's add it as a REPEATED FLOAT for now which is the standard BQ vector representation.
        bigquery.SchemaField("vibe_embedding", "FLOAT", mode="REPEATED", description="1536-dim vector for semantic search")
    ]

    table_ref = dataset_ref.table(table_id)
    table = bigquery.Table(table_ref, schema=schema)

    try:
        client.get_table(table_ref)
        print(f"Table {table_id} already exists.")
    except Exception:
        print(f"Creating table {table_id}...")
        client.create_table(table)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup Cloud Crate BigQuery")
    parser.add_argument("--project", required=True, help="GCP Project ID")
    parser.add_argument("--dataset", default="cloud_crate", help="BigQuery Dataset ID")
    parser.add_argument("--table", default="library_tracks", help="BigQuery Table ID")
    
    args = parser.parse_args()
    setup_bq(args.project, args.dataset, args.table)
