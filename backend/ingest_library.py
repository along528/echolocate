import json
import argparse
from google.cloud import bigquery
from datetime import datetime

def ingest_library(input_file, project_id, dataset_id, table_id):
    client = bigquery.Client(project=project_id)
    table_ref = client.dataset(dataset_id).table(table_id)

    with open(input_file, 'r') as f:
        data = json.load(f)

    rows_to_insert = []
    for item in data:
        # Basic validation/cleaning
        row = {
            "id": item.get("id"),
            "title": item.get("title"),
            "artist_name": item.get("artist_name"),
            "play_count": item.get("play_count", 0),
            "last_played_at": item.get("last_played_at"), # Assumes ISO format in JSON
            "editorial_summary": item.get("editorial_summary"),
            "vibe_embedding": [] # Empty for now, will be filled by embedding service
        }
        rows_to_insert.append(row)

    if not rows_to_insert:
        print("No data to insert.")
        return

    errors = client.insert_rows_json(table_ref, rows_to_insert)
    if errors == []:
        print(f"New rows have been added to {table_id}.")
    else:
        print("Encountered errors while inserting rows: {}".format(errors))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest Library to BigQuery")
    parser.add_argument("--input", required=True, help="Path to JSON library file")
    parser.add_argument("--project", required=True, help="GCP Project ID")
    parser.add_argument("--dataset", default="cloud_crate", help="BigQuery Dataset ID")
    parser.add_argument("--table", default="library_tracks", help="BigQuery Table ID")

    args = parser.parse_args()
    ingest_library(args.input, args.project, args.dataset, args.table)
