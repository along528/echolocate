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

### Step 6: Export Real Library (Optional)
This step requires running on a Mac with Apple Music library configured.
```bash
cd edge
./build_and_run.sh

# Check Output
# The app will write to `crate/my_library.json` in the project root.

cd ..
# Ingest the real data
python backend/ingest_library.py --input crate/my_library.json --project YOUR_PROJECT_ID
```

### Step 7: Run Local Mode (No Cloud Required)
If you want to use the MCP server with just your local JSON data (no BigQuery/Vertex AI):

1. **Setup Python Env:**
   ```bash
   # Create venv (Python 3.10+ required)
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r backend/requirements.txt
   ```

2. **Run Edge Tool (if not already done):**
   ```bash
   cd edge
   ./build_and_run.sh
   cd ..
   ```

3. **Start Local Server:**
   ```bash
   # This runs the server over stdio. 
   # Connect this to your MCP client (e.g. Claude Desktop).
   # Use the absolute path to your python executable if configuring an external app.
   python backend/local_server.py
   ```

### Client Configuration (Claude Desktop)
To use this with Claude Desktop, add the following to your `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cloud-crate": {
      "command": "/Users/alex.long/Projects/cloud-crate/.venv/bin/python3",
      "args": [
        "/Users/alex.long/Projects/cloud-crate/backend/local_server.py"
      ]
    }
  }
}
```

