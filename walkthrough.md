# Cloud Crate Phase 1 Walkthrough

We have successfully implemented the MVP backend for **Cloud Crate**, focusing on the data pipeline and the MCP server structure.

## What We Built

### 1. Project Structure
- **/backend**: Contains all Python logic.
- **/edge**: Dictionary for future native code.

### 2. Data Pipeline
- **`backend/setup_bq.py`**: Initializes the BigQuery dataset and table schema.
- **`backend/ingest_library.py`**: Reads a JSON export of your library and uploads it to BigQuery.
- **`backend/generate_embeddings.py`**: Enriches the library data with semantic vectors.
    - Includes a `--mock` flag to simulate embedding generation without Vertex AI costs.

### 3. MCP Server
- **`backend/server.py`**: Implements the Model Context Protocol server.
    - **`search_library`**: Semantic search using vector similarity.
    - **`get_track_context`**: Detailed metadata fetch.
    - **`get_rotation`**: Logic-based filtering (Heavy, Gold, Unplayed).

## How to Run

### Prerequisites
- Python 3.10+
- Google Cloud Project with BigQuery and Vertex AI enabled.
- `gcloud` authenticated.

### Step 1: Install Dependencies
```bash
pip install -r backend/requirements.txt
```

### Step 2: Setup BigQuery
```bash
python backend/setup_bq.py --project YOUR_PROJECT_ID
```

### Step 3: Ingest Data
```bash
# Using the provided mock data
python backend/ingest_library.py --input backend/test_library.json --project YOUR_PROJECT_ID
```

### Step 4: Generate Embeddings
```bash
# Use --mock for testing without Vertex AI
python backend/generate_embeddings.py --project YOUR_PROJECT_ID --mock
```

### Step 5: Run MCP Server
```bash
# This requires the mcp command line tool or running the python script directly if configured
# Typically with FastMCP:
mcp run backend/server.py
```
