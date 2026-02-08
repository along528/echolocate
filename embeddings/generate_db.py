import duckdb
import json
import os
import hashlib
import csv

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
    
    # Create the schema with source and URL columns
    print("Creating table 'tracks'...")
    con.execute("""
        CREATE TABLE IF NOT EXISTS tracks (
            id VARCHAR PRIMARY KEY,
            source VARCHAR,
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
    """)
    
    # Create HNSW Indexes for vector columns
    print("Creating HNSW indexes...")
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_mid 
        ON tracks USING HNSW (v_mid) 
        WITH (metric = 'cosine');
    """)
    
    # Create text and filter indexes
    print("Creating text indexes...")
    con.execute("CREATE INDEX IF NOT EXISTS idx_source ON tracks (source);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_title ON tracks (title);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_artist ON tracks (artist);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_album ON tracks (album);")
    
    return con


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
    
    with open(target_path, 'r') as f:
        if file_type == 'json':
            data = json.load(f)
            items = data if isinstance(data, list) else []
        else:
            items = (json.loads(line) for line in f if line.strip())

        for info in items:
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
                'library',  # source
                title,
                artist,
                album,
                relative_path,
                None,  # track_url (not available for library)
                None,  # album_url
                None,  # artist_url
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
    
    with open(FMA_EMBEDDINGS_PATH, 'r') as f:
        for line in f:
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
                'fma',  # source
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


def insert_tracks(con, track_data_list, source_name):
    """Batch insert tracks into the database."""
    if not track_data_list:
        return
    
    print(f"Inserting {len(track_data_list)} {source_name} tracks...")
    
    con.executemany("""
        INSERT OR IGNORE INTO tracks 
        (id, source, title, artist, album, relative_path, track_url, album_url, artist_url, v_intro, v_mid, v_outro, v_clap) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, track_data_list)


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
        
        # Force write to disk
        print("\nCheckpointing to disk...")
        con.execute("CHECKPOINT;")
        
        # Verify counts
        print("\n" + "=" * 50)
        print("📊 Database Summary:")
        total = con.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        print(f"   Total tracks: {total}")
        
        source_counts = con.execute(
            "SELECT source, COUNT(*) FROM tracks GROUP BY source ORDER BY source"
        ).fetchall()
        for source, count in source_counts:
            print(f"   - {source}: {count}")
        
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
