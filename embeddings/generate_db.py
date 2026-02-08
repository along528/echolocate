import duckdb
import json
import os
import hashlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "../data")
DB_PATH = os.path.join(DATA_DIR, "cloudcrate.duckdb")
JSONL_PATH = os.path.join(DATA_DIR, "embeddings.jsonl")
JSON_PATH = os.path.join(DATA_DIR, "embeddings.json")
CLAP_JSONL_PATH = os.path.join(DATA_DIR, "clap_embeddings.jsonl")

def initialize_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Removed existing {DB_PATH}")

    print(f"Connecting to {DB_PATH}...")
    con = duckdb.connect(DB_PATH)
    
    # Load required extensions
    print("Installing and loading VSS extension...")
    con.execute("INSTALL vss; LOAD vss;")
    
    # ENABLE PERSISTENCE (Critical for saving vector index to disk)
    con.execute("SET hnsw_enable_experimental_persistence = true;")
    
    # Create the schema
    print("Creating table 'tracks'...")
    con.execute("""
        CREATE TABLE IF NOT EXISTS tracks (
            id VARCHAR PRIMARY KEY,
            title VARCHAR,
            artist VARCHAR,
            album VARCHAR,
            relative_path VARCHAR,
            v_intro FLOAT[768],
            v_mid FLOAT[768],
            v_outro FLOAT[768],
            v_clap FLOAT[512]
        );
    """)
    
    # Create HNSW Indexes for each vector column
    # Note: Creating multiple indexes might be heavy, but useful for different search types.
    print("Creating HNSW indexes...")
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_mid 
        ON tracks USING HNSW (v_mid) 
        WITH (metric = 'cosine');
    """)
    # We can add indexes for intro/outro later if needed for performance, 
    # but starting with mid is reasonable for main search.
    
    # Create text indexes for search
    print("Creating text indexes...")
    con.execute("CREATE INDEX IF NOT EXISTS idx_title ON tracks (title);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_artist ON tracks (artist);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_album ON tracks (album);")
    
    return con

def generate_track_id(artist, album, title):
    # Create a consistent hash ID
    raw = f"{artist}|{album}|{title}"
    return hashlib.md5(raw.encode('utf-8')).hexdigest()

def load_clap_data():
    """Load CLAP embeddings into a dictionary keyed by relative_path."""
    clap_map = {}
    
    if not os.path.exists(CLAP_JSONL_PATH):
        print(f"Warning: CLAP embeddings not found at {CLAP_JSONL_PATH}. Using zero vectors.")
        return clap_map
    
    print(f"Loading CLAP embeddings from {CLAP_JSONL_PATH}...")
    with open(CLAP_JSONL_PATH, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    data = json.loads(line)
                    rel_path = data.get('relative_path')
                    v_clap = data.get('v_clap')
                    if rel_path and v_clap:
                        clap_map[rel_path] = v_clap
                except json.JSONDecodeError:
                    pass
    
    print(f"Loaded {len(clap_map)} CLAP embeddings.")
    return clap_map


def load_data(con):
    # Load CLAP data first for hash join
    clap_map = load_clap_data()
    
    # Determine which MERT file to load
    target_path = None
    file_type = None
    
    if os.path.exists(JSONL_PATH):
        target_path = JSONL_PATH
        file_type = 'jsonl'
    elif os.path.exists(JSON_PATH):
        target_path = JSON_PATH
        file_type = 'json'
    else:
        print(f"Error: No embeddings file found (checked {JSONL_PATH} and {JSON_PATH}).")
        return

    print(f"Loading MERT data from {target_path} ({file_type})...")
    
    track_data_list = []
    
    with open(target_path, 'r') as f:
        if file_type == 'json':
            data = json.load(f)
            if isinstance(data, list):
                items = data
            else:
                items = []
        else:
            # JSONL: Read line by line generator
            items = (json.loads(line) for line in f if line.strip())

        for info in items:
            # Extract fields
            artist = info.get('artist', 'Unknown')
            album = info.get('album', 'Unknown')
            title = info.get('title', 'Unknown')
            relative_path = info.get('relative_path', '')
            
            # Generate ID
            track_id = generate_track_id(artist, album, title)
            
            # Vectors
            v_intro = info.get('v_intro')
            v_mid = info.get('v_mid')
            v_outro = info.get('v_outro')
            
            if not v_mid:
                 # print(f"Skipping track without v_mid: {info.get('filename')}")
                 continue

            if artist == "Unknown" and album == "Unknown" and title == "Unknown":
                print(f"Skipping track with completely missing metadata: {relative_path}")
                continue

            # Hash join: lookup CLAP vector by relative_path
            v_clap = clap_map.get(relative_path, [0.0] * 512)
            
            track_data_list.append((
                track_id, 
                title, 
                artist, 
                album, 
                relative_path, 
                v_intro, 
                v_mid, 
                v_outro,
                v_clap
            ))

    print(f"Inserting {len(track_data_list)} tracks...")
    
    # Batch insert
    # Note: for very large datasets (10k+), we might want to chunk this insert too,
    # but 10k rows is easily handled by DuckDB in one go.
    con.executemany("""
        INSERT OR IGNORE INTO tracks (id, title, artist, album, relative_path, v_intro, v_mid, v_outro, v_clap) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, track_data_list)
    
    # Force write to disk
    print("Checkpointing to disk...")
    con.execute("CHECKPOINT;")
    
    # Verify count
    count = con.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    print(f"✅ Successfully inserted {count} tracks.")

if __name__ == "__main__":
    try:
        con = initialize_db()
        load_data(con)
        con.close()
        print(f"✅ Database created at {DB_PATH}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
