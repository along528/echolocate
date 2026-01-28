import duckdb
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "../data")
DB_PATH = os.path.join(DATA_DIR, "cloudcrate.duckdb")
JSON_PATH = os.path.join(DATA_DIR, "embeddings_sample.json")

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
            embedding FLOAT[768]
        );
    """)
    
    # Create HNSW Index
    print("Creating HNSW index...")
    con.execute("""
        CREATE INDEX IF NOT EXISTS sonic_idx 
        ON tracks USING HNSW (embedding) 
        WITH (metric = 'cosine');
    """)
    
    return con

def load_data(con):
    if not os.path.exists(JSON_PATH):
        print(f"Error: {JSON_PATH} not found.")
        return

    print(f"Loading data from {JSON_PATH}...")
    with open(JSON_PATH, 'r') as f:
        data = json.load(f)
    
    track_data_list = []
    
    # Structure is list of dicts with keys: filename, path, duration, v_intro, v_mid, v_outro
    if isinstance(data, list):
        for info in data:
            # Use path as ID since it's unique
            track_id = info.get('path') or info.get('filename')
            
            # Prefer v_mid, fallback to others
            embedding = info.get('v_mid') or info.get('v_intro') or info.get('v_outro')
            
            if not track_id or not embedding:
                print(f"Skipping track without ID or embedding: {info.get('filename')}")
                continue
                
            # Naive metadata extraction from path "crate/Artist/Title.mp3"
            # path: "crate/Rage/7 Renegades of Funk.mp3"
            try:
                parts = track_id.split('/')
                if len(parts) >= 2:
                    artist = parts[-2]
                    filename = parts[-1]
                    title = os.path.splitext(filename)[0]
                    album = "Unknown" # Not in path
                else:
                    artist = "Unknown"
                    title = track_id
                    album = "Unknown"
            except:
                artist = "Unknown"
                title = track_id
                album = "Unknown"

            track_data_list.append((track_id, title, artist, album, embedding))

    print(f"Inserting {len(track_data_list)} tracks...")
    
    # Batch insert
    con.executemany("""
        INSERT OR IGNORE INTO tracks (id, title, artist, album, embedding) 
        VALUES (?, ?, ?, ?, ?)
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
