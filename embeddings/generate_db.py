import duckdb
import json
import os
import hashlib
import csv
import sys
from tqdm import tqdm

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(BASE_DIR, "../data/library")
DB_PATH = os.path.join(BASE_DIR, "../data/cloudcrate.duckdb")

# Library data paths
LIBRARY_JSONL_PATH = os.path.join(DATA_DIR, "embeddings.jsonl")
LIBRARY_JSON_PATH = os.path.join(DATA_DIR, "embeddings.json")
LIBRARY_CLAP_PATH = os.path.join(DATA_DIR, "clap_embeddings.jsonl")

# FMA data paths
FMA_DIR = os.path.join(BASE_DIR, "../data/fma")
FMA_EMBEDDINGS_PATH = os.path.join(FMA_DIR, "fma_embeddings.jsonl")
FMA_METADATA_PATH = os.path.join(FMA_DIR, "fma_metadata/raw_tracks.csv")
FMA_CLAP_PATH = os.path.join(FMA_DIR, "fma_clap_embeddings.jsonl")


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
    
    # Create per-source tables (no source column needed)
    table_ddl = """
        CREATE TABLE IF NOT EXISTS {table} (
            id VARCHAR PRIMARY KEY,
            title VARCHAR,
            artist VARCHAR,
            album VARCHAR,
            relative_path VARCHAR,
            track_url VARCHAR,
            album_url VARCHAR,
            artist_url VARCHAR,
            v_intro FLOAT[768],
            v_mid FLOAT[768],
            v_outro FLOAT[768],
            v_clap FLOAT[512]
        );
    """

    print("Creating table 'tracks_library'...")
    con.execute(table_ddl.format(table="tracks_library"))
    print("Creating table 'tracks_fma'...")
    con.execute(table_ddl.format(table="tracks_fma"))

    return con


def create_indexes(con):
    """Create HNSW, text indexes, and union view.

    Called AFTER all data is inserted so HNSW indexes are bulk-built
    rather than incrementally updated per-row (much smaller on disk).
    """
    print("\nCreating HNSW indexes (bulk build)...")
    con.execute("CREATE INDEX idx_library_mid ON tracks_library USING HNSW (v_mid) WITH (metric = 'cosine');")
    con.execute("CREATE INDEX idx_library_clap ON tracks_library USING HNSW (v_clap) WITH (metric = 'cosine');")
    con.execute("CREATE INDEX idx_fma_mid ON tracks_fma USING HNSW (v_mid) WITH (metric = 'cosine');")
    con.execute("CREATE INDEX idx_fma_clap ON tracks_fma USING HNSW (v_clap) WITH (metric = 'cosine');")

    # Union view for backward compatibility (text search, sample, etc.)
    print("Creating union view 'tracks'...")
    con.execute("""
        CREATE VIEW tracks AS
          SELECT *, 'library' as source FROM tracks_library
          UNION ALL
          SELECT *, 'fma' as source FROM tracks_fma;
    """)

    # Create text indexes on both tables
    print("Creating text indexes...")
    for table in ("tracks_library", "tracks_fma"):
        con.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_title ON {table} (title);")
        con.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_artist ON {table} (artist);")
        con.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_album ON {table} (album);")


def generate_track_id(source, artist, album, title):
    """Create a consistent hash ID, including source to prevent collisions."""
    raw = f"{source}|{artist}|{album}|{title}"
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def load_clap_data(clap_path):
    """Load CLAP embeddings into a dictionary keyed by relative_path."""
    clap_map = {}
    
    if not os.path.exists(clap_path):
        print(f"  Note: CLAP embeddings not found at {clap_path}. Using zero vectors.")
        return clap_map
    
    print(f"  Loading CLAP embeddings from {clap_path}...")
    with open(clap_path, 'r') as f:
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
    
    print(f"  Loaded {len(clap_map)} CLAP embeddings.")
    return clap_map


def load_library_data():
    """Load library tracks from embeddings files."""
    print("\n📚 Loading Library Data...")
    
    clap_map = load_clap_data(LIBRARY_CLAP_PATH)
    
    # Determine which MERT file to load
    target_path = None
    file_type = None
    
    if os.path.exists(LIBRARY_JSONL_PATH):
        target_path = LIBRARY_JSONL_PATH
        file_type = 'jsonl'
    elif os.path.exists(LIBRARY_JSON_PATH):
        target_path = LIBRARY_JSON_PATH
        file_type = 'json'
    else:
        print(f"  Warning: No library embeddings found.")
        return []

    print(f"  Loading MERT data from {target_path} ({file_type})...")
    
    track_data_list = []
    
    if file_type == 'json':
        with open(target_path, 'r') as f:
            data = json.load(f)
            items = data if isinstance(data, list) else []
        
        for info in tqdm(items, desc="  Loading library", unit="tracks"):
            artist = info.get('artist', 'Unknown')
            album = info.get('album', 'Unknown')
            title = info.get('title', 'Unknown')
            relative_path = info.get('relative_path', '')
            
            track_id = generate_track_id('library', artist, album, title)
            
            v_intro = info.get('v_intro')
            v_mid = info.get('v_mid')
            v_outro = info.get('v_outro')
            
            if not v_mid:
                continue

            if artist == "Unknown" and album == "Unknown" and title == "Unknown":
                continue

            v_clap = clap_map.get(relative_path, [0.0] * 512)
            
            track_data_list.append((
                track_id,
                title,
                artist,
                album,
                relative_path,
                None,
                None,
                None,
                v_intro,
                v_mid,
                v_outro,
                v_clap
            ))
    else:
        # JSONL: count lines first for progress bar
        with open(target_path, 'r') as f:
            total_lines = sum(1 for _ in f)
        
        with open(target_path, 'r') as f:
            for line in tqdm(f, total=total_lines, desc="  Loading library", unit="tracks"):
                if not line.strip():
                    continue
                info = json.loads(line)
                
                artist = info.get('artist', 'Unknown')
                album = info.get('album', 'Unknown')
                title = info.get('title', 'Unknown')
                relative_path = info.get('relative_path', '')
                
                track_id = generate_track_id('library', artist, album, title)
                
                v_intro = info.get('v_intro')
                v_mid = info.get('v_mid')
                v_outro = info.get('v_outro')
                
                if not v_mid:
                    continue

                if artist == "Unknown" and album == "Unknown" and title == "Unknown":
                    continue

                v_clap = clap_map.get(relative_path, [0.0] * 512)
                
                track_data_list.append((
                    track_id,
                    title,
                    artist,
                    album,
                    relative_path,
                    None,
                    None,
                    None,
                    v_intro,
                    v_mid,
                    v_outro,
                    v_clap
                ))

    print(f"  Found {len(track_data_list)} library tracks.")
    return track_data_list


def load_fma_metadata():
    """Load FMA track metadata from CSV into a lookup dictionary."""
    if not os.path.exists(FMA_METADATA_PATH):
        print(f"  Warning: FMA metadata not found at {FMA_METADATA_PATH}")
        return {}
    
    print(f"  Loading FMA metadata from {FMA_METADATA_PATH}...")
    metadata = {}
    
    with open(FMA_METADATA_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                track_id = int(row['track_id'])
                metadata[track_id] = {
                    'title': row.get('track_title', ''),
                    'artist': row.get('artist_name', ''),
                    'album': row.get('album_title', ''),
                    'track_url': row.get('track_url', ''),
                    'album_url': row.get('album_url', ''),
                    'artist_url': row.get('artist_url', '')
                }
            except (ValueError, KeyError):
                continue
    
    print(f"  Loaded metadata for {len(metadata)} FMA tracks.")
    return metadata


def load_fma_data():
    """Load FMA tracks from embeddings and join with metadata."""
    print("\n🎵 Loading FMA Data...")
    
    if not os.path.exists(FMA_EMBEDDINGS_PATH):
        print(f"  Warning: FMA embeddings not found at {FMA_EMBEDDINGS_PATH}")
        return []
    
    # Load metadata for joining
    metadata = load_fma_metadata()
    
    # Load CLAP embeddings if available
    clap_map = load_clap_data(FMA_CLAP_PATH)
    
    print(f"  Loading FMA embeddings from {FMA_EMBEDDINGS_PATH}...")
    
    track_data_list = []
    no_metadata_count = 0
    
    # Count lines for progress bar
    with open(FMA_EMBEDDINGS_PATH, 'r') as f:
        total_lines = sum(1 for _ in f)
    
    with open(FMA_EMBEDDINGS_PATH, 'r') as f:
        for line in tqdm(f, total=total_lines, desc="  Loading FMA", unit="tracks"):
            line = line.strip()
            if not line:
                continue
            
            try:
                info = json.loads(line)
            except json.JSONDecodeError:
                continue
            
            # Extract track_id from filename (e.g., "050833.mp3" -> 50833)
            filename = info.get('filename', '')
            try:
                track_id_num = int(filename.replace('.mp3', ''))
            except ValueError:
                continue
            
            relative_path = info.get('relative_path', '')
            v_mid = info.get('v_mid')
            
            if not v_mid:
                continue
            
            # Join with metadata
            meta = metadata.get(track_id_num)
            if not meta:
                no_metadata_count += 1
                continue
            
            title = meta['title'] or 'Unknown'
            artist = meta['artist'] or 'Unknown'
            album = meta['album'] or 'Unknown'
            
            # Use track_id_num as string for ID to ensure uniqueness
            track_id = f"fma_{track_id_num}"
            
            # FMA embeddings only have v_mid
            v_intro = info.get('v_intro')
            v_outro = info.get('v_outro')
            
            v_clap = clap_map.get(relative_path, [0.0] * 512)
            
            track_data_list.append((
                track_id,
                title,
                artist,
                album,
                relative_path,
                meta['track_url'],
                meta['album_url'],
                meta['artist_url'],
                v_intro,
                v_mid,
                v_outro,
                v_clap
            ))

    print(f"  Found {len(track_data_list)} FMA tracks with metadata.")
    if no_metadata_count > 0:
        print(f"  Skipped {no_metadata_count} tracks without metadata.")
    
    return track_data_list


def insert_tracks(con, track_data_list, source_name, chunk_size=1000):
    """Batch insert tracks into the appropriate per-source table."""
    if not track_data_list:
        return

    table = "tracks_library" if source_name == "library" else "tracks_fma"
    total = len(track_data_list)
    print(f"Inserting {total} {source_name} tracks into {table}...")

    # Insert in chunks with progress bar
    for i in tqdm(range(0, total, chunk_size), desc=f"  Inserting {source_name}", unit="batch"):
        chunk = track_data_list[i:i + chunk_size]
        con.executemany(f"""
            INSERT OR IGNORE INTO {table}
            (id, title, artist, album, relative_path, track_url, album_url, artist_url, v_intro, v_mid, v_outro, v_clap)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, chunk)


def main(limit=None):
    try:
        con = initialize_db()
        
        # Load and insert library data
        library_tracks = load_library_data()
        if limit:
            library_tracks = library_tracks[:limit]
        insert_tracks(con, library_tracks, "library")
        
        # Load and insert FMA data
        fma_tracks = load_fma_data()
        if limit:
            fma_tracks = fma_tracks[:limit]
        insert_tracks(con, fma_tracks, "FMA")

        # Build indexes after all data is loaded (bulk build)
        create_indexes(con)

        # Force write to disk
        print("\nCheckpointing to disk...")
        con.execute("CHECKPOINT;")
        
        # Verify counts
        print("\n" + "=" * 50)
        print("📊 Database Summary:")
        lib_count = con.execute("SELECT COUNT(*) FROM tracks_library").fetchone()[0]
        fma_count = con.execute("SELECT COUNT(*) FROM tracks_fma").fetchone()[0]
        print(f"   Total tracks: {lib_count + fma_count}")
        print(f"   - library: {lib_count}")
        print(f"   - fma: {fma_count}")

        # Verify HNSW indexes
        indexes = con.execute("SELECT index_name FROM duckdb_indexes()").fetchall()
        print(f"   Indexes: {[idx[0] for idx in indexes]}")
        
        con.close()
        print(f"\n✅ Database created at {DB_PATH}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    import sys
    limit = None
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
            print(f"🔬 Running in sample mode with limit={limit}")
        except ValueError:
            pass
    main(limit=limit)
